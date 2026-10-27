"""Manual group service wired to real stdio; temporary GIMI only."""
from pathlib import Path
import tempfile
import unittest
from test_backend import Client

class BisectBridgeTest(unittest.TestCase):
    def task(self, client, method, **params):
        reply = client.call(method, **params)
        self.assertIn('result', reply, reply)
        event = client.finished(reply['result']['taskId'])
        self.assertEqual(event['state'], 'succeeded', event)
        return event['result']['bisect']

    def test_scan_split_independent_toggle_and_restore_without_game_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mods = root / 'GIMI/Mods'
            for name in ('A', 'B', 'C', 'D', 'DISABLED old'):
                p = mods / name
                p.mkdir(parents=True)
                (p / 'main.ini').write_text('[Constants]\n')
            client = Client(root / 'data', {})
            try:
                self.assertIn('result', client.call('config.patch', patch={'gimi_folder': str(mods.parent)}))
                state = self.task(client, 'bisect.scan')
                self.assertEqual(state['status'], 'ready')
                self.assertEqual(state['groupCount'], 2)
                self.assertEqual(state['stateSource'], 'resources.list')
                self.assertEqual(client.call('settings.flush')['result']['status'], 'unchanged')
                def params(**extra):
                    return dict(sessionId=state['sessionId'], generation=state['generation'], **extra)
                state = self.task(client, 'bisect.splitLeaves', **params())
                self.assertEqual(state['groupCount'], 4)
                state = self.task(client, 'bisect.toggle', **params(groupId='root.1.1', enabled=False))
                self.assertTrue((mods / 'DISABLED A/main.ini').exists())
                self.assertTrue((mods / 'B/main.ini').exists())
                self.assertTrue((mods / 'C/main.ini').exists())
                state = self.task(client, 'bisect.toggle', **params(groupId='root.2', enabled=False))
                self.assertTrue((mods / 'DISABLED C/main.ini').exists())
                self.assertTrue((mods / 'B/main.ini').exists())
                self.assertIn('二分', client.call('resources.toggle', id='fake', revision=1, enabled=False)['error']['message'])
                state = self.task(client, 'bisect.restore', **params())
                self.assertTrue(all((mods / name).exists() for name in ('A','B','C','D','DISABLED old')))
                self.assertFalse(client.call('state.get')['result']['bisectActive'])
            finally:
                client.close()
