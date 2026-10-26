"""Runtime probes for the two-entry validation-only build; no real game is run."""
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading
import http.server
import socketserver
import hashlib

from verify_size_reduction import certificate, Handler, ConnectProxy

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent / 'omg_neo/validation/independent-hosts-20261025'
BUNDLE = ROOT / 'probe-dist/omg_backend'

with tempfile.TemporaryDirectory(prefix='neo-independent-hosts-') as temporary:
    root = Path(temporary)
    cert, key = certificate(root)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    proxy = socketserver.ThreadingTCPServer(('127.0.0.1', 0), ConnectProxy)
    proxy.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    request = {'dataRoot': str(root / 'service'), 'url': f'https://localhost:{server.server_port}',
        'certificate': str(cert), 'proxy': f'http://127.0.0.1:{proxy.server_address[1]}',
        'sha256': hashlib.sha256(Handler.payload).hexdigest(), 'result': str(ROOT / 'service-probe.json')}
    request_file = root / 'probe-request.json'
    request_file.write_text(json.dumps(request))
    try:
        env = {**os.environ, 'SSL_CERT_FILE': str(cert), 'NO_PROXY': 'localhost,127.0.0.1',
            'HTTP_PROXY': '', 'HTTPS_PROXY': '', 'PYTHONUTF8': '1'}
        with (ROOT / 'service-probe.log').open('wb') as log:
            result = subprocess.run([str(BUNDLE / 'omg_backend.exe'), '--validation-probe',
                str(BACKEND / 'validation/frozen_dependency_probe.py'), str(request_file)],
                env=env, stdout=log, stderr=subprocess.STDOUT, timeout=90)
        assert result.returncode == 0, (ROOT / 'service-probe.log').read_text(errors='replace')
        with (ROOT / 'injector-probe-final.log').open('wb') as log:
            result = subprocess.run([str(BUNDLE / 'omg_injector.exe'), '--validation-probe',
                str(BACKEND / 'validation/frozen_injector_probe.py'), str(root / 'injector')],
                env=env, stdout=log, stderr=subprocess.STDOUT, timeout=30)
        assert result.returncode == 0, (ROOT / 'injector-probe-final.log').read_text(errors='replace')
        (ROOT / 'injector-probe.json').write_text((root / 'injector/injector-probe.json').read_text())
        service = json.loads((ROOT / 'service-probe.json').read_text())
        assert not service['cryptographyPresent'] and all(service['checks'].values())
        assert ConnectProxy.connects > 0
        print('Frozen service TLS/build/native probes and minimal injector spawn/worker probes passed')
    finally:
        server.shutdown()
        server.server_close()
        proxy.shutdown()
        proxy.server_close()
