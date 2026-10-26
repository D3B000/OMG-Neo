"""Real stdio integration against temporary GIMI copies; no game or internet."""
import io
import functools
import http.server
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from settings_store import SettingsStore


class Client:
    def __init__(self, root, fixture=None):
        frozen = os.environ.get("OMGNEO_FROZEN_BACKEND")
        command = [frozen] if frozen else [sys.executable, "-u", str(BACKEND / "main.py")]
        if fixture:
            # Inject a local release fixture in the test process only.
            code = (
                "import sys,json;from pathlib import Path;"
                f"sys.path.insert(0,{str(BACKEND)!r});import main;"
                "out=sys.stdout;"
                f"exec('if {bool(fixture.get('_quitEventLoop'))}:\\n from PySide6.QtCore import QTimer\\n original_loop=main.run_event_loop\\n main.run_event_loop=lambda app,closing: (QTimer.singleShot(50,app.quit), original_loop(app,closing))[1]');"
                f"main.bootstrap(Path({str(root)!r}),Path({str(BACKEND.parent / 'OMGLite' / 'src')!r}));"
                f"exec('if {bool(fixture.get('_verificationFailure'))}:\\n from PySide6.QtCore import QTimer,QCoreApplication\\n from types import SimpleNamespace\\n from injection_service import IsolatedLaunchController as LaunchController\\n def failed_launch(self):\\n  self._worker=SimpleNamespace(verification_state=\"failed\",isRunning=lambda:False)\\n  self._on_finished(False,\"fixture verification failed\")\\n  QTimer.singleShot(0,QCoreApplication.quit)\\n LaunchController.toggle=failed_launch');"
                "from omg.core import gimi_update;sys.stdout=out;"
                f"release=json.loads({json.dumps(fixture)!r});"
                "import time,os;from omg.domain.inject import process_tracker;"
                "process_tracker.is_process_running=lambda name: release.get('_gameRunning',False);"
                "exec('if release.get(\"_injectorCommand\"):\\n import injection_service\\n injection_service.injector_command=lambda root: release[\"_injectorCommand\"]');"
                "import ctypes,ctypes.wintypes as wt;native=ctypes.WinDLL('kernel32');"
                "native.GetStdHandle.argtypes=[wt.DWORD];native.GetStdHandle.restype=wt.HANDLE;"
                "native.WriteFile.argtypes=[wt.HANDLE,ctypes.c_void_p,wt.DWORD,ctypes.POINTER(wt.DWORD),ctypes.c_void_p];"
                "buffer=ctypes.create_string_buffer(b'NATIVE_WIN32_OUTPUT\\n');written=wt.DWORD();"
                "gimi_update.fetch_latest_release=lambda **kwargs: (os.write(1,b'NATIVE_FD_OUTPUT\\n'),native.WriteFile(native.GetStdHandle(wt.DWORD(-11)),buffer,len(buffer.value),ctypes.byref(written),None),time.sleep(release.get('_delay',0)),release)[-1];"
                "exec('if \"_buildReleases\" in release:\\n from omg.core import alchemy\\n alchemy.fetch_releases=lambda **kwargs: release[\"_buildReleases\"]');"
                "exec('if release.get(\"_failBuild\"):\\n from omg.core import alchemy\\n from types import SimpleNamespace\\n alchemy.run_env_check=lambda *args,**kwargs: SimpleNamespace(ready=True,to_tip_text=lambda *args: \"ready\")\\n alchemy.build_project=lambda *args,**kwargs: (False,\"fixture compile failure\")\\n alchemy.run_ritual=lambda *args,**kwargs: Path(\"ritual-should-not-run\").write_text(\"unexpected\")');"
                "raise SystemExit(main.main())"
            )
            command = [sys.executable, "-u", "-c", code]
        self.process = subprocess.Popen(command + ["--stdio", "--data-root", str(root)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, encoding="utf-8", errors="replace")
        self.messages = queue.Queue()
        self.events = []
        self.errors = []
        self.counter = 0
        def read():
            for line in self.process.stdout:
                self.messages.put(json.loads(line))
        def err():
            self.errors.extend(self.process.stderr)
        threading.Thread(target=read, daemon=True).start()
        threading.Thread(target=err, daemon=True).start()

    def call(self, method, **params):
        self.counter += 1
        request_id = str(self.counter)
        self.process.stdin.write(json.dumps({"v": 1, "id": request_id,
                                            "method": method, "params": params}) + "\n")
        self.process.stdin.flush()
        while True:
            message = self.messages.get(timeout=10)
            if "event" in message:
                self.events.append(message)
            elif message.get("id") == request_id:
                return message

    def finished(self, task_id):
        while True:
            for event in self.events:
                if event["event"] == "task.finished" and event["data"]["taskId"] == task_id:
                    return event["data"]
            self.events.append(self.messages.get(timeout=10))

    def close(self):
        if self.process.poll() is None:
            self.call("shutdown")
            self.process.stdin.close()
            self.process.wait(timeout=10)
        for stream in (self.process.stdout, self.process.stderr):
            stream.close()


class StoreTests(unittest.TestCase):
    def test_atomic_failure_keeps_original_and_in_memory_state(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SettingsStore(Path(temp))
            store.commit({"theme": "dark"})
            original = store.path.read_bytes()
            with patch("settings_store.os.replace", side_effect=PermissionError("locked")):
                with self.assertRaises(PermissionError):
                    store.commit({"theme": "light"})
            self.assertEqual(store.path.read_bytes(), original)
            self.assertEqual(store.get("theme"), "dark")
            self.assertEqual(store.revision, 1)

    def test_backup_recovery_and_legacy_import_without_source_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = SettingsStore(root)
            store.commit({"theme": "dark"})
            store.commit({"theme": "light"})
            store.path.write_text("broken", encoding="utf-8")
            recovered = SettingsStore(root)
            self.assertTrue(recovered.recovered)
            self.assertEqual(recovered.get("theme"), "dark")
            legacy = root / "lite.json"
            legacy.write_text(json.dumps({"hunting": "1", "auto_check_update": 1,
                                          "gimi_update_whitelist": ["Mods/"]}), encoding="utf-8")
            before = legacy.read_bytes()
            recovered.import_lite(legacy)
            self.assertEqual(legacy.read_bytes(), before)
            self.assertEqual(recovered.get("hunting"), 1)
            self.assertEqual(recovered.get("gimi_update_whitelist"), ["Mods/"])


class ProtocolTests(unittest.TestCase):
    def test_failed_verification_does_not_exit_or_disable_resource_service(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gimi = root / "GIMI"
            (gimi / "Mods").mkdir(parents=True)
            client = Client(root / "data", {"_verificationFailure": True})
            try:
                client.call("config.patch", patch={"gimi_folder": str(gimi)})
                task = client.call("launch.start")["result"]["taskId"]
                finished = client.finished(task)
                self.assertEqual(finished["state"], "failed")
                self.assertEqual(finished["verification"], "failed")
                self.assertIsNone(client.process.poll())
                task = client.call("resources.list", path="")["result"]["taskId"]
                self.assertEqual(client.finished(task)["state"], "succeeded")
                self.assertIsNone(client.process.poll())
            finally:
                client.close()

    def test_unrequested_qt_quit_keeps_resource_service_alive(self):
        import time
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gimi = root / "GIMI"
            mod = gimi / "Mods" / "Outfit"
            mod.mkdir(parents=True)
            (mod / "outfit.ini").write_text("[KeyOutfit]\nkey=X\n")
            client = Client(root / "data", {"_quitEventLoop": True})
            try:
                client.call("hello")
                time.sleep(.15)
                self.assertIsNone(client.process.poll())
                self.assertIn("result", client.call("hello"))
                self.assertIn("result", client.call("config.patch", patch={"gimi_folder": str(gimi)}))
                task = client.call("resources.list", path="")["result"]["taskId"]
                self.assertEqual(client.finished(task)["state"], "succeeded")
                self.assertTrue(any("without a shutdown request" in line for line in client.errors))
            finally:
                client.close()

    def test_check_cancel_and_eof_shutdown(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            client = Client(root, {"tag_name": "v9.2.0", "zip_url": "unused", "_delay": .3})
            try:
                client.call("hello")
                task = client.call("updates.check")["result"]["taskId"]
                self.assertTrue(client.call("tasks.cancel", taskId=task)["result"]["accepted"])
                self.assertEqual(client.finished(task)["state"], "cancelled")
                self.assertFalse((root / "config.json").exists())
                client.process.stdin.close()
                self.assertEqual(client.process.wait(timeout=10), 0)
            finally:
                client.close()

    def test_settings_versions_ini_revision_preflight_and_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gimi = root / "GIMI"
            (gimi / "Core/GIMI/Libraries/TexFx").mkdir(parents=True)
            (gimi / "Core/GIMI/main.ini").write_text("global $version = 9.10\n", encoding="utf-8")
            (gimi / "Core/GIMI/Libraries/ORFix.ini").write_text("; Version 2.0\n", encoding="utf-8")
            (gimi / "Core/GIMI/Libraries/TexFx/Main.ini").write_text("global $version = 3.0\n", encoding="utf-8")
            ini = gimi / "d3dx.ini"
            ini.write_text('[Loader]\nlaunch = "custom launcher.exe"\n[Hunting]\nhunting = 0\n[Logging]\nshow_warnings = 0\n', encoding="utf-8")
            client = Client(root / "data")
            try:
                self.assertEqual(client.call("hello")["result"]["protocol"], 1)
                result = client.call("config.patch", revision=0, patch={"gimi_folder": str(gimi),
                    "hunting": 1, "warning": 1, "accent_color": "#112233"})["result"]
                self.assertEqual(result["versions"], {"GIMI": "9.1.0", "ORFix": "2.0", "TexFx": "3.0"})
                self.assertIn("error", client.call("config.patch", revision=0, patch={"theme": "dark"}))
                self.assertIn("error", client.call("config.patch", patch={"gimi_update_whitelist": ["../escape/"]}))
                self.assertEqual(client.call("settings.flush")["result"]["status"], "written")
                text = ini.read_text(encoding="utf-8")
                self.assertIn('launch = "custom launcher.exe"', text)
                self.assertIn("hunting = 1", text)
                self.assertIn("show_warnings = 1", text)
                task = client.call("launch.start")["result"]["taskId"]
                finished = client.finished(task)
                self.assertEqual(finished["state"], "failed")
                self.assertIn("游戏目录", finished["message"])
                cache = root / "data/cache"
                cache.mkdir()
                (cache / "sample").write_bytes(b"123")
                self.assertEqual(client.call("cache.info")["result"]["bytes"], 3)
                task = client.call("cache.clear")["result"]["taskId"]
                self.assertEqual(client.finished(task)["result"]["bytes"], 0)
                self.assertTrue(ini.exists())
            finally:
                client.close()
            client = Client(root / "data")
            try:
                settings = client.call("config.get")["result"]["settings"]
                self.assertEqual(settings["gimi_folder"], str(gimi))
                self.assertEqual(settings["accent_color"], "#112233")
            finally:
                client.close()

    def test_update_local_archive_preserves_whitelist(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gimi = root / "GIMI"
            (gimi / "Mods").mkdir(parents=True)
            (gimi / "Mods/custom.ini").write_text("local", encoding="utf-8")
            (gimi / "d3dx.ini").write_text("[Hunting]\nhunting = 2\n", encoding="utf-8")
            archive = root / "release.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("Core/GIMI/main.ini", "global $version = 9.20\n")
                zf.writestr("Mods/custom.ini", "remote")
                zf.writestr("Mods/new.ini", "remote")
            class Handler(http.server.SimpleHTTPRequestHandler):
                def log_message(self, *args):
                    pass
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                functools.partial(Handler, directory=str(root)))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            url = f"http://127.0.0.1:{server.server_port}/release.zip"
            client = Client(root / "data", {"tag_name": "v9.2.0", "zip_url": url})
            try:
                client.call("hello")
                client.call("config.patch", patch={"gimi_folder": str(gimi),
                    "game_folder": str(root / "missing-game"), "gimi_update_whitelist": ["Mods/"]})
                task = client.call("updates.check")["result"]["taskId"]
                check = client.finished(task)
                self.assertEqual(check["state"], "succeeded", check)
                self.assertTrue(check["result"]["available"])
                task = client.call("updates.apply")["result"]["taskId"]
                finished = client.finished(task)
                self.assertEqual(finished["state"], "succeeded", finished)
                self.assertEqual((gimi / "Mods/custom.ini").read_text(), "local")
                self.assertFalse((gimi / "Mods/new.ini").exists())
                self.assertEqual(finished["snapshot"]["versions"]["GIMI"], "9.2.0")
            finally:
                client.close()
                server.shutdown()
                server.server_close()
            self.assertIn("NATIVE_FD_OUTPUT", "".join(client.errors))
            self.assertIn("NATIVE_WIN32_OUTPUT", "".join(client.errors))


class InjectionFeedbackTests(unittest.TestCase):
    def test_unchecked_hook_never_calls_verification_and_still_cleans_up(self):
        from unittest.mock import MagicMock
        sys.path.insert(0, str(BACKEND.parent / "OMGLite/src"))
        from omg.domain.inject.launcher import MigotoInjector, StartRequest
        request = StartRequest("fixture.exe", Path("fixture.exe"), Path("d3d11.dll"))
        native = MagicMock()
        native.wait_for_injection.side_effect = AssertionError("verification must not run")
        with patch("omg.domain.inject.launcher.DllInjector", return_value=native), \
             patch.object(MigotoInjector, "wait_for_window") as window:
            MigotoInjector(request, Path("3dmloader.dll")).run(verify_injection=False)
        native.hook_library.assert_called_once()
        native.open_process.assert_called_once()
        native.wait_for_injection.assert_not_called()
        native.last_check_verified_by_probe.assert_not_called()
        native.last_check_inconclusive.assert_not_called()
        native.unhook_library.assert_called_once()
        native.unload.assert_called_once()
        self.assertFalse(window.call_args.kwargs["injection_verified"])

    def test_unchecked_worker_executes_in_its_own_thread(self):
        import threading
        from types import SimpleNamespace
        from unittest.mock import Mock
        sys.path.insert(0, str(BACKEND.parent / "OMGLite/src"))
        from omg.domain.launch.worker import LaunchWorker
        from omg.domain.launch.types import LaunchTask
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication.instance() or QCoreApplication([])
        main_thread = threading.get_ident()
        ran_on = []
        engine = SimpleNamespace(run=Mock(side_effect=lambda **kw: ran_on.append(threading.get_ident())))
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "d3dx.ini").write_text("[Loader]\n", encoding="utf-8")
            task = LaunchTask(temp, "fixture.exe", 0, 0, None, "backend.exe", "unused.dll",
                              SimpleNamespace(use_hook=True, use_xxmi_dll=True))
            worker = LaunchWorker(task, verify_injection=False)
            emitted = []
            worker.finished.connect(lambda ok, message: emitted.append((ok, message)))
            with patch("omg.domain.launch.worker.MigotoInjector", return_value=engine), \
                 patch("omg.domain.launch.worker.patch_d3dx_ini", return_value=False):
                worker.start()
                self.assertTrue(worker.wait(3000))
                app.processEvents()
            self.assertEqual(len(ran_on), 1)
            self.assertNotEqual(ran_on[0], main_thread)
            engine.run.assert_called_once_with(verify_injection=False)
            self.assertEqual(worker.verification_state, "skipped")
            self.assertTrue(emitted[0][0])
            self.assertNotIn("注入完成", emitted[0][1])

    def test_worker_does_not_claim_injection_for_inaccessible_or_missing_module(self):
        sys.path.insert(0, str(BACKEND.parent / "OMGLite/src"))
        from main import bootstrap
        runtime_root = BACKEND / "tests/.runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)
        bootstrap(runtime_root, BACKEND.parent / "OMGLite/src")
        from types import SimpleNamespace
        from omg.domain.launch.worker import LaunchWorker
        from omg.domain.launch.types import LaunchTask
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication.instance() or QCoreApplication([])
        for native, probed, inconclusive, ok, verification in [
            (True, False, False, True, "verified"),
            (False, True, False, True, "verified"),
            (False, False, True, True, "inconclusive"),
            (False, False, False, False, "failed"),
        ]:
            with self.subTest(verification=verification, native=native), tempfile.TemporaryDirectory() as temp:
                (Path(temp) / "d3dx.ini").write_text("[Loader]\n", encoding="utf-8")
                request = SimpleNamespace(use_hook=True, use_xxmi_dll=True)
                task = LaunchTask(temp, "game.exe", 0, 0, None, "backend.exe", "unused.dll", request)
                engine = SimpleNamespace(last_check={"native": native},
                    last_check_verified_by_probe=lambda: probed,
                    last_check_inconclusive=lambda: inconclusive,
                    describe_last_check=lambda: "test evidence")
                fake = SimpleNamespace(injector=engine, run=lambda: None)
                worker = LaunchWorker(task)
                emitted = []
                worker.finished.connect(lambda success, message: emitted.append((success, message)))
                with patch("omg.domain.launch.worker.MigotoInjector", return_value=fake), \
                     patch("omg.domain.launch.worker.patch_d3dx_ini", return_value=False):
                    worker.run()
                self.assertEqual(emitted[0][0], ok)
                self.assertEqual(worker.verification_state, verification)
                if verification != "verified":
                    self.assertNotIn("注入完成", emitted[0][1])

    def test_module_snapshot_preserves_access_denied(self):
        import ctypes
        from unittest.mock import MagicMock
        sys.path.insert(0, str(BACKEND.parent / "OMGLite/src"))
        from omg.domain.inject import injection_probe
        kernel = MagicMock()
        kernel.CreateToolhelp32Snapshot.return_value = 12
        kernel.Module32FirstW.side_effect = lambda *args: ctypes.set_last_error(5) or False
        with patch.object(injection_probe, "_kernel32", return_value=kernel), \
             patch.object(injection_probe, "pids_for_name", return_value=[123]):
            result = injection_probe.find_loaded_module("game.exe", "C:/GIMI/d3d11.dll")
        self.assertFalse(result.found)
        self.assertTrue(result.inconclusive)
        self.assertEqual(result.last_error, 5)


if __name__ == "__main__":
    unittest.main()
