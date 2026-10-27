"""One stdio backend per Neo application. Reuses OMGLite QtCore orchestration.

Qt Widgets and the old application entry point are never imported. Keeping
QtCore in this first slice avoids rewriting the proven launch state machine.
"""
from __future__ import annotations

import argparse
import copy
import json
import multiprocessing
import os
from pathlib import Path
import sys
import threading
import time
import traceback
import uuid

from settings_store import SettingsStore, DEFAULTS
from backend_runtime import bootstrap


def run_event_loop(app, should_close):
    """Only the protocol shutdown/EOF path may end the long-lived service."""
    last_exit = 0.0
    repeated = 0
    while True:
        code = app.exec()
        if should_close() or code != 0:
            return code
        now = time.monotonic()
        repeated = repeated + 1 if now - last_exit < 1 else 1
        last_exit = now
        print("Qt event loop exited without a shutdown request; resuming backend", file=sys.stderr)
        if repeated >= 3:
            print("Qt event loop repeatedly exited; stopping backend with error", file=sys.stderr)
            return 1



def serve(args):
    root = args.data_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = (root / ".backend.lock").open("a+b")
    if os.name == "nt":
        import msvcrt
        lock.seek(0)
        if not lock.read(1):
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    if getattr(sys, 'frozen', False):
        from updater_handoff import start_pending_updater
        start_pending_updater(Path(sys.executable).resolve().parent.parent)
    if sys.stdout is None or sys.stdin is None or sys.stderr is None:
        raise RuntimeError("后端必须以 stdio 管道启动")
    # Reserve the protocol pipe, then redirect both the CRT fd and Win32's
    # native stdout handle. DLLs and inherited launcher processes can write
    # directly to stdout without going through Python's sys.stdout wrapper.
    output = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
    sys.stdout.flush()
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    if os.name == "nt":
        import ctypes
        import msvcrt
        native = ctypes.WinDLL("kernel32", use_last_error=True)
        native.SetStdHandle.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
        native.SetStdHandle.restype = ctypes.c_int
        if not native.SetStdHandle(ctypes.c_ulong(-11), msvcrt.get_osfhandle(sys.stderr.fileno())):
            raise ctypes.WinError(ctypes.get_last_error())
    sys.stdin.reconfigure(encoding="utf-8", errors="strict")
    if sys.stderr:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    paths = bootstrap(root, args.lite_src)
    from PySide6.QtCore import QCoreApplication, QObject, QThread, QTimer, Signal, Slot
    from omg.domain.inject.loader import patch_d3dx_runtime_options, find_game_exe
    from omg.domain.inject.process_tracker import is_process_running
    from injection_service import IsolatedLaunchController
    from omg.core.logging_setup import logger as legacy_logger
    import logging
    domain_log = logging.getLogger("omg")
    domain_log.setLevel(logging.DEBUG)
    domain_log.propagate = False
    for handler in legacy_logger.handlers:
        if handler not in domain_log.handlers:
            domain_log.addHandler(handler)

    write_lock = threading.Lock()

    def send(message):
        with write_lock:
            try:
                output.write(json.dumps({"v": 1, **message}, ensure_ascii=False) + "\n")
                output.flush()
            except (BrokenPipeError, OSError):
                pass  # stdin EOF still drives orderly worker cleanup.

    class Worker(QThread):
        completed = Signal(object)
        progress = Signal(object)

        def __init__(self, function):
            super().__init__()
            self.function = function
            self.cancel = threading.Event()

        def run(self):
            try:
                result = self.function(self)
                self.completed.emit({"result": result})
            except Exception as exc:
                traceback.print_exc(file=sys.stderr)
                self.completed.emit({"error": str(exc)})

    class DownloadSink:
        class Emitter:
            def __init__(self, emit):
                self.emit = emit

        def __init__(self, worker):
            self.progress = self.Emitter(lambda p: worker.progress.emit(
                {"progress": max(0., min(.85, float(p) / 100 * .85))}))
            self.status = self.Emitter(lambda text, role="info": worker.progress.emit(
                {"message": text}))

    class Bridge(QObject):
        incoming = Signal(object)

        def __init__(self):
            super().__init__()
            self.config = SettingsStore(root)
            self.worker = None
            self.active = None
            self.task_id = None
            self.closing = False
            self.seq = 0
            self.release = None
            self.release_root = None
            self.launch = IsolatedLaunchController(self.config, root)
            self.launch_state = "idle"
            self.launch_detail = ""
            self.launch.state_changed.connect(self.launch_changed)
            self.launch.finished.connect(self.launch_finished)
            self.ini_timer = QTimer(self)
            self.ini_timer.setSingleShot(True)
            self.ini_timer.timeout.connect(self.flush_ini_event)
            self.ini_dirty_since = None
            self.incoming.connect(self.dispatch)
            self.shutdown_timer = QTimer(self)
            self.shutdown_timer.timeout.connect(self.try_shutdown)
            self._resources = None
            self._builds = None
            from bisect_service import BisectService
            self.bisect = BisectService(root, self.config)

        @property
        def resources(self):
            if self._resources is None:
                from resource_service import ResourceService
                self._resources = ResourceService(root, self.config)
            return self._resources

        @property
        def builds(self):
            if self._builds is None:
                from build_service import BuildService
                self._builds = BuildService(root, self.config, self.game_stopped)
            return self._builds

        def emit_event(self, event, data):
            self.seq += 1
            send({"seq": self.seq, "event": event, "data": data})

        def versions(self):
            gimi = self.config.get_gimi_dir()
            return {"GIMI": paths.read_gimi_version_from_ini(gimi) if gimi else "",
                    "ORFix": paths.read_orfix_version(gimi) if gimi else "",
                    "TexFx": paths.read_teffx_version(gimi) if gimi else ""}

        def state(self):
            return {**self.config.snapshot(), "versions": self.versions(),
                    "launchState": self.launch_state, "launchDetail": self.launch_detail,
                    "activeTask": self.task_id, "eventSeq": self.seq, "bisectActive": self.bisect.active}

        def schedule_ini(self):
            now = time.monotonic()
            if self.ini_dirty_since is None:
                self.ini_dirty_since = now
            remaining = 1.5 - (now - self.ini_dirty_since)
            self.ini_timer.start(max(0, min(400, int(remaining * 1000))))

        def flush_ini(self):
            if self.ini_dirty_since is None:
                return {"status": "unchanged"}
            self.ini_timer.stop()
            gimi = self.config.get_gimi_dir()
            if not gimi or not (Path(gimi) / "d3dx.ini").is_file():
                self.ini_dirty_since = None
                return {"status": "skipped", "message": "配置已保存；GIMI 未配置或缺少 d3dx.ini"}
            changed = patch_d3dx_runtime_options(
                Path(gimi) / "d3dx.ini", self.config.get("hunting"), self.config.get("warning"))
            self.ini_dirty_since = None
            return {"status": "written" if changed else "unchanged",
                    "message": "INI 已同步；游戏内需重新加载或下次启动生效"}

        @Slot()
        def flush_ini_event(self):
            try:
                self.emit_event("settings.ini", self.flush_ini())
            except Exception as exc:
                self.emit_event("settings.ini", {"status": "error", "message": str(exc)})

        def idle_required(self):
            if self.active or self.launch_state == "injecting":
                raise ValueError("已有任务正在执行，请稍后重试")

        def game_stopped(self, settings):
            game = settings.get("game_folder", "")
            targets = {"YuanShen.exe", "GenshinImpact.exe"}
            if game and Path(game).is_dir():
                _, target = find_game_exe(Path(game))
                if target:
                    targets.add(target)
            if any(is_process_running(target) for target in targets):
                raise ValueError("游戏正在运行，请退出游戏后更新")

        def start_worker(self, kind, function):
            self.idle_required()
            self.task_id = uuid.uuid4().hex
            self.active = kind
            self.worker = Worker(function)
            self.worker.progress.connect(self.progress)
            self.worker.completed.connect(self.completed)
            self.worker.start()
            return {"taskId": self.task_id, "kind": kind}

        @Slot(object)
        def progress(self, data):
            self.emit_event("task.progress", {"taskId": self.task_id, "kind": self.active, **data})

        @Slot(object)
        def completed(self, data):
            kind, task_id = self.active, self.task_id
            worker = self.worker
            if worker is None:
                return
            cancelled, result, error = False, {}, None
            try:
                worker.wait()
                cancelled = worker.cancel.is_set()
                result = data.get("result", {})
                error = data.get("error")
                if kind == "resources.writeback" and (result.get("ok") is False or result.get("failures")):
                    error = result.get("message", "部分文件未能写回")
                if kind == "build.cleanup.apply" and result.get("errors"):
                    error = result.get("message", "部分文件清理失败")
                if kind and kind.startswith("bisect."):
                    result["bisect"] = self.bisect.state()
                    result["message"] = self.bisect.state().get("message", "二分状态已更新")
                if kind and kind.startswith("build.") and "build" not in result:
                    result["build"] = self.builds.state()
                if not error and kind == "check" and not cancelled:
                    self.release = result.pop("release", None)
                    self.release_root = self.config.get_gimi_dir()
                    if self.release:
                        try:
                            self.config.commit({}, metadata={"checkedAt": int(time.time())})
                        except OSError as exc:
                            error = f"检查完成，但保存检查时间失败：{exc}"
                result.pop("release", None)
                if not error and kind == "update":
                    if result.get("ok"):
                        self.release = None
                    else:
                        error = result.get("message", "更新失败")
            except Exception as exc:
                traceback.print_exc(file=sys.stderr)
                detail = f"任务已结束，但收尾失败：{exc}"
                error = f"{error}；{detail}" if error else detail
            finally:
                # Optional state refresh must never retain a completed worker or
                # leave shutdown waiting forever on a stale busy reference.
                self.worker = None
                self.active = self.task_id = None
                worker.deleteLater()
            state = "succeeded" if not error else "failed"
            if cancelled and not (kind == "update" and result.get("ok")) and not (kind == "resources.writeback" and result.get("changedFiles")):
                state = "cancelled"
            event = {"taskId": task_id, "kind": kind, "state": state,
                     "message": error or result.get("message", "完成"), "result": result}
            try:
                event["snapshot"] = self.state()
            except Exception as exc:
                traceback.print_exc(file=sys.stderr)
                event["state"] = "failed"
                event["message"] = f"{event['message']}；读取当前状态失败：{exc}"
            self.emit_event("task.finished", event)

        @Slot(str, str)
        def launch_changed(self, state, detail):
            worker = getattr(self.launch, "_worker", None)
            if state == "done" and getattr(worker, "verification_state", None) == "inconclusive":
                state = "unverified"
            self.launch_state, self.launch_detail = state, detail
            self.emit_event("launch.state", {"state": state, "message": detail})

        @Slot(bool, str)
        def launch_finished(self, ok, message):
            task_id = self.task_id
            self.active = self.task_id = None
            self.emit_event("task.finished", {"taskId": task_id, "kind": "launch",
                       "state": "succeeded" if ok else "failed", "message": message,
                       "verification": getattr(getattr(self.launch, "_worker", None),
                                               "verification_state", "not_checked"),
                       "snapshot": self.state()})

        @Slot()
        def begin_launch(self):
            if self.closing:
                self.launch._on_finished(False, "已取消，应用正在关闭")
                return
            try:
                self.launch.toggle()
            except Exception as exc:
                traceback.print_exc(file=sys.stderr)
                self.launch._on_finished(False, str(exc))

        def check(self, params):
            if params.get("auto") and time.time() - self.config.metadata.get("checkedAt", 0) < 3600:
                return {"throttled": True}
            local = self.versions()["GIMI"]

            def run(worker):
                from omg.core import gimi_update
                release = gimi_update.fetch_latest_release(
                    connect_status_cb=lambda inner, label="": worker.progress.emit(
                        {"message": label or "正在获取远端版本…"}))
                if not release or not release.get("tag_name"):
                    raise ValueError("无法获取更新信息，请检查网络后重试")
                remote = release["tag_name"].lstrip("vV")
                available = gimi_update.compare_versions(local, remote) < 0
                return {"release": release, "available": available, "remote": remote,
                        "message": f"发现新版本 {remote}" if available else "已是最新版本"}
            return self.start_worker("check", run)

        def update(self):
            self.idle_required()
            self.flush_ini()
            settings = copy.deepcopy(self.config.settings)
            gimi = settings["gimi_folder"]
            if not gimi or not Path(gimi).is_dir() or not (Path(gimi) / "d3dx.ini").is_file():
                raise ValueError("请先配置包含 d3dx.ini 的 GIMI 目录")
            if not self.release or self.release_root != gimi:
                raise ValueError("请先检查更新")
            self.game_stopped(settings)
            release = dict(self.release)

            def run(worker):
                from omg.core import download, updates
                import tempfile
                with tempfile.TemporaryDirectory(prefix="update-", dir=root) as work:
                    archive = str(Path(work) / "gimi.zip")
                    ok, message = download.download_file_smart(
                        release["zip_url"], archive, signals=DownloadSink(worker),
                        should_cancel=worker.cancel.is_set)
                    if ok:
                        worker.progress.emit({"message": "部署中；取消将等待回退完成"})
                        ok, message = updates.deploy_gimi_update(
                            archive, gimi, settings["gimi_update_whitelist"],
                            should_cancel=worker.cancel.is_set,
                            progress_cb=lambda p: worker.progress.emit({"progress": .86 + p * .13}))
                    return {"ok": ok, "message": "GIMI 更新完成" if ok else message}
            return self.start_worker("update", run)

        def cache_info(self, clear=False, progress=None):
            from cache_service import CacheService
            return CacheService(root).run(clear=clear, progress=progress)

        def handle(self, method, params):
            if self.closing and method != "shutdown":
                raise ValueError("后端正在收尾")
            if method == "hello":
                if params.get("protocol", 1) != 1:
                    raise ValueError("不兼容的协议版本")
                return {"protocol": 1, "snapshot": self.state()}
            if self.bisect.active:
                if method == "settings.flush":
                    if self.ini_dirty_since is not None:
                        raise ValueError("二分会话中有未同步业务配置，请先恢复再处理")
                    return {"status": "unchanged"}
                mutations = {"resources.toggle", "resources.move", "resources.card", "resources.writeback",
                             "updates.apply"}
                if method in mutations or method.startswith(("links.", "serverSwitch.")) or (method.startswith("build.") and method not in ("build.get", "build.openWorkspace")):
                    raise ValueError("二分排查会话未结束；请先恢复初始状态或结束会话")
                if method in ("config.patch", "config.importLite"):
                    if method == "config.importLite" or any(k not in ("theme", "accent_color") for k in params.get("patch", {})):
                        raise ValueError("二分排查期间不能修改业务设置，请先结束会话")
            if method.startswith("bisect."):
                action = method.split(".", 1)[1]
                if action == "state":
                    self.idle_required()
                    return self.bisect.state()
                if action == "export":
                    self.idle_required()
                    return self.bisect.export()
                if action == "scan":
                    self.flush_ini()
                return self.start_worker(method, lambda worker: {"bisect": self.bisect.dispatch(action, params, worker)})
            if method in ("config.get", "state.get", "versions.detect"):
                return self.state()
            if method in ("config.patch", "config.importLite"):
                patch = params.get("patch", {})
                if self.active or self.launch_state == "injecting":
                    if method == "config.importLite" or any(k not in ("theme", "accent_color") for k in patch):
                        raise ValueError("任务执行期间不能修改业务设置")
                if method == "config.importLite" or "gimi_folder" in patch:
                    self.flush_ini()
                if method == "config.importLite":
                    self.config.import_lite(Path(params["path"]))
                else:
                    gimi_root = Path(patch.get("gimi_folder", self.config.get_gimi_dir()))
                    for entry in patch.get("gimi_update_whitelist", []):
                        (gimi_root / entry).resolve().relative_to(gimi_root.resolve())
                    self.config.commit(patch, revision=params.get("revision"))
                if method == "config.importLite" or any(k in patch for k in ("hunting", "warning", "gimi_folder")):
                    self.schedule_ini()
                if method == "config.importLite" or "gimi_folder" in patch:
                    self.release = None
                    self.release_root = None
                self.emit_event("config.changed", self.state())
                return self.state()
            if method == "settings.flush":
                return self.flush_ini()
            if method.startswith("serverSwitch."):
                from server_switch import ServerSwitchService
                def switch_stopped(settings):
                    self.game_stopped(settings)
                    if is_process_running("launcher.exe") or is_process_running("HYP.exe"):
                        raise ValueError("请先退出原神启动器和米哈游启动器")
                service = ServerSwitchService(root, self.config, switch_stopped)
                action = method.split(".", 1)[1]
                if action == "openDirectory":
                    return service.open_directory()
                if action == "import":
                    from server_import import import_package
                    return self.start_worker(method, lambda worker: import_package(params, service, worker))
                if action == "backupPreview":
                    self.idle_required()
                    from server_backup import preview
                    return preview(params, self.config, service.root)
                if action == "backup":
                    from server_backup import export
                    return self.start_worker(method, lambda worker: export(
                        params, self.config, service.root, switch_stopped, worker))
                if action == "versions":
                    self.idle_required()
                    from server_versions import collect
                    return collect(service)
                if action == "status":
                    return service.status()
                if action == "preview":
                    self.idle_required()
                    return service.preview(params.get("target"))
                if action == "apply":
                    return self.start_worker(method, lambda worker: service.apply(params.get("target"), worker))
                if action == "restore":
                    return self.start_worker(method, lambda worker: service.restore())
                raise ValueError("未知切服操作")
            if method == "build.get":
                return self.builds.state()
            if method == "build.openWorkspace":
                return self.builds.open_workspace()
            if method in ("links.validate", "links.create"):
                self.idle_required()
                from link_service import LinkService
                service = LinkService(self.config)
                return service.create(params) if method == "links.create" else service.validate(params)
            if method == "build.select":
                self.idle_required()
                return self.builds.select(params.get("patch", {}))
            if method.startswith("build."):
                action = method.split(".", 1)[1]
                if action == "cleanup.scan":
                    return self.start_worker(method, lambda worker: {"cleanup": self.builds.cleanup_scan()})
                if action == "cleanup.apply":
                    return self.start_worker(method, lambda worker: self.builds.cleanup(params.get("ids"), worker))
                return self.start_worker(method, lambda worker: self.builds.execute(action, worker, DownloadSink))
            if method == "resources.list":
                return self.start_worker(method, lambda worker: {"resources": self.resources.refresh(params, worker=worker)})
            if method == "resources.folders":
                return {"folders": self.resources.folders(params.get("path", ""))}
            if method == "resources.directory":
                return self.resources.directory_entries(params.get("path", ""))
            if method == "resources.configs":
                return {"files": self.resources.config_files(params)}
            if method == "resources.open":
                return self.resources.open_path(params)
            if method == "resources.openImage":
                return self.resources.open_image(params)
            if method in ("resources.card", "resources.move"):
                action = self.resources.card if method.endswith("card") else self.resources.move
                return self.start_worker(method, lambda worker: {"resources": action(params, worker)})
            if method == "resources.toggle":
                return self.start_worker(method, lambda worker: {"resources": self.resources.toggle(params, worker)})
            if method == "resources.keys":
                return self.start_worker(method, lambda worker: {"resourceKeys": self.resources.keys(params, worker)})
            if method == "resources.writeback":
                return self.start_worker(method, self.resources.writeback)
            if method == "updates.check":
                return self.check(params)
            if method == "updates.apply":
                return self.update()
            if method == "tasks.cancel":
                if not self.worker or params.get("taskId") != self.task_id:
                    raise ValueError("该任务不可取消或已经结束")
                self.worker.cancel.set()
                return {"accepted": True}
            if method == "launch.start":
                self.idle_required()
                if self.launch_state in ("done", "unverified"):
                    raise ValueError("游戏已在运行")
                self.flush_ini()
                self.task_id = uuid.uuid4().hex
                task_id = self.task_id
                self.active = "launch"
                # Queue start so the accepted response precedes launch events.
                QTimer.singleShot(0, self.begin_launch)
                return {"taskId": task_id, "kind": "launch"}
            if method in ("cache.info", "cache.clear"):
                self.idle_required()
                if method == "cache.clear":
                    return self.start_worker(method, lambda worker: self.cache_info(
                        True, worker.progress.emit))
                return self.cache_info()
            if method == "shutdown":
                self.closing = True
                self.launch.request_stop()
                if self.worker:
                    self.worker.cancel.set()
                self.shutdown_timer.start(100)
                return {"accepted": True}
            raise ValueError(f"未知方法：{method}")

        @Slot(object)
        def dispatch(self, request):
            if request is None:
                self.handle("shutdown", {})
                return
            req_id = request.get("id")
            try:
                if request.get("v", 1) != 1:
                    raise ValueError("不兼容的协议版本")
                result = self.handle(request["method"], request.get("params", {}))
                send({"id": req_id, "result": result})
            except Exception as exc:
                traceback.print_exc(file=sys.stderr)
                send({"id": req_id, "error": {"message": str(exc)}})

        @Slot()
        def try_shutdown(self):
            launch_worker = getattr(self.launch, "_worker", None)
            if self.worker or (launch_worker and launch_worker.isRunning()):
                return
            self.flush_ini_event()
            self.launch._stop_exit_watch()
            self.shutdown_timer.stop()
            if self.config.get("cleanup_on_exit", False):
                try:
                    from cache_service import CacheService
                    report = CacheService(root).run(clear=True, keep_latest=True,
                        progress=lambda data: self.emit_event("cache.progress", data))
                    if report["errors"]:
                        print("退出清理未完成：" + "；".join(report["errors"]), file=sys.stderr)
                except (OSError, ValueError) as exc:
                    print(f"退出清理未完成：{exc}", file=sys.stderr)
            self.bisect.close()  # Pending sessions remain journaled; never mutate while a game may be running.
            app.quit()

    app = QCoreApplication([])
    # This is a service, not a last-window/last-job-owned GUI application.
    app.setQuitLockEnabled(False)
    bridge = Bridge()

    def read():
        try:
            for line in sys.stdin:
                if len(line) > 1024 * 1024:
                    raise ValueError("协议行过长")
                try:
                    request = json.loads(line)
                    if not isinstance(request, dict):
                        raise ValueError("请求必须为对象")
                    bridge.incoming.emit(request)
                except ValueError as exc:
                    send({"id": None, "error": {"message": str(exc)}})
        finally:
            bridge.incoming.emit(None)

    threading.Thread(target=read, daemon=True).start()
    try:
        return run_event_loop(app, lambda: bridge.closing)
    finally:
        lock.close()


def main():
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdio", action="store_true")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--lite-src", type=Path)
    parser.add_argument("--injector", action="store_true")
    parser.add_argument("--request-file", type=Path)
    parser.add_argument("--result-file", type=Path)
    args = parser.parse_args()
    if not getattr(sys, "frozen", False):
        args.lite_src = args.lite_src or Path(__file__).resolve().parents[1] / "OMGLite" / "src"
    try:
        if args.injector:
            if not args.request_file or not args.result_file:
                parser.error("注入端需要 --request-file 和 --result-file")
            from injection_entry import run_injector
            return run_injector(args)
        return serve(args)
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
