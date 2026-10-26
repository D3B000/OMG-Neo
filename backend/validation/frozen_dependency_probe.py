"""Exercise actual frozen TLS/imports without injecting or starting a game."""
import hashlib
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import ssl
import sys
import urllib.request

import requests
import urllib3

request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
root = Path(request['dataRoot'])
root.mkdir(parents=True, exist_ok=True)
report = {'frozen': bool(getattr(sys, 'frozen', False)), 'hasSNI': ssl.HAS_SNI,
          'cryptographyPresent': importlib.util.find_spec('cryptography') is not None,
          'checks': {}}
assert report['frozen'] and report['hasSNI']
assert Path(requests.__file__).is_relative_to(Path(sys._MEIPASS))
base, certificate = request['url'], request['certificate']
session = requests.Session()
session.trust_env = False
report['checks']['requestsVerifiedTLS'] = session.get(base + '/json', verify=certificate, timeout=10).json() == {'fixture': True}
with session.get(base + '/blob', verify=certificate, stream=True, timeout=10) as response:
    response.raise_for_status()
    digest = hashlib.sha256()
    for chunk in response.iter_content(16384):
        digest.update(chunk)
    report['checks']['requestsStreamingDownload'] = digest.hexdigest() == request['sha256']
try:
    session.get(base + '/json', verify=True, timeout=10)
except requests.exceptions.SSLError:
    report['checks']['untrustedCertificateRejected'] = True
else:
    report['checks']['untrustedCertificateRejected'] = False
proxy = {'http': request['proxy'], 'https': request['proxy']}
report['checks']['requestsHTTPSConnectProxy'] = session.get(base + '/json', verify=certificate,
    proxies=proxy, timeout=10).json() == {'fixture': True}
with urllib.request.urlopen(base + '/blob', context=ssl.create_default_context(cafile=certificate), timeout=10) as response:
    report['checks']['stdlibVerifiedTLS'] = hashlib.sha256(response.read()).hexdigest() == request['sha256']
pool = urllib3.PoolManager(cert_reqs='CERT_REQUIRED', ca_certs=certificate)
try:
    response = pool.request('GET', base + '/json', timeout=10)
    report['checks']['urllib3VerifiedTLS'] = json.loads(response.data) == {'fixture': True}
finally:
    pool.clear()
session.close()

try:
    from backend_runtime import bootstrap
except ModuleNotFoundError:
    from main import bootstrap  # Earlier comparison bundles predate the shared bootstrap.
bootstrap(root, None)
from omg.core import download, lanzou
report['checks']['lanzouImports'] = lanzou is not None
# Use the production opener selection, but fail if it attempts the insecure
# fallback. The generated CA is trusted through this child's SSL_CERT_FILE.
def forbid_insecure(*args, **kwargs):
    raise AssertionError('insecure TLS fallback used')
for _, opener in download.get_openers(prefer_direct=True):
    for handler in opener.handlers:
        if isinstance(handler, urllib.request.HTTPSHandler):
            if handler._context.verify_mode != ssl.CERT_REQUIRED:
                opener.open = forbid_insecure
destination = root / 'download.bin'
ok, message = download.download_file_smart(base + '/blob', str(destination), timeout=10, use_proxies=False)
report['checks']['productionDownloaderVerifiedTLS'] = bool(ok) and hashlib.sha256(destination.read_bytes()).hexdigest() == request['sha256']

from settings_store import SettingsStore
from build_service import BuildService
from PySide6.QtCore import QCoreApplication
app = QCoreApplication.instance() or QCoreApplication([])
builds = BuildService(root, SettingsStore(root), lambda settings: None)
report['checks']['nativeBuildCapabilities'] = builds.state()['capabilities'] == {'build': True, 'ritual': [True, True, True]}
native = ctypes.WinDLL('kernel32', use_last_error=True)
native.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
native.GetModuleHandleW.restype = ctypes.c_void_p
native.FreeLibrary.argtypes = [ctypes.c_void_p]
native.FreeLibrary.restype = ctypes.c_int
loader = ctypes.WinDLL(str(Path(sys._MEIPASS) / 'resources/binaries/loader/3dmloader.dll'))
report['checks']['injectionLibraryExports'] = callable(loader.HookLibrary) and callable(loader.UnhookLibrary)
report['checks']['injectionLibraryUnloaded'] = bool(native.FreeLibrary(loader._handle))
loader._handle = 0
report['checks']['softwareOpenGLNotLoaded'] = native.GetModuleHandleW('opengl32sw.dll') is None
report['cryptoLoadedAfterAllChecks'] = any(name == 'cryptography' or name.startswith('cryptography.') for name in sys.modules)
Path(request['result']).write_text(json.dumps(report, indent=2), encoding='utf-8')
assert all(report['checks'].values()), report
