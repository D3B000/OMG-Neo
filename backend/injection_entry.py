"""One launch per process. Results use an atomic file, independent of DLL stdio."""
from __future__ import annotations

import json
import os
from pathlib import Path
import traceback
from types import SimpleNamespace


def run_injector(args):
    from backend_runtime import bootstrap
    from settings_store import validate, DEFAULTS
    from PySide6.QtCore import QCoreApplication, QTimer
    # This entry does not acquire the service lock or read its protocol pipe.
    root = args.data_root.resolve()
    bootstrap(root, args.lite_src)
    from omg.domain.launch.controller import LaunchController
    from omg.domain.launch.worker import LaunchWorker
    data = json.loads(args.request_file.read_text(encoding="utf-8"))
    token = data["token"]
    settings = {**DEFAULTS, **validate(data["settings"])}
    app = QCoreApplication([])
    app.setQuitLockEnabled(False)
    config = SimpleNamespace(get=lambda key, default=None: settings.get(key, default))
    controller = LaunchController(config, verify_injection=False)
    output = {"token": token, "ok": False, "message": "注入端未完成", "verification": "not_checked"}
    worker = None
    result_received = False

    def save_result():
        args.result_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.result_file.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(output, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, args.result_file)

    def completed(ok, message):
        nonlocal result_received
        output.update(ok=bool(ok), message=message, verification=worker.verification_state)
        result_received = True

    def thread_stopped():
        # Write the result only after native cleanup and the QThread finish.
        save_result()
        app.quit()

    try:
        ok, message, task = controller._build_task()
        if not ok:
            output["message"] = message
            save_result()
            return 0
        output["target"] = task.d3dx_target
        worker = LaunchWorker(task, verify_injection=False)
        worker.finished.connect(completed)
        # LaunchWorker.finished(bool,str) shadows QThread.finished(). Polling
        # isRunning avoids quitting while its native thread is still unwinding.
        timer = QTimer()
        timer.setInterval(20)
        timer.timeout.connect(lambda: thread_stopped()
            if result_received and not worker.isRunning() else None)
        worker.start()
        timer.start()
        code = app.exec()
        if worker.isRunning():
            worker.wait()
            app.processEvents()
        if not args.result_file.exists():
            save_result()
        return code
    except Exception as exc:
        traceback.print_exc()
        output["message"] = f"注入端错误：{exc}"
        save_result()
        return 1
