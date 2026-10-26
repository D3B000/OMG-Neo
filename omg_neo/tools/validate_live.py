"""Opt-in real-machine validation through the shipped stdio backend.

Writes evidence and a pre-update backup to the explicitly selected report root.
Never mocks network, injector, or backend. Does not stop the game after launch.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import stat
import subprocess
import sys
import threading
import time

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP.parent / "backend"))
from settings_store import SettingsStore


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def files(root):
    for base, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (
            (Path(base) / d).lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)]
        for name in names:
            path = Path(base) / name
            if not path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                yield path


def manifest(root, *, skip_mods=True):
    result = {}
    for path in files(root):
        relative = path.relative_to(root).as_posix()
        if skip_mods and relative.casefold().startswith("mods/"):
            continue
        result[relative] = {"size": path.stat().st_size, "sha256": digest(path)}
    return result


class Backend:
    def __init__(self, report, config_root):
        self.report = report
        self.records = []
        self.messages = queue.Queue()
        self.events = []
        self.next_id = 0
        self.stderr = (report / "backend-stderr.log").open("w", encoding="utf-8")
        executable = APP / "dist/OMG-Neo-home-settings/backend/omg_backend.exe"
        self.process = subprocess.Popen(
            [str(executable), "--stdio", "--data-root", str(config_root)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr,
            encoding="utf-8", cwd=APP)
        def read():
            with (report / "raw-stdout.log").open("w", encoding="utf-8") as raw:
                for line in self.process.stdout:
                    raw.write(line)
                    raw.flush()
                    try:
                        message = json.loads(line)
                    except ValueError:
                        message = {"event": "protocol.invalid", "data": {"line": line}}
                    self.records.append(message)
                    self.messages.put(message)
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()

    def next_message(self, timeout=30):
        return self.messages.get(timeout=timeout)

    def call(self, method, **params):
        self.next_id += 1
        req_id = str(self.next_id)
        self.process.stdin.write(json.dumps({"v": 1, "id": req_id, "method": method, "params": params}) + "\n")
        self.process.stdin.flush()
        while True:
            message = self.next_message()
            if "event" in message:
                self.events.append(message)
            elif message.get("id") == req_id:
                if "error" in message:
                    raise RuntimeError(message["error"]["message"])
                return message["result"]

    def wait(self, task, timeout=600):
        start = time.monotonic()
        last = 0
        while time.monotonic() - start < timeout:
            for message in self.events:
                if message.get("event") == "task.finished" and message["data"]["taskId"] == task:
                    return message["data"]
            try:
                message = self.next_message(timeout=1)
                self.events.append(message)
                if message.get("event") == "task.progress" and time.monotonic() - last > 5:
                    print(json.dumps(message["data"], ensure_ascii=False), flush=True)
                    last = time.monotonic()
            except queue.Empty:
                if self.process.poll() is not None:
                    raise RuntimeError(f"backend exited: {self.process.returncode}")
        raise TimeoutError(f"task did not finish within {timeout}s")

    def close(self):
        if self.process.poll() is None:
            self.call("shutdown")
            self.process.stdin.close()
            self.process.wait(timeout=180)
        self.reader.join(timeout=2)
        self.stderr.close()
        (self.report / "protocol.json").write_text(
            json.dumps(self.records, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["check", "update", "launch"])
    parser.add_argument("--gimi", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--game", type=Path)
    parser.add_argument("--custom-command")
    args = parser.parse_args()
    args.report = args.report.resolve()
    args.report.mkdir(parents=True, exist_ok=True)
    config = SettingsStore(args.report / "data")
    legacy = APP.parents[1] / "OMGLite/config.json"
    config.import_lite(legacy)
    patch = {"gimi_folder": str(args.gimi.resolve()), "auto_check_update": False}
    # Protect the user's large mod library during live update verification.
    whitelist = list(config.get("gimi_update_whitelist"))
    if "mods/" not in [x.casefold() for x in whitelist]:
        whitelist.append("Mods/")
    patch["gimi_update_whitelist"] = whitelist
    if args.game:
        patch["game_folder"] = str(args.game.resolve())
    if args.custom_command is not None:
        patch["custom_launch_enabled"] = bool(args.custom_command)
        patch["custom_launch_cmd"] = args.custom_command
    config.commit(patch)
    before = manifest(args.gimi)
    (args.report / "before.json").write_text(json.dumps(before, indent=2), encoding="utf-8")
    if args.mode == "update":
        backup = args.report / "backup"
        if backup.exists():
            raise RuntimeError("Use a new report directory; backup must not be overwritten")
        for relative in before:
            destination = backup / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(args.gimi / relative, destination)
        print(f"Backed up {len(before)} non-Mods files", flush=True)
    client = Backend(args.report, args.report / "data")
    result = {}
    try:
        snapshot = client.call("hello", protocol=1)["snapshot"]
        print("Before versions: " + json.dumps(snapshot["versions"], ensure_ascii=False), flush=True)
        if args.mode in ("check", "update"):
            task = client.call("updates.check")["taskId"]
            result["check"] = client.wait(task)
            print("Check: " + json.dumps(result["check"], ensure_ascii=False), flush=True)
            if args.mode == "update" and result["check"]["state"] == "succeeded":
                task = client.call("updates.apply")["taskId"]
                result["update"] = client.wait(task)
                print("Update: " + json.dumps(result["update"], ensure_ascii=False), flush=True)
        else:
            task = client.call("launch.start")["taskId"]
            result["launch"] = client.wait(task, timeout=180)
            print("Launch: " + json.dumps(result["launch"], ensure_ascii=False), flush=True)
            if result["launch"]["state"] == "succeeded":
                time.sleep(10)
                result["after10seconds"] = client.call("state.get")
        result["after"] = client.call("state.get")
    except Exception as exc:
        result["error"] = str(exc)
        raise
    finally:
        client.close()
        after = manifest(args.gimi)
        (args.report / "after.json").write_text(json.dumps(after, indent=2), encoding="utf-8")
        result["changed"] = [p for p in before.keys() | after.keys() if before.get(p) != after.get(p)]
        (args.report / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Report: " + str(args.report), flush=True)


if __name__ == "__main__":
    main()
