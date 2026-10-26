"""The standalone source entry must not acquire a dependency on the service."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_backend import BACKEND


class InjectorEntryTests(unittest.TestCase):
    def test_preflight_runs_without_importing_service_or_network_stack(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, result, modules = (root / name for name in ('request.json', 'result.json', 'modules.json'))
            request.write_text(json.dumps({'token': 'thin-entry', 'settings': {}}))
            code = f'''import sys,json,atexit
from pathlib import Path
sys.path.insert(0,{str(BACKEND)!r})
import injector_main
atexit.register(lambda: Path({str(modules)!r}).write_text(json.dumps(sorted(sys.modules))))
raise SystemExit(injector_main.main())
'''
            process = subprocess.run([sys.executable, '-c', code, '--injector', '--data-root', str(root),
                '--request-file', str(request), '--result-file', str(result)], capture_output=True, timeout=20)
            self.assertEqual(process.returncode, 0, process.stderr.decode(errors='replace'))
            output = json.loads(result.read_text(encoding='utf-8'))
            self.assertEqual(output['token'], 'thin-entry')
            self.assertFalse(output['ok'])
            loaded = json.loads(modules.read_text())
            for prefix in ('main', 'build_service', 'resource_browser', 'injection_service',
                           'omg.core.alchemy', 'requests', 'urllib3'):
                self.assertFalse(any(name == prefix or name.startswith(prefix + '.') for name in loaded), prefix)
            self.assertFalse((root / '.backend.lock').exists())

    def test_injector_rejects_service_stdio_entry(self):
        process = subprocess.run([sys.executable, str(BACKEND / 'injector_main.py'), '--stdio'],
            capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 2)
