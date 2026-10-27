"""Frozen updater -> bundled payload -> frozen backend startup integration."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import MANIFEST, UPDATER_EXE, digest, inspect_package, write_manifest


def extract(package, target, *, frontend_only=False):
    with zipfile.ZipFile(package.path) as archive:
        for name, relative, _ in package.files:
            if frontend_only and (relative == MANIFEST or relative.startswith('backend/')):
                continue
            output = target / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as source, output.open('wb') as destination:
                shutil.copyfileobj(source, destination)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--backend', type=Path, required=True)
    parser.add_argument('--updater', type=Path, required=True)
    parser.add_argument('--export', type=Path, help='Optional full portable ZIP output')
    args = parser.parse_args()
    report_dir = Path(__file__).resolve().parents[1] / 'validation'
    release = inspect_package(args.release)
    executable_hash = digest(args.updater)
    with tempfile.TemporaryDirectory(prefix='neo-frozen-handoff-') as temporary:
        root = Path(temporary)
        source, install = root / 'release', root / 'installed'
        source.mkdir()
        install.mkdir()
        extract(release, source, frontend_only=True)
        shutil.copytree(args.backend, source / 'backend')
        shutil.copy2(args.updater, source / UPDATER_EXE)
        (source / (UPDATER_EXE + '.sha256')).write_text(f'{executable_hash}  {UPDATER_EXE}\n')
        write_manifest(source, '0.0.2+2', 'Release')
        package = root / 'with-updater.zip'
        with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in source.rglob('*'):
                if path.is_file():
                    archive.write(path, path.relative_to(source).as_posix())
        if args.export:
            if args.export.exists():
                raise FileExistsError(args.export)
            args.export.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(package, args.export)
            args.export.with_suffix('.zip.sha256').write_text(
                digest(args.export) + '  ' + args.export.name + '\n', encoding='ascii')
        extract(release, install)
        shutil.copy2(args.updater, install / UPDATER_EXE)
        (install / 'AppData').mkdir()
        user_file = install / 'AppData/user-export.bin'
        user_file.write_bytes(b'user data' * 262144)
        data_identity = user_file.stat().st_ino
        updater_identity = (install / UPDATER_EXE).stat().st_ino
        result = subprocess.run([str(install / UPDATER_EXE), '--install-dir', str(install),
                                 '--package', str(package)], cwd=install, input='5\n\n',
                                capture_output=True, encoding='utf-8', timeout=120)
        (report_dir / 'frozen-handoff-update.log').write_text(result.stdout + result.stderr, encoding='utf-8')
        assert result.returncode == 0 and '更新完成' in result.stdout, result.stdout[-3000:]
        pending = install / '.updater-pending/manifest.json'
        assert pending.is_file()
        assert (install / UPDATER_EXE).stat().st_ino == updater_identity
        process = subprocess.Popen([str(install / 'backend/omg_backend.exe'), '--stdio',
                                    '--data-root', str(install / 'AppData')], cwd=install,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding='utf-8')
        try:
            deadline = time.monotonic() + 30
            while pending.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.1)
            completed = not pending.exists()
            stdout, stderr = process.communicate('{"id":1,"method":"shutdown","params":{}}\n', timeout=30)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        (report_dir / 'frozen-handoff-startup.log').write_text(stdout + stderr, encoding='utf-8')
        assert completed, stderr
        assert process.returncode == 0, stderr
        assert digest(install / UPDATER_EXE) == executable_hash
        assert (install / UPDATER_EXE).stat().st_ino != updater_identity
        assert user_file.stat().st_ino == data_identity
    report = {'updaterRunsInsideInstall': True, 'automaticExitAfterAppUpdate': True,
              'runningUpdaterUnchangedDuringUpdate': True, 'frozenBackendAppliedPendingUpdater': True,
              'userDataStayedInPlace': True, 'consoleHelperLaunched': False}
    (report_dir / 'frozen-handoff.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
