"""Build and validate four isolated packaging candidates. Production is unchanged."""
import argparse
import collections
import datetime
import hashlib
import http.server
import ipaddress
import json
import os
from pathlib import Path
import select
import shutil
import socket
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
import zlib

BACKEND = Path(__file__).resolve().parents[1]
WORKSPACE = BACKEND.parents[1]
OUTPUT = BACKEND.parent / 'omg_neo/validation/package-size-20261025'
VARIANTS = ['control', 'without-opengl', 'without-crypto', 'combined']


def build(name, exclude_crypto=False):
    root = OUTPUT / name
    root.mkdir(parents=True, exist_ok=True)
    assert root.resolve().is_relative_to(OUTPUT.resolve())
    assert not (root / 'dist/omg_backend/omg_backend.exe').exists(), 'Refusing to overwrite a previous validation build'
    lite = BACKEND.parent / 'OMGLite/src'
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir', '--name', 'omg_backend',
        '--icon', str(BACKEND.parent / 'omg_neo/krr.ico'), '--distpath', str(root / 'dist'),
        '--workpath', str(root / 'work'), '--specpath', str(root), '--paths', str(lite),
        '--hidden-import', 'omg.core.paths', '--runtime-hook', str(Path(__file__).with_name('size_probe_hook.py'))]
    excluded = ['PySide6.QtWidgets', 'PySide6.QtGui', 'PySide6.QtMultimedia', 'PySide6.QtNetwork']
    if exclude_crypto:
        excluded += ['cryptography', 'OpenSSL', 'urllib3.contrib.pyopenssl']
    for module in excluded:
        command += ['--exclude-module', module]
    command += ['--add-data', f'{lite / "omg/resources/binaries/loader"};resources/binaries/loader',
        '--add-data', f'{BACKEND / "vendor/ritual"};resources/binaries/ritual', str(BACKEND / 'main.py')]
    with (root / 'build.log').open('wb') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
            env={**os.environ, 'PYINSTALLER_CONFIG_DIR': str(root / 'cache')}, check=True)
    bundle = root / 'dist/omg_backend'
    for name in ('icuuc.dll', 'icudt78.dll'):
        (bundle / '_internal' / name).unlink(missing_ok=True)
    shutil.copy2(bundle / 'omg_backend.exe', bundle / 'omg_injector.exe')


def derive(source, destination):
    src = OUTPUT / source / 'dist/omg_backend'
    dst = OUTPUT / destination / 'dist/omg_backend'
    assert dst.resolve().is_relative_to(OUTPUT.resolve())
    shutil.copytree(src, dst)
    (dst / '_internal/PySide6/opengl32sw.dll').unlink()


def measure(bundle):
    size, compressed = 0, 0
    for path in bundle.rglob('*'):
        if not path.is_file():
            continue
        size += path.stat().st_size
        compressor = zlib.compressobj(6, zlib.DEFLATED, -15)
        with path.open('rb') as stream:
            while chunk := stream.read(262144):
                compressed += len(compressor.compress(chunk))
        compressed += len(compressor.flush())
    return {'bytes': size, 'zipPayloadBytes': compressed,
        'unpackedMiB': round(size / 1048576, 2), 'zipPayloadMiB': round(compressed / 1048576, 2)}


class Handler(http.server.BaseHTTPRequestHandler):
    payload = b'packaging TLS fixture\n' * 8192
    def do_GET(self):
        body = b'{"fixture": true}' if self.path == '/json' else self.payload
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Content-Type', 'application/json' if self.path == '/json' else 'application/octet-stream')
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass


class ConnectProxy(socketserver.StreamRequestHandler):
    connects = 0
    def handle(self):
        line = self.rfile.readline().decode('ascii')
        while self.rfile.readline().strip():
            pass
        verb, target, _ = line.split()
        assert verb == 'CONNECT'
        host, port = target.rsplit(':', 1)
        assert host in ('127.0.0.1', 'localhost'), 'Local fixtures only'
        type(self).connects += 1
        with socket.create_connection((host, int(port)), timeout=10) as upstream:
            self.wfile.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            self.wfile.flush()
            sockets = [self.connection, upstream]
            while True:
                readable, _, _ = select.select(sockets, [], [], 10)
                if not readable:
                    return
                for src in readable:
                    chunk = src.recv(65536)
                    if not chunk:
                        return
                    (upstream if src is self.connection else self.connection).sendall(chunk)


def certificate(root):
    # The host creates a test certificate. Frozen candidates must NOT use this
    # host-side cryptography installation, including the no-crypto candidates.
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, 'Neo local validation')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),
            x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256()))
    crt, pem = root / 'ca.pem', root / 'key.pem'
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
    return crt, pem


def validate(probes_only=False):
    previous = json.loads((OUTPUT / 'report.json').read_text()) if probes_only else None
    report = {'validationOnly': True, 'variants': {}, 'limitations': [
        'Local trusted TLS and CONNECT proxy are exercised; no live third-party download service is contacted.',
        'Injector preflight and child lifecycle are tested; no real game or injection hook is executed.',
        'Some existing tests use source fixtures even when a frozen executable is selected; the dependency probe and non-fixture integration cases use the frozen runtime.']}
    with tempfile.TemporaryDirectory(prefix='neo-size-validation-') as temporary:
        temp = Path(temporary)
        crt, key = certificate(temp)
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(crt, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        proxy = socketserver.ThreadingTCPServer(('127.0.0.1', 0), ConnectProxy)
        proxy.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        threading.Thread(target=proxy.serve_forever, daemon=True).start()
        try:
            for name in VARIANTS:
                root = OUTPUT / name
                bundle = root / 'dist/omg_backend'
                executable = bundle / 'omg_backend.exe'
                item = measure(bundle)
                request = {'dataRoot': str(temp / name), 'url': f'https://localhost:{server.server_port}',
                    'certificate': str(crt), 'proxy': f'http://127.0.0.1:{proxy.server_address[1]}',
                    'sha256': hashlib.sha256(Handler.payload).hexdigest(), 'result': str(root / 'dependency-result.json')}
                request_file = root / 'probe-request.json'
                request_file.write_text(json.dumps(request), encoding='utf-8')
                env = {**os.environ, 'SSL_CERT_FILE': str(crt), 'NO_PROXY': 'localhost,127.0.0.1',
                    'HTTP_PROXY': '', 'HTTPS_PROXY': '', 'PYTHONUTF8': '1'}
                connects_before = ConnectProxy.connects
                with (root / 'dependency-probe.log').open('wb') as log:
                    run = subprocess.run([str(executable), '--validation-probe',
                        str(Path(__file__).with_name('frozen_dependency_probe.py')), str(request_file)],
                        stdout=log, stderr=subprocess.STDOUT, env=env, timeout=90)
                item['probeExitCode'] = run.returncode
                if run.returncode:
                    report['variants'][name] = item
                    (OUTPUT / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
                    raise RuntimeError(f'{name}: see {root / "dependency-probe.log"}')
                item['dependencyProbe'] = json.loads(Path(request['result']).read_text(encoding='utf-8'))
                item['localConnectProxyUsed'] = ConnectProxy.connects > connects_before
                if name in ('without-crypto', 'combined'):
                    assert not item['dependencyProbe']['cryptographyPresent']
                    assert not item['dependencyProbe']['cryptoLoadedAfterAllChecks']
                if probes_only:
                    item['regressionExitCode'] = previous['variants'][name]['regressionExitCode']
                else:
                    with (root / 'regression.log').open('wb') as log:
                        tests = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s',
                            str(BACKEND / 'tests'), '-q'], stdout=log, stderr=subprocess.STDOUT,
                            env={**env, 'OMGNEO_FROZEN_BACKEND': str(executable)}, timeout=180)
                    item['regressionExitCode'] = tests.returncode
                report['variants'][name] = item
                (OUTPUT / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
                assert item['regressionExitCode'] == 0, f'{name}: see {root / "regression.log"}'
                print(name, json.dumps(item), flush=True)
        finally:
            server.shutdown()
            server.server_close()
            proxy.shutdown()
            proxy.server_close()
    print('Validation complete:', OUTPUT / 'report.json', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--probes-only', action='store_true')
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if args.build:
        build('control')
        derive('control', 'without-opengl')
        build('without-crypto', True)
        derive('without-crypto', 'combined')
    validate(args.probes_only)
