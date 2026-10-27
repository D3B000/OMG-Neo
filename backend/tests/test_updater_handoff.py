import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from updater_handoff import UPDATER, apply_pending_updater


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pending = self.root / '.updater-pending'
        self.pending.mkdir()
        self.incoming, self.target = self.pending / UPDATER, self.root / UPDATER
        self.incoming.write_bytes(b'new updater')
        self.target.write_bytes(b'old updater')
        self.checksum = hashlib.sha256(self.incoming.read_bytes()).hexdigest()
        self.metadata = self.pending / 'manifest.json'
        self.metadata.write_text(json.dumps({'schema': 1, 'sha256': self.checksum}))

    def test_waits_for_old_exe_and_replaces_without_launching_process(self):
        replace = __import__('os').replace
        calls = []
        def busy_once(source, target):
            calls.append(source)
            if len(calls) == 1:
                raise PermissionError('old updater running')
            return replace(source, target)
        with patch('updater_handoff.os.replace', side_effect=busy_once), patch('updater_handoff.time.sleep'):
            self.assertTrue(apply_pending_updater(self.root))
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.target.read_bytes(), b'new updater')

    def test_busy_timeout_preserves_old_and_pending_files(self):
        with patch('updater_handoff.os.replace', side_effect=PermissionError()):
            self.assertFalse(apply_pending_updater(self.root, timeout=0))
        self.assertEqual(self.target.read_bytes(), b'old updater')
        self.assertTrue(self.incoming.exists())
        self.assertTrue(self.metadata.exists())

    def test_corrupt_payload_does_not_touch_old_updater(self):
        self.incoming.write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            apply_pending_updater(self.root)
        self.assertEqual(self.target.read_bytes(), b'old updater')

    def test_interrupted_after_replace_finishes_on_next_startup(self):
        self.incoming.replace(self.target)
        self.assertTrue(apply_pending_updater(self.root))
        self.assertIn(self.checksum, (self.root / (UPDATER + '.sha256')).read_text())
        self.assertFalse(apply_pending_updater(self.root))
