import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cache_service import CacheService
from settings_store import SettingsStore
from test_backend import Client


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = CacheService(self.root)

    def file(self, name, stamp=100):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'123')
        os.utime(path, (stamp, stamp))
        # Directory creation time must not mask fixture generation ordering.
        for parent in path.parents:
            if parent == self.root:
                break
            os.utime(parent, (stamp, stamp))
        return path

    def test_keep_latest_generation_per_category(self):
        for group in ('cache', 'resource-backups', 'dll-backups',
                      'server-switch/backups', 'server-switch/备份包/.history',
                      'build-work/temp', 'temp'):
            old = 'injection-old' if group == 'temp' else 'old'
            new = 'injection-new' if group == 'temp' else 'new'
            self.file(f'{group}/{old}/file', 100)
            self.file(f'{group}/{new}/file', 200)
        self.assertEqual(self.service.run()['bytes'], 42)
        result = self.service.run(clear=True, keep_latest=True)
        self.assertEqual(result['bytes'], 21)
        self.assertEqual(result['clearedBytes'], 21)
        self.assertFalse((self.root / 'resource-backups/old').exists())
        self.assertTrue((self.root / 'resource-backups/new/file').exists())

    def test_manual_clear_preserves_owned_outputs_and_pending_recovery(self):
        protected = [self.file(p) for p in ('config.json', 'config.json.bak',
            'build-work/output/d3d11.dll', 'server-switch/备份包/UnityPlayer.dll',
            'server-switch/pending.json', 'server-switch/backups/old/file',
            'temp/_MEI123/runtime.dll', 'temp/unknown.txt')]
        self.file('cache/a')
        self.file('resource-backups/old/file')
        self.file('update-abcd/gimi.zip')
        self.assertEqual(self.service.run(clear=True)['bytes'], 0)
        self.assertTrue(all(p.exists() for p in protected))

    def test_progress_and_failed_deletion_report_actual_remaining_size(self):
        from unittest.mock import patch
        self.file('cache/old')
        events = []
        with patch.object(Path, 'unlink', side_effect=PermissionError('locked')):
            result = self.service.run(clear=True, progress=events.append)
        self.assertEqual(result['bytes'], 3)
        self.assertEqual(result['clearedBytes'], 0)
        self.assertTrue(result['errors'])
        self.assertIsNone(events[0]['progress'])
        self.assertEqual(events[-1]['progress'], 1.)

    def test_audited_import_history_temp_logs_and_atomic_leftovers(self):
        import logging
        histories = [self.file(f'server-switch/{base}.history/{generation}/file', stamp)
            for base in ('替换包/', '原神资源替换包/', '')
            for generation, stamp in (('old', 100), ('new', 200))]
        for name in ('temp/omg_gimi_rollback_old/file',
                     'temp/omg_gimi_latest.zip', 'resource-cards.tmp',
                     'server-switch/.server-import-' + 'a' * 32 + '/file',
                     'server-switch/备份包/.server-backup-' + 'b' * 32 + '/file',
                     'log/omg_old.log', 'log/injector-old.log'):
            self.file(name)
        protected = [self.file(p) for p in (
            'server-switch/替换包/版本号.ini', 'logs/exported.txt',
            'log/injection-lifecycle.jsonl', 'temp/_MEI1/runtime.dll')]
        active = self.file('log/omg_active.log')
        logger = logging.getLogger('cache-test-active-log')
        handler = logging.FileHandler(active)
        logger.addHandler(handler)
        try:
            result = self.service.run(clear=True)
            self.assertEqual(result['bytes'], 0)
            self.assertFalse(any(p.exists() for p in histories))
            self.assertTrue(all(p.exists() for p in [active, *protected]))
        finally:
            logger.removeHandler(handler)
            handler.close()

    def test_link_rejected_before_any_deletion(self):
        keep = self.file('cache/first')
        target = self.file('outside/important')
        link = self.root / 'resource-backups/link'
        link.parent.mkdir()
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest('Symlink privilege unavailable')
        with self.assertRaises(ValueError):
            self.service.run(clear=True)
        self.assertTrue(keep.exists())
        self.assertTrue(target.exists())

    def test_shutdown_setting_persisted_and_applied(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                store = SettingsStore(self.root)
                store.commit({'cleanup_on_exit': enabled})
                self.assertEqual(SettingsStore(self.root).get('cleanup_on_exit'), enabled)
                self.file('cache/old', 100)
                self.file('cache/new', 200)
                client = Client(self.root)
                try:
                    self.assertIn('result', client.call('hello'))
                finally:
                    client.close()
                self.assertEqual((self.root / 'cache/old').exists(), not enabled)
                self.assertTrue((self.root / 'cache/new').exists())


if __name__ == '__main__':
    unittest.main()
