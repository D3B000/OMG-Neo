"""Manual recursive groups and Windows rename safety; temporary fixtures only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND), str(BACKEND.parent / 'OMGLite' / 'src')]
from bisect_service import BisectService
from bisect_fs import rename_exact


class BisectTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.mods = self.base / 'GIMI' / 'Mods'
        self.mods.mkdir(parents=True)
        self.config = SimpleNamespace(settings={}, get_gimi_dir=lambda: str(self.mods.parent))
        self.game_check = lambda _: self.fail('group control must not check game state')
        self.service = BisectService(self.base / 'data', self.config, self.game_check)
        self.addCleanup(self.service.close)
        for name in 'ABCDEFGH':
            self.mod(name)

    def mod(self, name, parent=None):
        folder = (parent or self.mods) / name
        folder.mkdir(parents=True)
        (folder / 'main.ini').write_text('[Constants]\nglobal $x=1\n')
        (folder / 'extra.ini').write_text('[KeyTest]\nkey=X\n')
        return folder

    def params(self, **extra):
        s = self.service.session
        return {'sessionId': s['sessionId'], 'generation': s['generation'], **extra}

    def scan(self):
        state = self.service.scan({})
        self.assertEqual(state['errors'], [])
        return state

    def toggle(self, group, enabled):
        return self.service.toggle(self.params(groupId=group, enabled=enabled))

    def node(self, group):
        return next(n for n in self.service.state()['nodes'] if n['id'] == group)

    def test_snapshot_immediately_creates_two_groups_without_changing_files(self):
        off = self.mod('DISABLED old')
        s = self.scan()
        self.assertEqual(s['mode'], 'manual')
        self.assertEqual(s['status'], 'ready')
        self.assertEqual([n['label'] for n in s['nodes']], ['已记录模组', 'A', 'B'])
        self.assertEqual([self.node(g)['count'] for g in ('root.1', 'root.2')], [4, 4])
        self.assertTrue(all((self.mods / n).exists() for n in 'ABCDEFGH'))
        self.assertTrue(off.exists())
        self.assertEqual(len(s['inis']), 16)
        self.assertFalse(s.get('transactions'))

    def test_both_groups_can_be_independently_enabled_or_disabled(self):
        self.scan()
        self.toggle('root.1', False)
        self.assertEqual(self.node('root.1')['state'], 'disabled')
        self.assertEqual(self.node('root.2')['state'], 'enabled')
        self.toggle('root.2', False)
        self.assertEqual(self.node('root')['state'], 'disabled')
        self.toggle('root.1', True)
        self.assertEqual(self.node('root.1')['state'], 'enabled')
        self.assertEqual(self.node('root.2')['state'], 'disabled')
        self.assertEqual(self.node('root')['state'], 'mixed')

    def test_selected_directory_is_session_local_and_survives_recovery(self):
        alternate = self.base / 'Alternative mods'
        alternate.mkdir()
        self.mod('Custom A', alternate)
        self.mod('Custom B', alternate)
        state = self.service.scan({'root': str(alternate)})
        self.assertEqual(state['errors'], [])
        self.assertEqual(len(state['units']), 2)
        self.assertEqual(self.config.get_gimi_dir(), str(self.mods.parent))
        self.toggle('root.1', False)
        with self.assertRaises(ValueError):
            self.service.scan({'root': str(self.mods)})
        self.service.close()
        self.service = BisectService(self.base / 'data', self.config)
        self.addCleanup(self.service.close)
        self.service.restore(self.params())
        self.assertTrue((alternate / 'Custom A').is_dir())
        self.assertTrue((alternate / 'Custom B').is_dir())
        self.assertTrue(all((self.mods / n).is_dir() for n in 'ABCDEFGH'))

    def test_scan_reports_indeterminate_progress_until_snapshot_is_complete(self):
        events = []
        worker = SimpleNamespace(cancel=SimpleNamespace(is_set=lambda: False),
                                 progress=SimpleNamespace(emit=events.append))
        self.service.scan({}, worker)
        self.assertIsNone(events[0]['progress'])
        self.assertEqual(events[-1]['progress'], 1.)
        self.assertTrue(all(e['progress'] is None for e in events[:-1]))

    def test_toggle_reports_verified_entry_progress(self):
        self.scan()
        events = []
        worker = SimpleNamespace(cancel=SimpleNamespace(is_set=lambda: False),
                                 progress=SimpleNamespace(emit=events.append))
        self.service.toggle(self.params(groupId='root.1', enabled=False), worker)
        self.assertIsNone(events[0]['progress'])
        values = [e['progress'] for e in events[1:]]
        self.assertEqual(len(values), 5)  # Four renamed entries, then final verification.
        self.assertEqual(values, sorted(values))
        self.assertEqual(values[-1], 1.)
        self.assertEqual(self.node('root.2')['state'], 'enabled')

    def test_two_groups_split_into_four_then_eight_without_any_enable_changes(self):
        self.scan()
        self.toggle('root.1', False)
        self.service.split(self.params(groupId='root.1'))
        self.service.split(self.params(groupId='root.2'))
        self.assertEqual(self.service.state()['groupCount'], 4)
        for g in ('root.1.1', 'root.1.2'):
            self.assertEqual(self.node(g)['state'], 'disabled')
        for g in ('root.2.1', 'root.2.2'):
            self.assertEqual(self.node(g)['state'], 'enabled')
        self.service.split_leaves(self.params())
        self.assertEqual(self.service.state()['groupCount'], 8)
        ids = [u for n in self.service.state()['nodes'] if not n['children'] for u in n['unitIds']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 8)
        self.assertEqual(len(self.service.session['history']), 1)

    def test_enabling_child_of_disabled_parent_produces_mixed_parent_and_leaves_sibling_alone(self):
        self.scan()
        self.service.split(self.params(groupId='root.1'))
        self.toggle('root.1', False)
        self.toggle('root.1.1', True)
        self.assertEqual(self.node('root.1')['state'], 'mixed')
        self.assertEqual(self.node('root.1.1')['state'], 'enabled')
        self.assertEqual(self.node('root.1.2')['state'], 'disabled')
        self.assertEqual(self.node('root.2')['state'], 'enabled')
        self.toggle('root.1', True)
        self.assertEqual(self.node('root.1.2')['state'], 'enabled')

    def test_single_mod_leaf_cannot_split_and_does_not_create_empty_group(self):
        self.scan()
        self.service.split_leaves(self.params())
        self.service.split_leaves(self.params())
        with self.assertRaisesRegex(ValueError, '不足两个'):
            self.service.split(self.params(groupId='root.1.1.1'))
        self.assertEqual(self.service.state()['groupCount'], 8)

    def test_game_and_ini_changes_do_not_require_reload_or_result_confirmation(self):
        self.scan()
        (self.mods.parent / 'd3dx_user.ini').write_text('changed while game is running')
        (self.mods / 'A' / 'main.ini').write_text('external content edit')
        self.toggle('root.1', False)
        self.toggle('root.1', True)
        self.assertEqual((self.mods / 'A' / 'main.ini').read_text(), 'external content edit')
        for action in ('begin', 'apply', 'result', 'confirmReload'):
            with self.assertRaisesRegex(ValueError, '未知分组操作'):
                self.service.dispatch(action, self.params())

    def test_initial_disabled_mods_never_enabled_even_by_root_action(self):
        off = self.mod('DISABLED old')
        self.scan()
        self.toggle('root', False)
        self.toggle('root', True)
        self.service.restore(self.params())
        self.assertTrue(off.exists())
        self.assertFalse((self.mods / 'old').exists())

    def test_resource_browser_status_is_the_snapshot_source(self):
        (self.mods / 'A' / 'DISABLED spare.ini').write_text('[Constants]')
        s = self.scan()
        self.assertTrue(next(i for i in s['resourceSnapshot'] if i['name'] == 'A')['enabled'])
        ini = next(i for i in s['inis'] if i['name'] == 'DISABLED spare.ini')
        self.assertTrue(ini['initialEnabled'])
        self.assertEqual(ini['stateSource'], 'resources.list')

    def test_undo_restores_only_last_toggle_and_preserves_splits(self):
        self.scan()
        self.toggle('root.1', False)
        self.service.split(self.params(groupId='root.1'))
        self.toggle('root.1.1', True)
        self.service.undo(self.params())
        self.assertEqual(self.node('root.1.1')['state'], 'disabled')
        self.assertEqual(self.service.state()['groupCount'], 3)
        self.assertTrue(self.service.session['history'][1]['undone'])
        self.assertTrue(self.service.session['inis'][0]['operations'])

    def test_restart_can_resume_preserving_tree_and_enable_state(self):
        self.scan()
        self.service.split_leaves(self.params())
        self.toggle('root.1.1', False)
        self.service.close()
        fresh = BisectService(self.base / 'data', self.config)
        self.addCleanup(fresh.close)
        self.assertEqual(fresh.state()['status'], 'recovery')
        state = fresh.resume({'sessionId': fresh.session['sessionId'], 'generation': fresh.session['generation']})
        self.assertEqual(state['groupCount'], 4)
        self.assertEqual(next(n for n in state['nodes'] if n['id'] == 'root.1.1')['state'], 'disabled')

    def test_finish_keeps_current_state_and_exports_snapshot_tree_and_operations(self):
        self.scan()
        self.toggle('root.1', False)
        self.service.finish(self.params())
        self.assertFalse(self.service.active)
        self.assertTrue((self.mods / 'DISABLED A').exists())
        report = json.loads((self.base / 'data/mod-bisect/report.json').read_text('utf-8'))
        self.assertEqual(len(report['nodes']), 3)
        self.assertEqual(report['history'][0]['type'], 'disable')

    def test_restore_collision_preserves_both_copies(self):
        self.scan()
        self.toggle('root.1', False)
        self.mod('A')
        with self.assertRaisesRegex(ValueError, '同时存在'):
            self.service.restore(self.params())
        self.assertTrue((self.mods / 'DISABLED A/main.ini').exists())
        self.assertTrue((self.mods / 'A/main.ini').exists())
        self.assertTrue(self.service.active)

    def test_failure_after_successful_rename_rolls_back_current_entry_too(self):
        self.scan()
        count = [0]
        def fail_after_second(source, target, validate):
            count[0] += 1
            rename_exact(source, target, validate)
            if count[0] == 2:
                raise OSError('after rename')
        with patch('bisect_service.rename_exact', side_effect=fail_after_second):
            with self.assertRaisesRegex(ValueError, 'after rename'):
                self.toggle('root.1', False)
        self.assertTrue(all((self.mods / n).exists() for n in 'ABCDEFGH'))
        self.assertEqual(self.service.session['status'], 'recovery')

    def test_log_write_failure_prevents_rename(self):
        self.scan()
        with patch('bisect_service.atomic', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                self.toggle('root.1', False)
        self.assertTrue(all((self.mods / n).exists() for n in 'ABCDEFGH'))

    def test_tampered_journal_is_read_only(self):
        self.scan()
        self.service.close()
        value = json.loads(self.service.path.read_text('utf-8'))
        value['payload'] = value['payload'].replace('manual', 'tampered')
        self.service.path.write_text(json.dumps(value), encoding='utf-8')
        fresh = BisectService(self.base / 'data', self.config)
        self.assertEqual(fresh.state()['status'], 'blocked')
        with self.assertRaises(ValueError):
            fresh.restore({})

    def test_cross_instance_lock_and_stale_requests_are_rejected(self):
        self.scan()
        old = self.params(groupId='root.1', enabled=False)
        self.service.toggle(old)
        with self.assertRaisesRegex(ValueError, '会话已变化'):
            self.service.toggle(old)
        other = BisectService(self.base / 'other-data', self.config)
        self.addCleanup(other.close)
        with self.assertRaisesRegex(ValueError, '另一个'):
            other.scan({})

    def test_unicode_original_names_restore_exactly(self):
        name = '测试角色_🌿_Original'
        self.mod(name)
        self.scan()
        self.toggle('root', False)
        self.service.restore(self.params())
        self.assertTrue((self.mods / name / 'main.ini').exists())

    @unittest.skipUnless(os.name == 'nt', 'real Windows junction fixture')
    def test_hub_junction_aliases_share_one_entry_and_restore_target_child(self):
        library = self.base / 'Library'
        self.mod('Outside', library)
        for name in ('Hub', 'HubAlias'):
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(self.mods / name), str(library)], check=True, capture_output=True)
            self.addCleanup(lambda p=self.mods / name: os.rmdir(p) if os.path.lexists(p) else None)
        s = self.scan()
        unit = next(u for u in s['units'] if u['name'] == 'Outside')
        e = next(e for e in s['entries'] if e['unitId'] == unit['id'])
        self.assertEqual(len(e['aliases']), 2)
        self.toggle('root', False)
        self.assertTrue((library / 'DISABLED Outside').exists())
        self.assertTrue((self.mods / 'Hub').exists())
        self.service.restore(self.params())
        self.assertTrue((library / 'Outside').exists())

    @unittest.skipUnless(os.name == 'nt', 'real Windows junction fixture')
    def test_junction_target_replacement_blocks_rename(self):
        library, replacement = self.base / 'Library', self.base / 'Other'
        self.mod('Outside', library)
        self.mod('Outside', replacement)
        hub = self.mods / 'Hub'
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(hub), str(library)], check=True, capture_output=True)
        self.addCleanup(lambda: os.rmdir(hub) if os.path.lexists(hub) else None)
        self.scan()
        os.rmdir(hub)
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(hub), str(replacement)], check=True, capture_output=True)
        with self.assertRaises((ValueError, OSError)):
            self.toggle('root', False)
        self.assertTrue((replacement / 'Outside/main.ini').exists())
        self.assertTrue((library / 'Outside/main.ini').exists())

if __name__ == '__main__':
    unittest.main()
