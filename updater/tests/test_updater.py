from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine import (MANIFEST, UpdateError, Updater, digest, inspect_package,
                    preview_payload, validate_payload, write_manifest)
from platform_ops import exclusive_lock, running_processes
from sources import GitHubSource, Release


def pe(tag=b''):
    header = bytearray(64)
    header[:2] = b'MZ'
    struct.pack_into('<I', header, 60, 64)
    return bytes(header) + b'PE\0\0\x64\x86' + tag


def payload(root: Path, tag=b'new', debug=False):
    root.mkdir(parents=True, exist_ok=True)
    for name in ('omg_neo.exe', 'flutter_windows.dll', 'backend/omg_backend.exe', 'backend/omg_injector.exe'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pe(tag))
    for name in ('data/icudtl.dat', 'data/flutter_assets/fonts/font.ttf', 'backend/_internal/python311.dll',
                 'data/flutter_assets/kernel_blob.bin' if debug else 'data/app.so'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(tag)
    (root / 'README.txt').write_bytes(tag)


def archive(source: Path, path: Path, prefix='OMG-Neo-v0.0.1/'):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for file in source.rglob('*'):
            if file.is_file():
                bundle.write(file, prefix + file.relative_to(source).as_posix())


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='neo-updater-tests-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'installed'
        self.source = self.root / 'release'
        payload(self.target, b'old')
        payload(self.source)
        (self.target / 'AppData').mkdir()
        (self.target / 'AppData/config.json').write_text('{"theme":"dark"}')
        (self.target / 'ui-reviews').mkdir()
        (self.target / 'ui-reviews/notes.json').write_text('my review')
        (self.target / 'custom.txt').write_text('keep me')
        (self.target / 'obsolete.dll').write_bytes(b'obsolete')
        (self.target / 'backend/obsolete.dll').write_bytes(b'obsolete')
        self.zip = self.root / 'update.zip'
        archive(self.source, self.zip)
        self.updater = Updater(self.target, process_check=lambda _: [])

    def assert_original(self):
        self.assertEqual((self.target / 'omg_neo.exe').read_bytes(), pe(b'old'))
        self.assertEqual((self.target / 'custom.txt').read_text(), 'keep me')
        self.assertEqual((self.target / 'AppData/config.json').read_text(), '{"theme":"dark"}')

    def add_entry(self, name, data=b'bad'):
        with zipfile.ZipFile(self.zip, 'a') as bundle:
            bundle.writestr(name, data)

    def test_complete_replace_preserves_data_and_backup(self):
        work = self.updater.apply(self.zip)
        self.assertEqual((self.target / 'omg_neo.exe').read_bytes(), pe(b'new'))
        self.assertEqual((work / 'backup/omg_neo.exe').read_bytes(), pe(b'old'))
        self.assertEqual((self.target / 'AppData/config.json').read_bytes(), (work / 'backup/AppData/config.json').read_bytes())
        self.assertEqual((self.target / 'ui-reviews/notes.json').read_text(), 'my review')
        self.assertEqual((self.target / 'custom.txt').read_text(), 'keep me')
        self.assertFalse((self.target / 'obsolete.dll').exists())
        self.assertFalse((self.target / 'backend/obsolete.dll').exists())
        self.assertEqual(json.loads((work / 'journal.json').read_text(encoding='utf-8'))['state'], 'installed')
        self.assertFalse(json.loads((work / 'journal.json').read_text(encoding='utf-8'))['hash_verified'])

    def test_rollback_keeps_current_userdata_and_backs_up_current_program(self):
        work = self.updater.apply(self.zip)
        (self.target / 'AppData/config.json').write_text('new user settings')
        rollback = self.updater.rollback(work)
        self.assertEqual((self.target / 'omg_neo.exe').read_bytes(), pe(b'old'))
        self.assertEqual((self.target / 'AppData/config.json').read_text(), 'new user settings')
        self.assertEqual((rollback / 'backup/omg_neo.exe').read_bytes(), pe(b'new'))
        self.assertEqual((work / 'backup/AppData/config.json').read_text(), '{"theme":"dark"}')

    def test_stage_rename_failure_restores_whole_old_install(self):
        original = Path.rename

        def fail(path, destination):
            if path.name == 'stage' and Path(destination) == self.target:
                raise PermissionError('simulated occupied destination')
            return original(path, destination)

        with patch.object(Path, 'rename', fail):
            with self.assertRaises(PermissionError):
                self.updater.apply(self.zip)
        self.assert_original()
        self.assertEqual(self.updater.transactions()[0][1]['state'], 'rolled_back')

    def test_userdata_copy_failure_never_switches(self):
        with patch.object(self.updater, '_copy', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.updater.apply(self.zip)
        self.assert_original()
        self.assertEqual(self.updater.transactions()[0][1]['state'], 'aborted')

    def test_userdata_copy_hash_detects_corruption(self):
        original = self.updater._copy
        def corrupt(source, destination):
            original(source, destination)
            if source.name == 'custom.txt':
                destination.write_text('corrupt copy')
        with patch.object(self.updater, '_copy', corrupt):
            with self.assertRaisesRegex(UpdateError, '复制校验失败'):
                self.updater.apply(self.zip)
        self.assert_original()

    def test_backend_byte_lock_held_during_preparation_and_released_after(self):
        checks = []
        def progress(stage, *_):
            if stage == '解压更新包' and not checks:
                with self.assertRaises(RuntimeError):
                    with exclusive_lock(self.target / 'AppData/.backend.lock'):
                        pass
                checks.append(True)
        self.updater.progress = progress
        work = self.updater.apply(self.zip)
        self.assertEqual(checks, [True])
        with exclusive_lock(work / 'backup/AppData/.backend.lock'):
            pass

    def test_ctrl_c_before_switch_preserves_original(self):
        def cancel(stage, *_):
            if stage == '解压更新包':
                raise KeyboardInterrupt()
        self.updater.progress = cancel
        with self.assertRaises(KeyboardInterrupt):
            self.updater.apply(self.zip)
        self.assert_original()

    def test_process_running_refuses_before_backup(self):
        self.updater.process_check = lambda _: ['omg_backend.exe (PID 123)']
        with self.assertRaisesRegex(UpdateError, '正常退出'):
            self.updater.apply(self.zip)
        self.assert_original()
        self.assertEqual(self.updater.transactions(), [])

    def test_process_started_during_preparation_is_caught(self):
        checks = iter([[], ['omg_neo.exe']])
        self.updater.process_check = lambda _: next(checks)
        with self.assertRaises(UpdateError):
            self.updater.apply(self.zip)
        self.assert_original()

    def test_insufficient_space_never_changes_install(self):
        with patch('engine.shutil.disk_usage', return_value=type('Disk', (), {'free': 1})()):
            with self.assertRaisesRegex(UpdateError, '空间不足'):
                self.updater.apply(self.zip)
        self.assert_original()

    def test_missing_runtime_and_bad_machine_rejected(self):
        (self.source / 'backend/_internal/python311.dll').unlink()
        archive(self.source, self.zip)
        with self.assertRaises(UpdateError):
            self.updater.apply(self.zip)
        self.assert_original()
        payload(self.source)
        (self.source / 'omg_neo.exe').write_bytes(b'fake')
        archive(self.source, self.zip)
        with self.assertRaisesRegex(UpdateError, 'Windows EXE'):
            self.updater.apply(self.zip)
        self.assert_original()

    def test_manifest_and_local_sidecar_verified(self):
        write_manifest(self.source, '0.0.1+1', 'Release')
        archive(self.source, self.zip)
        self.zip.with_suffix('.zip.sha256').write_text(digest(self.zip) + '  update.zip\n')
        package = inspect_package(self.zip)
        self.assertTrue(package.hash_verified)
        self.assertEqual(preview_payload(package)['version'], '0.0.1+1')
        work = self.updater.apply(self.zip)
        self.assertTrue(json.loads((work / 'journal.json').read_text(encoding='utf-8'))['hash_verified'])

    def test_manifest_tamper_rejected(self):
        write_manifest(self.source, '0.0.1+1', 'Release')
        (self.source / 'data/app.so').write_bytes(b'tampered')
        archive(self.source, self.zip)
        with self.assertRaisesRegex(UpdateError, '校验失败'):
            self.updater.apply(self.zip)
        self.assert_original()

    def test_manifest_writer_rejects_wrong_configuration(self):
        with self.assertRaisesRegex(UpdateError, '清单模式'):
            write_manifest(self.source, '0.0.1+1', 'Debug')
        self.assertFalse((self.source / MANIFEST).exists())

    def test_manifest_regenerated_after_final_readme(self):
        write_manifest(self.source, '0.0.2+2', 'Release')
        (self.source / 'README.txt').write_text('OMG-Neo 0.0.2 final readme')
        with self.assertRaises(UpdateError):
            validate_payload(self.source)
        write_manifest(self.source, '0.0.2+2', 'Release')
        self.assertEqual(validate_payload(self.source)['version'], '0.0.2+2')
        (self.source / 'AppData').mkdir()
        with self.assertRaisesRegex(UpdateError, '洁净分发'):
            write_manifest(self.source, '0.0.2+2', 'Release')

    def test_checksum_mismatch_and_wrong_sidecar_name(self):
        with self.assertRaisesRegex(UpdateError, 'SHA-256'):
            self.updater.apply(self.zip, '0' * 64)
        self.zip.with_suffix('.zip.sha256').write_text(digest(self.zip) + '  other.zip')
        with self.assertRaisesRegex(UpdateError, '包名不匹配'):
            inspect_package(self.zip)
        self.assert_original()

    def test_changed_since_review_rejected(self):
        reviewed = digest(self.zip)
        (self.source / 'README.txt').write_text('changed')
        archive(self.source, self.zip)
        with self.assertRaisesRegex(UpdateError, '预览后'):
            self.updater.apply(self.zip, reviewed_sha256=reviewed)
        self.assert_original()

    def test_debug_and_root_level_zip_are_supported(self):
        (self.source / 'data/app.so').unlink()
        payload(self.source, debug=True)
        write_manifest(self.source, '0.0.1+1', 'Debug')
        archive(self.source, self.zip, prefix='')
        self.updater.apply(self.zip)
        self.assertEqual(validate_payload(self.target)['configuration'], 'Debug')

    def test_zip_path_and_data_rejections(self):
        cases = ['../escape', '/escape', 'C:/evil', 'OMG-Neo-v0.0.1/backend/a:stream',
                 'OMG-Neo-v0.0.1/backend/CON.txt', 'OMG-Neo-v0.0.1/backend/a. ',
                 'OMG-Neo-v0.0.1/AppData/config.json',
                 'OMG-Neo-v0.0.1/ui-reviews/x', 'OMG-Neo-v0.0.1/a.pdb',
                 'second/omg_neo.exe', 'OMG-Neo-v0.0.1/BACKEND/OMG_BACKEND.EXE']
        for name in cases:
            with self.subTest(name=name):
                archive(self.source, self.zip)
                self.add_entry(name)
                with self.assertRaises(UpdateError):
                    inspect_package(self.zip)
        self.assertFalse((self.root / 'escape').exists())
        self.assert_original()

    def test_raw_zip_backslash_path_is_rejected(self):
        # ZipInfo normalizes backslashes on Windows, so construct the on-disk attack explicitly.
        self.add_entry('OMG-Neo-v0.0.1/backend/evil')
        self.zip.write_bytes(self.zip.read_bytes().replace(b'backend/evil', b'backend\\evil'))
        with self.assertRaises(UpdateError):
            inspect_package(self.zip)

    def test_zip_symlink_and_file_directory_conflict_rejected(self):
        entry = zipfile.ZipInfo('OMG-Neo-v0.0.1/backend/link')
        entry.create_system = 3
        entry.external_attr = 0o120777 << 16
        with zipfile.ZipFile(self.zip, 'a') as bundle:
            bundle.writestr(entry, 'outside')
        with self.assertRaises(UpdateError):
            inspect_package(self.zip)
        archive(self.source, self.zip)
        self.add_entry('OMG-Neo-v0.0.1/backend/file')
        self.add_entry('OMG-Neo-v0.0.1/backend/file/child')
        with self.assertRaises(UpdateError):
            inspect_package(self.zip)

    def test_size_and_count_limits(self):
        with patch('engine.MAX_BYTES', 1):
            with self.assertRaisesRegex(UpdateError, '体积'):
                inspect_package(self.zip)
        with patch('engine.MAX_FILES', 1):
            with self.assertRaisesRegex(UpdateError, '数量'):
                inspect_package(self.zip)

    def test_pending_transaction_blocks_new_update(self):
        self.updater.workspace.mkdir()
        work, record = self.updater._new('update')
        with self.assertRaisesRegex(UpdateError, '未完成'):
            self.updater.apply(self.zip)
        self.updater.recover(work)
        self.assertEqual(json.loads((work / 'journal.json').read_text(encoding='utf-8'))['state'], 'aborted')
        self.updater.apply(self.zip)

    def test_real_process_interruption_recovers_from_missing_target(self):
        code = '''
import os, sys
from pathlib import Path
from engine import Updater
def progress(stage, *rest):
    if stage == '替换程序': os._exit(93)
Updater(Path(sys.argv[1]), progress, process_check=lambda _: []).apply(Path(sys.argv[2]))
'''
        child = subprocess.run([sys.executable, '-c', code, str(self.target), str(self.zip)], cwd=ROOT)
        self.assertEqual(child.returncode, 93)
        self.assertFalse(self.target.exists())
        work, record = self.updater.transactions()[0]
        self.assertEqual(record['state'], 'backup_ready')
        self.updater.recover(work)
        self.assert_original()

    def test_interruption_after_new_directory_rename_is_recoverable(self):
        self.updater.workspace.mkdir()
        work, record = self.updater._new('update')
        self.target.rename(work / 'backup')
        payload(self.target)
        self.updater._save(work, record, 'backup_ready')
        self.updater.recover(work)
        self.assert_original()
        self.assertEqual((work / 'failed-install/omg_neo.exe').read_bytes(), pe(b'new'))

    def test_cannot_recover_completed_update_or_unrelated_directory(self):
        work = self.updater.apply(self.zip)
        with self.assertRaises(UpdateError):
            self.updater.recover(work)
        with self.assertRaises(UpdateError):
            self.updater.rollback(self.root)

    def test_single_updater_lock(self):
        self.updater.workspace.mkdir()
        with exclusive_lock(self.updater.workspace / '.lock'):
            with self.assertRaisesRegex(RuntimeError, '另一个更新器'):
                self.updater.apply(self.zip)
        self.assert_original()

    def test_link_in_userdata_is_rejected_without_following(self):
        outside = self.root / 'external'
        outside.mkdir()
        try:
            (self.target / 'AppData/link').symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Windows symlink privilege unavailable')
        with self.assertRaises(UpdateError):
            self.updater.apply(self.zip)
        self.assertEqual(list(outside.iterdir()), [])

    def test_github_stub_does_not_make_requests(self):
        with self.assertRaises(NotImplementedError):
            GitHubSource().check_latest('Release')
        with self.assertRaises(NotImplementedError):
            GitHubSource().fetch_release(Release('1', 'Release', 'x'), self.root)

    @unittest.skipUnless(os.name == 'nt', 'Windows process API')
    def test_process_scanner_finds_own_python(self):
        found = running_processes(Path(sys.executable).parent)
        self.assertTrue(any(f'PID {os.getpid()}' in item for item in found))


if __name__ == '__main__':
    unittest.main()
