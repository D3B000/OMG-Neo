from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server_import import import_package
from server_backup import export
from server_switch import read_ini
import test_server_switch as switch_fixtures
import test_server_backup as backup_fixtures


class ImportTests(unittest.TestCase):
    setUp = switch_fixtures.SwitchTests.setUp
    write = switch_fixtures.SwitchTests.write
    snapshot = switch_fixtures.SwitchTests.snapshot
    prepare = backup_fixtures.BackupTests.prepare

    def package(self):
        params = self.prepare()
        export(params, self.config, self.service.root, lambda _: None, self.worker)
        return Path(params['destination'])

    def run_import(self, source):
        return import_package({'source': str(source)}, self.service, self.worker)

    def files(self, path):
        return {str(f.relative_to(path)): f.read_bytes()
                for f in path.rglob('*') if f.is_file() and '.history' not in f.parts}

    def test_native_selection_preserves_source_game_and_ignores_extra_assets(self):
        source = self.package()
        (source / 'unrelated.exe').write_bytes(b'ignore')
        nested = source / '原神米哈游官服/YuanShen_Data/StreamingAssets/nested/large.blk'
        nested.parent.mkdir(parents=True)
        nested.write_bytes(b'ignore')
        before_source, before_game = self.files(source), self.snapshot()
        events = []
        self.worker.progress.emit = events.append
        result = self.run_import(source)
        target = Path(result['path'])
        self.assertEqual(target, self.service.root / '替换包')
        self.assertTrue((target / '原神米哈游官服/YuanShen.exe').is_file())
        self.assertFalse((target / 'unrelated.exe').exists())
        self.assertFalse((target / nested.relative_to(source)).exists())
        self.assertEqual(read_ini(target / '版本号.ini')['配置']['国服版本'], '7.0.0')
        self.assertEqual(self.files(source), before_source)
        self.assertEqual(self.snapshot(), before_game)
        self.assertEqual(events[0]['message'], '识别中…')
        self.assertEqual(events[-1]['progress'], 1)
        self.assertTrue(self.service.preview('global')['copy'])
        self.assertTrue(self.service.preview('bilibili')['copy'])

    def test_legacy_wrapper_is_normalized(self):
        source = self.root / 'download/extracted'
        source.mkdir(parents=True)
        shutil.copytree(self.service.root / 'cn', source / 'cn')
        self.run_import(source.parent)
        self.assertTrue((self.service.root / '替换包/原神米哈游官服/YuanShen.exe').is_file())

    def test_merge_other_channel_and_recoverable_history(self):
        source = self.package()
        target = Path(self.run_import(source)['path'])
        old = (target / '原神米哈游官服/YuanShen.exe').read_bytes()
        (target / '原神国际服').mkdir(exist_ok=True)
        (target / '原神国际服/keep').write_text('other channel')
        ini = read_ini(target / '版本号.ini')
        ini['配置']['外服版本'] = '7.2.0'
        with (target / '版本号.ini').open('w', encoding='utf-8') as stream:
            ini.write(stream)
        (source / '原神米哈游官服/YuanShen.exe').write_bytes(b'updated')
        self.run_import(source)
        self.assertEqual((target / '原神米哈游官服/YuanShen.exe').read_bytes(), b'updated')
        self.assertEqual((target / '原神国际服/keep').read_text(), 'other channel')
        self.assertEqual(read_ini(target / '版本号.ini')['配置']['外服版本'], '7.2.0')
        self.assertTrue(any(f.read_bytes() == old for f in (target / '.history').rglob('YuanShen.exe')))

    def test_default_backup_folder_can_be_imported(self):
        params = self.prepare()
        params.pop('destination')
        source = export(params, self.config, self.service.root, lambda _: None, self.worker)['path']
        self.run_import(source)
        self.assertTrue((self.service.root / '替换包/版本号.ini').is_file())

    def test_invalid_incomplete_and_ambiguous_folders_do_not_publish(self):
        empty = self.root / 'empty'
        empty.mkdir()
        with self.assertRaisesRegex(ValueError, '不是一个替换包'):
            self.run_import(empty)
        source = self.package()
        (source / '原神米哈游官服/mhypbase.dll').unlink()
        with self.assertRaisesRegex(ValueError, '不完整|缺少'):
            self.run_import(source)
        self.assertFalse((self.service.root / '替换包').exists())

    def test_copy_failure_and_publish_failure_restore_old_files(self):
        source = self.package()
        target = Path(self.run_import(source)['path'])
        before = self.files(target)
        with patch('server_import.shutil.copystat', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                self.run_import(source)
        original = Path.rename
        def fail_metadata(path, destination):
            if path.name == '版本号.ini' and path.parent.name.startswith('.server-import-'):
                raise PermissionError('occupied')
            return original(path, destination)
        with patch.object(Path, 'rename', fail_metadata):
            with self.assertRaises(PermissionError):
                self.run_import(source)
        self.assertEqual(self.files(target), before)
        self.assertEqual(list(self.service.root.glob('.server-import-*')), [])

    def test_mismatched_version_and_multiple_packages_rejected(self):
        import struct
        source = self.package()
        marker = b'7.2.0_48052158_48145775'
        (source / '原神米哈游官服/YuanShen_Data/globalgamemanagers').write_bytes(
            struct.pack('<I', len(marker)) + marker)
        with self.assertRaisesRegex(ValueError, '声明与文件不一致'):
            self.run_import(source)
        wrapper = self.root / 'multiple'
        shutil.copytree(source, wrapper / 'a')
        shutil.copytree(source, wrapper / 'b')
        with self.assertRaisesRegex(ValueError, '多个替换包'):
            self.run_import(wrapper)
        self.assertFalse((self.service.root / '替换包').exists())

    def test_cancel_during_copy_never_publishes(self):
        source = self.package()
        def cancel(event):
            if event['message'].startswith('正在导入'):
                self.worker.cancel.set()
        self.worker.progress.emit = cancel
        with self.assertRaisesRegex(ValueError, '取消'):
            self.run_import(source)
        self.assertFalse((self.service.root / '替换包').exists())
        self.assertEqual(list(self.service.root.glob('.server-import-*')), [])

    def test_game_self_import_and_pending_switch_rejected(self):
        with self.assertRaisesRegex(ValueError, '游戏目录'):
            self.run_import(self.game)
        source = self.package()
        self.run_import(source)
        with self.assertRaisesRegex(ValueError, '自身'):
            self.run_import(self.service.root / '替换包')
        (self.service.root / 'pending.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, '恢复'):
            self.run_import(source)

    def test_symbolic_source_is_rejected(self):
        source = self.package()
        link = self.root / 'linked'
        try:
            link.symlink_to(source, target_is_directory=True)
        except OSError:
            self.skipTest('symlink privilege unavailable')
        with self.assertRaisesRegex(ValueError, '链接'):
            self.run_import(link)

    def test_stdio_import_without_configured_game(self):
        from test_backend import Client
        source = self.package()
        client = Client(self.root / 'import-protocol')
        try:
            accepted = client.call('serverSwitch.import', source=str(source))
            finished = client.finished(accepted['result']['taskId'])
            self.assertEqual(finished['state'], 'succeeded', finished)
            self.assertTrue((Path(finished['result']['path']) / '版本号.ini').is_file())
            bad = client.call('serverSwitch.import', source=str(self.root / 'missing'))
            failed = client.finished(bad['result']['taskId'])
            self.assertEqual(failed['state'], 'failed')
            self.assertIn('不是一个替换包', failed['message'])
        finally:
            client.close()
