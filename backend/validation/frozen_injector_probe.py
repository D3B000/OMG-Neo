"""Test-only probe for the minimal frozen injector, including spawn helpers."""
import ctypes
import json
from pathlib import Path
import sys

from backend_runtime import bootstrap
root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=True)
bootstrap(root, None)
from omg.domain.inject.process_tracker import wait_for_process, WaitResult
result, pid = wait_for_process('NeoPackagingFixtureMissing-9A46.exe', timeout=1)
assert result == WaitResult.Timeout and pid == -1, (result, pid)
# The multiprocessing child must have executed freeze_support, not argparse.
library = ctypes.WinDLL(str(Path(sys._MEIPASS) / 'resources/binaries/loader/3dmloader.dll'))
assert callable(library.HookLibrary) and callable(library.UnhookLibrary)
native = ctypes.WinDLL('kernel32', use_last_error=True)
native.FreeLibrary.argtypes = [ctypes.c_void_p]
native.FreeLibrary.restype = ctypes.c_int
assert native.FreeLibrary(library._handle)
library._handle = 0
from types import SimpleNamespace
import threading
from settings_store import DEFAULTS
from omg.domain.launch import controller as launch_controller
from omg.domain.launch.worker import LaunchWorker
game, gimi = root / 'fixture-game', root / 'fixture-gimi'
game.mkdir()
gimi.mkdir()
(game / 'YuanShen.exe').write_bytes(b'fixture only; never executed')
(gimi / 'd3dx.ini').write_text('[Loader]\n')
(gimi / 'd3d11.dll').write_bytes(b'fixture only; never loaded')
settings = {**DEFAULTS, 'game_folder': str(game), 'gimi_folder': str(gimi)}
launch_controller.is_process_running = lambda name: False
controller = launch_controller.LaunchController(SimpleNamespace(get=lambda key, default=None: settings.get(key, default)), verify_injection=False)
ok, message, task = controller._build_task()
assert ok, message
assert task.d3dx_loader == 'omg_injector.exe', task.d3dx_loader
request, result_file = root / 'request.json', root / 'result.json'
request.write_text(json.dumps({'token': 'minimal-worker', 'settings': settings}))
def fake_run(self):
    assert not self._verify_injection
    assert threading.current_thread() is not threading.main_thread()
    self.verification_state = 'skipped'
    self.finished.emit(True, 'fixture worker completed')
    (root / 'worker-cleanup').write_text('done')
LaunchWorker.run = fake_run
from injection_entry import run_injector
code = run_injector(SimpleNamespace(data_root=root, lite_src=None, request_file=request, result_file=result_file))
assert code == 0
completed = json.loads(result_file.read_text(encoding='utf-8'))
assert completed['ok'] and completed['token'] == 'minimal-worker'
assert (root / 'worker-cleanup').exists()
for prefix in ('main', 'build_service', 'resource_browser', 'injection_service', 'requests', 'urllib3'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules), prefix
(root / 'injector-probe.json').write_text(json.dumps({
    'frozen': bool(sys.frozen), 'processWaiterSpawn': 'passed',
    'nativeLoaderLoadUnload': 'passed', 'serviceModulesImported': False,
    'workerThreadCompletion': 'passed', 'loaderIdentity': task.d3dx_loader,
    'executable': str(Path(sys.executable).name)
}, indent=2), encoding='utf-8')
