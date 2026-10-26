"""Disposable child failures never take down the service. No game/DLL is run."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from test_backend import Client, BACKEND


FAKE_CHILD = '''import argparse,json,os,time
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--request-file',type=Path)
p.add_argument('--result-file',type=Path)
p.add_argument('--behavior')
a=p.parse_args()
d=json.loads(a.request_file.read_text())
time.sleep(.5 if a.behavior != 'hang' else 30)
if a.behavior in ('0','7'): os._exit(int(a.behavior))
r={'token':d['token'],'ok':True,'message':'fixture done','verification':'skipped','target':'fixture-game.exe'}
if a.behavior == 'bad-token': r['token']='wrong'
a.result_file.write_text(json.dumps(r))
'''


class IsolationTests(unittest.TestCase):
    def test_real_service_spawns_injector_only_on_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game, gimi = root / 'empty-game', root / 'GIMI'
            game.mkdir()
            gimi.mkdir()
            (gimi / 'd3dx.ini').write_text('[Loader]\n')
            (gimi / 'd3d11.dll').write_bytes(b'not loaded: no game executable')
            data = root / 'data'
            client = Client(data)
            try:
                client.call('hello')
                client.call('config.patch', patch={'game_folder': str(game), 'gimi_folder': str(gimi)})
                client.call('cache.info')
                self.assertFalse((data / 'log' / 'injection-lifecycle.jsonl').exists())
                task = client.call('launch.start')['result']['taskId']
                result = client.finished(task)
                self.assertEqual(result['state'], 'failed')
                self.assertIn('result', client.call('hello'))
                records = [json.loads(line) for line in (data / 'log' / 'injection-lifecycle.jsonl').read_text().splitlines()]
                self.assertEqual([r['event'] for r in records], ['started', 'exited'])
                self.assertTrue(records[-1]['result_received'])
                self.assertEqual(records[-1]['exit_code'], 0)
                self.assertNotEqual(records[0]['injector_pid'], client.process.pid)
            finally:
                client.close()

    def exercise_child(self, behavior):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / 'child.py'
            script.write_text(FAKE_CHILD)
            game, gimi = root / 'game', root / 'GIMI'
            game.mkdir()
            (gimi / 'Mods').mkdir(parents=True)
            (gimi / 'd3dx.ini').write_text('[Loader]\n')
            (gimi / 'd3d11.dll').write_bytes(b'fixture, never loaded')
            data = root / 'data'
            client = Client(data, {'_injectorCommand': [sys.executable, str(script), '--behavior', behavior]})
            try:
                client.call('hello')
                client.call('config.patch', patch={'game_folder': str(game), 'gimi_folder': str(gimi)})
                client.call('cache.info')
                resources = client.call('resources.list', path='')['result']['taskId']
                self.assertEqual(client.finished(resources)['state'], 'succeeded')
                self.assertFalse((data / 'log' / 'injection-lifecycle.jsonl').exists())
                task = client.call('launch.start')['result']['taskId']
                start = time.monotonic()
                self.assertIn('result', client.call('hello'))
                self.assertLess(time.monotonic() - start, .4)
                if behavior == 'hang':
                    deadline = time.monotonic() + 5
                    while not (data / 'log' / 'injection-lifecycle.jsonl').exists():
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(.02)
                    start = time.monotonic()
                    client.close()
                    self.assertLess(time.monotonic() - start, 3)
                    self.assertEqual(client.process.returncode, 0)
                    return
                result = client.finished(task)
                self.assertEqual(result['state'], 'succeeded' if behavior == 'success' else 'failed')
                if behavior == '0':
                    self.assertIn('（0）', result['message'])
                self.assertIsNone(client.process.poll())
                self.assertIn('result', client.call('hello'))
                resources = client.call('resources.list', path='')['result']['taskId']
                self.assertEqual(client.finished(resources)['state'], 'succeeded')
                records = [json.loads(line) for line in (data / 'log' / 'injection-lifecycle.jsonl').read_text().splitlines()]
                self.assertEqual([r['event'] for r in records], ['started', 'exited'])
                self.assertNotEqual(records[0]['injector_pid'], client.process.pid)
                self.assertEqual(records[0]['service_pid'], client.process.pid)
                self.assertFalse(list(data.glob('temp/injection-*/request.json')))
            finally:
                if not client.process.stdout.closed:
                    client.close()

    def test_exit_zero_without_result(self): self.exercise_child('0')
    def test_nonzero_exit(self): self.exercise_child('7')
    def test_valid_completion(self): self.exercise_child('success')
    def test_invalid_result_token(self): self.exercise_child('bad-token')
    def test_close_during_injection(self): self.exercise_child('hang')

    def test_real_injector_preflight_without_service_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request, result = root / 'request.json', root / 'result.json'
            request.write_text(json.dumps({'token': 'fixture', 'settings': {}}))
            frozen = os.environ.get('OMGNEO_FROZEN_BACKEND')
            command = [str(Path(frozen).with_name('omg_injector.exe'))] if frozen else [sys.executable, str(BACKEND / 'main.py')]
            process = subprocess.run(command + ['--injector',
                '--data-root', str(root), '--request-file', str(request), '--result-file', str(result)],
                capture_output=True, timeout=20)
            self.assertEqual(process.returncode, 0, process.stderr.decode(errors='replace'))
            self.assertFalse(json.loads(result.read_text(encoding='utf-8'))['ok'])
            self.assertFalse((root / '.backend.lock').exists())

    def test_injector_reports_only_after_worker_thread_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request, result = root / 'request.json', root / 'result.json'
            request.write_text(json.dumps({'token': 'fixture', 'settings': {}}))
            code = f'''
import sys,time,threading
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,{str(BACKEND)!r})
import main
main.bootstrap(Path({str(root)!r}),Path({str(BACKEND.parent / 'OMGLite' / 'src')!r}))
from omg.domain.launch.controller import LaunchController
from omg.domain.launch.worker import LaunchWorker
LaunchController._build_task=lambda self: (True,'',SimpleNamespace(d3dx_target='fixture.exe'))
def run(self):
 assert not self._verify_injection
 assert threading.current_thread() is not threading.main_thread()
 self.verification_state='skipped'
 self.finished.emit(True,'fixture completion')
 time.sleep(.1)
 Path({str(root / 'cleanup.done')!r}).write_text('done')
LaunchWorker.run=run
raise SystemExit(main.main())
'''
            process = subprocess.run([sys.executable, '-c', code, '--injector', '--data-root', str(root),
                '--request-file', str(request), '--result-file', str(result)], capture_output=True, timeout=20)
            self.assertEqual(process.returncode, 0, process.stderr.decode(errors='replace'))
            output = json.loads(result.read_text(encoding='utf-8'))
            self.assertTrue(output['ok'])
            self.assertEqual(output['verification'], 'skipped')
            self.assertEqual(output['token'], 'fixture')
            self.assertTrue((root / 'cleanup.done').exists())
            self.assertGreaterEqual(result.stat().st_mtime_ns, (root / 'cleanup.done').stat().st_mtime_ns)
