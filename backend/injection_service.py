"""Service-side supervision. Native injection libraries never execute here."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import threading
import uuid

from PySide6.QtCore import QObject, QThread, QTimer, Signal


def injector_command(root: Path):
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).with_name("omg_injector.exe")
        if not executable.is_file():
            raise ValueError("缺少注入端 omg_injector.exe，请完整解压程序包")
        return [str(executable), "--injector", "--data-root", str(root)]
    return [sys.executable, "-u", str(Path(__file__).with_name("injector_main.py")),
            "--injector", "--data-root", str(root)]


class InjectionSupervisor(QThread):
    """Wait for a disposable child without blocking Qt's service loop."""
    def __init__(self, root, settings, command):
        super().__init__()
        self.root, self.settings, self.command = Path(root), copy.deepcopy(settings), list(command)
        self.verification_state = "not_checked"
        self.outcome = {"ok": False, "message": "注入端未完成任务"}
        self.stop_requested = threading.Event()

    def run(self):
        token = uuid.uuid4().hex
        work = self.root / "temp" / f"injection-{token}"
        log_root = self.root / "log"
        request = work / "request.json"
        result_path = work / "result.json"
        log_path = log_root / f"injector-{token}.log"
        try:
            work.mkdir(parents=True)
            log_root.mkdir(parents=True, exist_ok=True)
            request.write_text(json.dumps({"token": token, "settings": self.settings}), encoding="utf-8")
            command = self.command + ["--request-file", str(request), "--result-file", str(result_path)]
            with log_path.open("wb") as log:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, close_fds=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    env={**os.environ, "PYTHONUTF8": "1"})
                self._record(token, "started", injector_pid=process.pid)
                try:
                    deadline = time.monotonic() + 90
                    while True:
                        if self.stop_requested.is_set():
                            process.kill()
                            code = process.wait()
                            break
                        if time.monotonic() >= deadline:
                            raise subprocess.TimeoutExpired(command, 90)
                        try:
                            code = process.wait(timeout=.1)
                            break
                        except subprocess.TimeoutExpired:
                            pass
                except subprocess.TimeoutExpired:
                    # Only our injection host is stopped; never terminate the game.
                    process.kill()
                    code = process.wait()
                    self.outcome = {"ok": False, "message": "注入端等待超时，服务继续运行"}
                else:
                    if self.stop_requested.is_set():
                        self.outcome = {"ok": False, "message": "注入任务已随应用关闭"}
                    elif result_path.is_file() and result_path.stat().st_size <= 65536:
                        try:
                            result = json.loads(result_path.read_text(encoding="utf-8"))
                            if (not isinstance(result, dict) or result.get("token") != token
                                    or type(result.get("ok")) is not bool
                                    or not isinstance(result.get("message"), str)):
                                raise ValueError("注入端返回了无效的完成结果")
                            self.outcome = result if code == 0 else {
                                "ok": False, "message": f"注入端异常退出（{code}），服务继续运行"}
                        except (ValueError, OSError) as exc:
                            self.outcome = {"ok": False, "message": f"注入端结果无效：{exc}；服务继续运行"}
                    else:
                        self.outcome = {"ok": False,
                            "message": f"注入端提前退出（{code}），未返回完成结果；服务继续运行"}
                self.verification_state = self.outcome.get("verification", "not_checked")
                self._record(token, "exited", injector_pid=process.pid, exit_code=code,
                             result_received=result_path.is_file(), ok=self.outcome.get("ok", False))
        except Exception as exc:
            self.outcome = {"ok": False, "message": f"无法完成注入任务：{exc}"}
        finally:
            try:
                request.unlink(missing_ok=True)
            except OSError:
                pass

    def _record(self, token, event, **details):
        try:
            with (self.root / "log" / "injection-lifecycle.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"time": time.time(), "task": token, "event": event,
                    "service_pid": os.getpid(), **details}) + "\n")
                stream.flush()
        except OSError as exc:
            print(f"Unable to write injector lifecycle: {exc}", file=sys.stderr)


class IsolatedLaunchController(QObject):
    state_changed = Signal(str, str)
    finished = Signal(bool, str)

    def __init__(self, config, root):
        super().__init__()
        self.config, self.root = config, Path(root)
        self._worker = None
        self._state = "idle"
        self._active_target = ""
        self._exit_timer = QTimer(self)
        self._exit_timer.setInterval(1000)
        self._exit_timer.timeout.connect(self._on_exit_tick)

    def toggle(self):
        if self._state in ("injecting", "done"):
            return
        settings = copy.deepcopy(self.config.settings)
        game = settings.get("game_folder", "")
        gimi = settings.get("gimi_folder", "")
        if not game or not Path(game).is_dir():
            self._on_finished(False, "请先配置有效的游戏目录")
            return
        if not gimi or not (Path(gimi) / "d3dx.ini").is_file() or not (Path(gimi) / "d3d11.dll").is_file():
            self._on_finished(False, "请先配置包含 d3dx.ini 和 d3d11.dll 的 GIMI 目录")
            return
        try:
            command = injector_command(self.root)
        except ValueError as exc:
            self._on_finished(False, str(exc))
            return
        old = self._worker
        self._worker = InjectionSupervisor(self.root, settings, command)
        if old is not None:
            old.deleteLater()
        # Use QThread's real finished signal: the child has exited and the
        # supervision thread has fully returned before accepting another task.
        self._worker.finished.connect(self._on_child_finished)
        self._set_state("injecting", "正在运行独立注入端…")
        self._worker.start()

    def _on_child_finished(self):
        result = self._worker.outcome
        self._active_target = result.get("target", "") if result.get("ok") else ""
        self._on_finished(result.get("ok", False), result.get("message", "注入端未返回结果"))

    def request_stop(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.stop_requested.set()

    def _on_finished(self, ok, message):
        self._set_state("done" if ok else "error", message)
        if ok and self._active_target:
            self._exit_timer.start()
        else:
            self._stop_exit_watch()
        self.finished.emit(ok, message)

    def _set_state(self, state, message):
        self._state = state
        self.state_changed.emit(state, message)

    def _stop_exit_watch(self):
        self._exit_timer.stop()

    def _on_exit_tick(self):
        from omg.domain.inject.process_tracker import is_process_running
        if self._active_target and not is_process_running(self._active_target):
            self._stop_exit_watch()
            self._active_target = ""
            self._set_state("idle", "游戏已退出，可再次开始")
