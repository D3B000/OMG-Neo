# Two independently analyzed entrypoints, one shared onedir runtime.
from pathlib import Path
import hashlib
import json
import zipfile

from PyInstaller.config import CONF

root = Path(SPECPATH)
lite = root.parent / 'OMGLite/src'
icon = str(root.parent / 'omg_neo/krr.ico')
excluded = ['PySide6.QtWidgets', 'PySide6.QtGui', 'PySide6.QtMultimedia',
            'PySide6.QtNetwork', 'cryptography', 'OpenSSL', 'urllib3.contrib.pyopenssl']
service = Analysis([str(root / 'main.py')], pathex=[str(root), str(lite)],
    binaries=[], datas=[(str(root / 'vendor/ritual'), 'resources/binaries/ritual')],
    hiddenimports=['omg.core.paths'], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=excluded, noarchive=False, optimize=0)
injector = Analysis([str(root / 'injector_main.py')], pathex=[str(root), str(lite)],
    binaries=[], datas=[(str(lite / 'omg/resources/binaries/loader'), 'resources/binaries/loader')],
    hiddenimports=['omg.core.paths'], hookspath=[], hooksconfig={},
    runtime_hooks=[], excludes=excluded, noarchive=False, optimize=0)

def check_modules(host, modules, forbidden):
    unexpected = sorted(name for name in modules if any(
        name == prefix or name.startswith(prefix + '.') for prefix in forbidden))
    if unexpected:
        raise RuntimeError(f'{host} imported modules from the other host: {unexpected}')


service_modules = {entry[0] for entry in service.pure}
check_modules('Service', service_modules, ('injection_entry', 'injector_main',
              'omg.domain.inject', 'omg.domain.launch'))
injector_modules = {entry[0] for entry in injector.pure}
check_modules('Injector', injector_modules, ('main', 'build_service', 'resource_service', 'resource_browser',
             'injection_service', 'omg.core.alchemy', 'omg.core.gimi_update',
             'omg.core.lanzou', 'requests', 'urllib3'))

removed = {'opengl32sw.dll', 'icuuc.dll', 'icudt78.dll'}
def trimmed(entries):
    # Neither host installs a Qt translator.
    return [entry for entry in entries
            if Path(entry[0]).name.lower() not in removed
            and not entry[0].replace('\\', '/').startswith('PySide6/translations/')]

# Merge shared files explicitly. Never let collection order silently choose
# conflicting DLLs. base_library.zip can contain different bootstrap subsets;
# merge its bytecode members with the same conflict check.
def shared_files(*groups):
    result = {}
    for entry in (entry for group in groups for entry in trimmed(group)):
        destination, source, kind = entry
        key = destination.replace('\\', '/').casefold()
        old = result.get(key)
        if old is None:
            result[key] = entry
        elif Path(source).resolve() != Path(old[1]).resolve():
            if Path(destination).name == 'base_library.zip':
                members = {}
                for library in (old[1], source):
                    with zipfile.ZipFile(library) as archive:
                        for name in archive.namelist():
                            data = archive.read(name)
                            if name in members and members[name] != data:
                                raise RuntimeError(f'Conflicting bootstrap module: {name}')
                            members[name] = data
                merged = Path(CONF['workpath']) / 'shared_base_library.zip'
                with zipfile.ZipFile(merged, 'w', zipfile.ZIP_DEFLATED) as archive:
                    for name, data in sorted(members.items()):
                        archive.writestr(name, data)
                result[key] = (destination, str(merged), kind)
            elif kind != old[2] or hashlib.sha256(Path(source).read_bytes()).digest() != hashlib.sha256(Path(old[1]).read_bytes()).digest():
                raise RuntimeError(f'Conflicting shared dependency: {destination}')
    return list(result.values())

libraries = shared_files(service.binaries, injector.binaries)
assets = shared_files(service.datas, injector.datas)
service_exe = EXE(PYZ(service.pure), service.scripts, [], exclude_binaries=True,
    name='omg_backend', debug=False, strip=False, upx=False, console=True, icon=icon)
injector_exe = EXE(PYZ(injector.pure), injector.scripts, [], exclude_binaries=True,
    name='omg_injector', debug=False, strip=False, upx=False, console=True, icon=icon)
COLLECT(service_exe, injector_exe, libraries, assets, strip=False, upx=False, name='omg_backend')
Path(CONF['workpath'], 'host-modules.json').write_text(json.dumps({
    'service': sorted(service_modules),
    'injector': sorted(injector_modules),
    'sharedLibraries': sorted(entry[0] for entry in libraries),
    'sharedAssets': sorted(entry[0] for entry in assets),
}, indent=2), encoding='utf-8')
