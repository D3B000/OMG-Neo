"""Completion enrichment failures must not lose the task or block shutdown."""
import sys
import unittest
from test_backend import BACKEND

sys.path.insert(0, str(BACKEND / 'validation'))
from probe_completion_failure import probe


class CompletionCleanupTests(unittest.TestCase):
    def test_build_state_failure_releases_busy_state_and_reports_completion(self):
        result = probe()
        self.assertTrue(result['taskAccepted'])
        self.assertTrue(result['exceptionObserved'])
        self.assertTrue(result['completionReceived'])
        self.assertIsNone(result['activeTaskAfterFault'])
        self.assertTrue(result['shutdownExitedWithin2Seconds'])

    def test_snapshot_failure_still_reports_completion_and_allows_shutdown(self):
        result = probe('snapshot')
        self.assertTrue(result['taskAccepted'])
        self.assertTrue(result['exceptionObserved'])
        self.assertFalse(result['snapshotAvailable'])
        self.assertTrue(result['completionReceived'])
        self.assertTrue(result['shutdownExitedWithin2Seconds'])
