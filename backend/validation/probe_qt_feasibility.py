"""Read-only feasibility probe; never starts a game, build, or injection hook."""
import argparse
import importlib
import importlib.abc
import json
import logging
from pathlib import Path
import subprocess
import sys
import tempfile

BACKEND = Path(__file__).resolve().parents[1]
LITE = BACKEND.parent / 'OMGLite/src'
TARGETS = ['settings_store', 'resource_browser', 'link_service', 'server_backup',
    'server_switch', 'server_versions', 'omg.core.download', 'omg.core.updates',
    'omg.domain.inject.loader', 'omg.domain.inject.launcher',
    'omg.domain.inject.process_tracker', 'omg.core.build_env',
    'omg.core.alchemy', 'omg.core.gimi_update',
    'omg.domain.launch.controller', 'omg.domain.launch.worker', 'native_ritual']


def child(target):
    original_stdout, original_stderr = sys.stdout, sys.stderr
    sys.path[:0] = [str(BACKEND), str(LITE)]
    class WithoutQt(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split('.')[0] in ('PySide6', 'shiboken6'):
                raise ModuleNotFoundError(f'Qt intentionally blocked: {fullname}')
    sys.meta_path.insert(0, WithoutQt())
    result = {'target': target}
    with tempfile.TemporaryDirectory(prefix='neo-qt-analysis-') as temporary:
        from backend_runtime import bootstrap
        bootstrap(Path(temporary), LITE)
        try:
            if target == 'native_ritual':
                from omg.core import ritual_loader
                ritual_loader.RITUAL_BUNDLE_PYD = str(BACKEND / 'vendor/ritual/ritual_bundle.pyd')
                ritual_loader.CYTHON_ANALYSIS_PYD = str(BACKEND / 'vendor/ritual/_cython_analysis.pyd')
                library = ritual_loader.load_ritual_bundle()
                assert library is not None
                options = library.TransformOptions(seed=9876, allow_invalid_signature=True)
                import _ctypes
                pe, report, approved = library.analyze_internal(Path(_ctypes.__file__).read_bytes(), options)
                result['nativePEAnalysis'] = pe is not None
                result['nativeBuildExport'] = callable(library.run_build)
            else:
                importlib.import_module(target)
            result['qtFreeImport'] = True
        except Exception as exc:
            result.update(qtFreeImport=False, exception=type(exc).__name__, message=str(exc))
        result['qtPythonModules'] = [m for m in sys.modules if m.split('.')[0] in ('PySide6', 'shiboken6')]
        import ctypes
        native = ctypes.WinDLL('kernel32')
        native.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        native.GetModuleHandleW.restype = ctypes.c_void_p
        result['qtCoreDllLoaded'] = native.GetModuleHandleW('Qt6Core.dll') is not None
        sys.stdout.flush()
        sys.stderr.flush()
        sys.stdout, sys.stderr = original_stdout, original_stderr
        logging.shutdown()
    print('QT_FEASIBILITY=' + json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--child')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.child:
        child(args.child)
    else:
        report = []
        for target in TARGETS:
            run = subprocess.run([sys.executable, str(Path(__file__)), '--child', target],
                capture_output=True, encoding='utf-8', errors='replace', timeout=40)
            lines = [line for line in run.stdout.splitlines() if line.startswith('QT_FEASIBILITY=')]
            if run.returncode or not lines:
                report.append({'target': target, 'probeFailed': True, 'error': run.stderr[-1500:]})
            else:
                report.append(json.loads(lines[-1].split('=', 1)[1]))
        if args.output:
            args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))
