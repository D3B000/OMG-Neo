"""Startup stays independent of optional tools; large hashes use bounded memory."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tracemalloc
import unittest

from test_backend import BACKEND
from file_io import sha256_file


class MemoryTests(unittest.TestCase):
    def test_home_and_settings_do_not_load_optional_toolchains(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            modules = root / 'loaded.json'
            code = f'''import sys,json,atexit
sys.path.insert(0,{str(BACKEND)!r})
import main
atexit.register(lambda: __import__('pathlib').Path({str(modules)!r}).write_text(json.dumps(sorted(sys.modules))))
raise SystemExit(main.main())
'''
            requests = [{'v': 1, 'id': str(i), 'method': method, 'params': params}
                for i, (method, params) in enumerate([
                    ('hello', {}), ('cache.info', {}),
                    ('config.patch', {'patch': {'theme': 'dark'}}),
                    ('settings.flush', {}), ('shutdown', {})])]
            result = subprocess.run([sys.executable, '-c', code, '--stdio', '--data-root', str(root)],
                input=''.join(json.dumps(r) + '\n' for r in requests), capture_output=True,
                encoding='utf-8', errors='replace', timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            replies = {r['id']: r for line in result.stdout.splitlines() if (r := json.loads(line)).get('id') is not None}
            self.assertTrue(all('result' in replies[str(i)] for i in range(len(requests))))
            loaded = json.loads(modules.read_text())
            for name in ('build_service', 'resource_browser', 'omg.core.alchemy', 'omg.core.gimi_update',
                         'omg.core.download', 'ritual_bundle', '_cython_analysis'):
                self.assertNotIn(name, loaded)
            self.assertFalse((root / 'build-work').exists())

    def test_large_file_hash_has_bounded_python_allocation(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'large.dll'
            with path.open('wb') as stream:
                stream.truncate(32 * 1024 * 1024)
            expected = hashlib.sha256()
            for _ in range(32):
                expected.update(bytes(1024 * 1024))
            tracemalloc.start()
            try:
                self.assertEqual(sha256_file(path), expected.hexdigest())
                _, peak = tracemalloc.get_traced_memory()
                self.assertLess(peak, 1024 * 1024)
            finally:
                tracemalloc.stop()
