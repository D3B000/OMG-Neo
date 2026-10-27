"""Exercise the shipped TUI binary against real packages in a disposable install."""
import argparse
import json
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine import MANIFEST, Updater, digest, inspect_package, validate_payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--updater', type=Path, required=True)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--debug', type=Path, required=True)
    args = parser.parse_args()
    executable = args.updater.absolute()
    executable_hash = digest(executable)
    records = ROOT / 'validation'
    records.mkdir(exist_ok=True)

    def run(arguments, inputs, log_name):
        result = subprocess.run([str(executable), *map(str, arguments)], input=inputs,
                                capture_output=True, encoding='utf-8', errors='replace',
                                cwd=install, timeout=120)
        (records / log_name).write_text(result.stdout + '\n' + result.stderr, encoding='utf-8')
        assert result.returncode == 0, result.stderr or result.stdout[-2000:]
        assert '操作未完成' not in result.stdout, result.stdout[-3000:]
        return result.stdout

    with tempfile.TemporaryDirectory(prefix='neo-updater-frozen-') as temporary:
        install = Path(temporary) / 'OMG-Neo'
        install.mkdir()
        package = inspect_package(args.release)
        with zipfile.ZipFile(package.path) as archive:
            for name, relative, _ in package.files:
                target = install / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, target.open('xb') as destination:
                    shutil.copyfileobj(source, destination)
        bundled_updater = install / 'OMG-Neo-Updater.exe'
        shutil.copy2(executable, bundled_updater)
        executable = bundled_updater
        run(['--create-manifest', install, '--version', '0.0.1+1', '--configuration', 'Release'],
            '', 'frozen-manifest.log')
        assert validate_payload(install)['version'] == '0.0.1+1'
        (install / MANIFEST).unlink()  # Test legacy-package compatibility too.
        (install / 'AppData').mkdir()
        settings = install / 'AppData/config.json'
        settings.write_text('{"theme":"dark","user":"保留数据"}', encoding='utf-8')
        (install / 'ui-reviews').mkdir()
        (install / 'ui-reviews/note.txt').write_text('user export', encoding='utf-8')
        (install / 'obsolete.dll').write_bytes(b'old dependency')
        old_executable = digest(install / 'omg_neo.exe')
        data_identity = settings.stat().st_ino
        output = run(['--install-dir', install, '--package', args.debug.absolute()],
                     '4\n\n5\n\n\n0\n', 'frozen-update.log')
        assert '更新完成' in output
        assert validate_payload(install)['configuration'] == 'Debug'
        assert json.loads(settings.read_text(encoding='utf-8'))['user'] == '保留数据'
        assert not (install / 'obsolete.dll').exists()
        transaction, record = Updater(install).transactions()[0]
        assert record['hash_verified']
        assert digest(transaction / 'backup/omg_neo.exe') == old_executable
        assert not (transaction / 'backup/AppData').exists()
        assert settings.stat().st_ino == data_identity
        assert digest(bundled_updater) == executable_hash
        settings.write_text('{"theme":"light","user":"更新后的设置"}', encoding='utf-8')
        output = run(['--install-dir', install], '6\n1\nROLLBACK\n\n0\n', 'frozen-rollback.log')
        assert '回退完成' in output
        assert validate_payload(install)['configuration'] == 'Release'
        assert digest(install / 'omg_neo.exe') == old_executable
        assert json.loads(settings.read_text(encoding='utf-8'))['user'] == '更新后的设置'
        assert (install / 'ui-reviews/note.txt').read_text() == 'user export'
    report = {'frozenTUIUpdate': 'Release -> Debug', 'frozenTUIRollback': 'Debug -> Release',
              'existingPackages': 'accepted with sidecar verification',
              'userData': 'preserved; rollback keeps current settings',
              'obsoleteDLL': 'removed on update', 'backup': 'original executable hash verified',
              'manifestCommand': 'native EXE generated a valid 0.0.1+1 Release manifest',
              'updaterInsideInstall': True, 'userDataCopied': False,
              'realInstallationsModified': False, 'updaterSHA256': executable_hash}
    (records / 'frozen-integration.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
