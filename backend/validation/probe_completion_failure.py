"""Fault injection in an isolated source service; never changes production code."""
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading

BACKEND = Path(__file__).resolve().parents[1]


def probe(fault='build_state'):
    with tempfile.TemporaryDirectory(prefix='neo-completion-analysis-') as temporary:
        root = Path(temporary)
        code = f'''import sys
from pathlib import Path
sys.path.insert(0,{str(BACKEND)!r})
import main
main.bootstrap(Path({str(root)!r}),Path({str(BACKEND.parent / 'OMGLite/src')!r}))
from build_service import BuildService
fault={fault!r}
def unreadable_state(self):
 raise PermissionError('analysis fixture: build state unavailable')
if fault == 'build_state':
 BuildService.state=unreadable_state
else:
 original_snapshot=main.SettingsStore.snapshot
 original_scan=BuildService.cleanup_scan
 fail_reads=False
 def snapshot(self):
  if fail_reads: raise PermissionError('analysis fixture: snapshot unavailable')
  return original_snapshot(self)
 def scan(self):
  global fail_reads
  result=original_scan(self)
  fail_reads=True
  return result
 main.SettingsStore.snapshot=snapshot
 BuildService.cleanup_scan=scan
raise SystemExit(main.main())
'''
        process = subprocess.Popen([sys.executable, '-u', '-c', code, '--stdio', '--data-root', str(root)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding='utf-8', errors='replace')
        messages, events = queue.Queue(), []
        errors = []
        def read():
            for line in process.stdout:
                messages.put(json.loads(line))
        reader = threading.Thread(target=read, daemon=True)
        error_reader = threading.Thread(target=lambda: errors.extend(process.stderr), daemon=True)
        reader.start()
        error_reader.start()
        counter = 0
        def call(method):
            nonlocal counter
            counter += 1
            process.stdin.write(json.dumps({'v': 1, 'id': str(counter), 'method': method, 'params': {}}) + '\n')
            process.stdin.flush()
            while True:
                message = messages.get(timeout=10)
                if message.get('id') == str(counter):
                    return message
                events.append(message)
        try:
            call('hello')
            accepted = call('build.cleanup.scan')
            threading.Event().wait(.5)
            reply = call('hello')
            snapshot = reply.get('result', {}).get('snapshot', {})
            call('shutdown')
            try:
                process.wait(timeout=2)
                shutdown_exited = True
            except subprocess.TimeoutExpired:
                shutdown_exited = False
            events.extend(list(messages.queue))
            return {'injectedFault': fault,
                'taskAccepted': 'result' in accepted,
                'completionReceived': any(e.get('event') == 'task.finished' for e in events),
                'activeTaskAfterFault': snapshot.get('activeTask'),
                'snapshotAvailable': 'result' in reply,
                'shutdownExitedWithin2Seconds': shutdown_exited,
                'exceptionObserved': any('analysis fixture' in line for line in errors)}
        finally:
            if process.poll() is None:
                process.kill()  # Only this owned, temporary fault-injection service.
            process.wait(timeout=5)
            process.stdin.close()
            reader.join(timeout=2)
            error_reader.join(timeout=2)
            process.stdout.close()
            process.stderr.close()


if __name__ == '__main__':
    result = probe()
    output = BACKEND.parent / 'omg_neo/validation/completion-failure-analysis.json'
    output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
