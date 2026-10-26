import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server_switch import ServerSwitchService, read_ini
from settings_store import SettingsStore

class SwitchTests(unittest.TestCase):
    def test_open_directory_creates_managed_root_without_game_operations(self):
        service = ServerSwitchService(self.root / 'fresh-data', self.config,
                                      lambda _: self.fail('must not inspect game'))
        with patch('subprocess.Popen') as popen:
            service.open_directory()
        self.assertTrue(service.root.is_dir())
        popen.assert_called_once_with(['explorer.exe', str(service.root)])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / 'game'
        self.game.mkdir()
        self.data = self.root / 'AppData'
        self.config = SettingsStore(self.data)
        self.config.commit({'game_folder': str(self.game)})
        self.service = ServerSwitchService(self.data, self.config, lambda _: None)
        self.write('config.ini', '[general]\ncps=mihoyo\nchannel=1\nsub_channel=1\ngame_version=7.0.0\ncustom=keep\n')
        self.write('YuanShen.exe', 'old-exe')
        self.write('YuanShen_Data/StreamingAssets/large.blk', 'shared')
        self.worker = SimpleNamespace(cancel=threading.Event(), progress=SimpleNamespace(emit=lambda _: None))
        bp = self.service.root / 'bilibili'
        (bp / 'BLPlatform64').mkdir(parents=True)
        (bp / 'manifest.json').write_text(json.dumps({'game_version': '7.0.0'}))
        (bp / 'PCGameSDK.dll').write_text('sdk')
        (bp / 'BLPlatform64/PCGamePlatform.exe').write_text('login')
        for channel, data, exe in [('cn','YuanShen_Data','YuanShen.exe'), ('global','GenshinImpact_Data','GenshinImpact.exe')]:
            package = self.service.root / channel
            for rel in [exe,'mhypbase.dll','pkg_version',f'{data}/app.info',f'{data}/globalgamemanagers',
                        f'{data}/globalgamemanagers.assets',f'{data}/globalgamemanagers.assets.resS',
                        f'{data}/Native/Data/Metadata/global-metadata.dat',f'{data}/Native/Data/Metadata/startup-metadata.dat']:
                file = package / rel
                file.parent.mkdir(parents=True,exist_ok=True)
                file.write_text('new-'+channel)
            (package / 'manifest.json').write_text(json.dumps({'game_version':'7.0.0'}))

    def write(self, name, content):
        dest = self.game / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)

    def snapshot(self):
        return {p.relative_to(self.game).as_posix(): p.read_bytes() for p in self.game.rglob('*') if p.is_file()}

    def test_channels_and_shared_data(self):
        self.service.apply('bilibili',self.worker)
        self.assertEqual(self.service.status()['current'], 'bilibili')
        self.assertTrue((self.game/'YuanShen_Data/Plugins/BLPlatform64/PCGamePlatform.exe').exists())
        self.service.apply('cn',self.worker)
        self.assertFalse((self.game/'YuanShen_Data/Plugins/PCGameSDK.dll').exists())
        self.service.apply('bilibili',self.worker)
        self.service.apply('global',self.worker)
        self.assertEqual(self.service.status()['current'], 'global')
        self.assertEqual((self.game/'GenshinImpact_Data/StreamingAssets/large.blk').read_text(),'shared')
        self.assertFalse((self.game/'GenshinImpact_Data/Plugins/PCGameSDK.dll').exists())
        self.assertFalse((self.game/'YuanShen.exe').exists())
        self.service.apply('cn',self.worker)
        self.assertEqual(self.service.status()['current'],'cn')
        self.assertEqual(read_ini(self.game/'config.ini').get('general','custom'),'keep')

    def test_rollback_on_copy_failure(self):
        before = self.snapshot()
        import shutil
        original = shutil.copy2
        failed = False
        def copy(src,dest,*args,**kwargs):
            nonlocal failed
            if 'global' in Path(src).parts and Path(dest).is_relative_to(self.game) and not failed:
                failed = True
                Path(dest).write_text('partial')
                raise OSError('simulated disk error')
            return original(src,dest,*args,**kwargs)
        with patch('server_switch.shutil.copy2',side_effect=copy):
            with self.assertRaisesRegex(RuntimeError,'已回滚'):
                self.service.apply('global',self.worker)
        self.assertEqual(self.snapshot(),before)
        self.assertFalse((self.service.root/'pending.json').exists())

    def test_version_and_process_guards(self):
        before = self.snapshot()
        (self.service.root/'global/manifest.json').write_text('{"game_version":"0"}')
        with self.assertRaisesRegex(ValueError,'版本'):
            self.service.apply('global',self.worker)
        self.service.game_stopped = lambda _: (_ for _ in ()).throw(ValueError('running'))
        with self.assertRaisesRegex(ValueError,'running'):
            self.service.apply('bilibili',self.worker)
        self.assertEqual(self.snapshot(),before)

    def native_package(self, wrapper='替换包'):
        base = self.service.root / wrapper if wrapper else self.service.root
        base.mkdir(parents=True, exist_ok=True)
        for source, name in [('cn', '原神米哈游官服'), ('global', '原神国际服')]:
            (self.service.root / source).rename(base / name)
            (base / name / 'manifest.json').unlink()
            (base / name / 'config.ini').write_text('[general]\ngame_version=old\n')
        bpack = self.service.root / 'bilibili'
        (bpack / 'PCGameSDK.dll').rename(base / 'PCGameSDK.dll')
        (base / '原神B服新登录框窗口').mkdir()
        (bpack / 'BLPlatform64').rename(base / '原神B服新登录框窗口/BLPlatform64')
        (base / '版本号.ini').write_bytes('[配置]\n国服版本=7.0.0\n外服版本=7.0.0\n'.encode('gb18030'))
        return base

    def test_original_backup_layout_roundtrip(self):
        self.native_package()
        self.service.apply('global', self.worker)
        self.assertEqual(self.service.status()['current'], 'global')
        self.assertEqual(self.service.status()['version'], '7.0.0')
        self.service.apply('bilibili', self.worker)
        self.assertEqual(self.service.status()['current'], 'bilibili')
        self.assertTrue((self.game / 'YuanShen_Data/Plugins/BLPlatform64/PCGamePlatform.exe').is_file())
        self.service.apply('cn', self.worker)
        self.assertFalse((self.game / 'YuanShen_Data/Plugins/PCGameSDK.dll').exists())

    def test_original_layout_locations_and_versions(self):
        base = self.native_package('原神资源替换包')
        self.assertTrue(self.service.preview('global')['copy'])
        import shutil
        for child in list(base.iterdir()):
            shutil.move(str(child), str(self.service.root / child.name))
        base.rmdir()
        self.assertTrue(self.service.preview('global')['copy'])
        before = self.snapshot()
        (self.service.root / '版本号.ini').write_text('[配置]\n国服版本=7.0.0\n外服版本=6.0.0\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '版本不一致'):
            self.service.apply('global', self.worker)
        self.assertEqual(before, self.snapshot())

    def test_general_case_and_shared_resource_link(self):
        self.native_package()
        self.write('config.ini','[General]\ncps=mihoyo\ngame_version=7.0.0\nchannel=1\n')
        shared = self.root / 'shared'
        shared.mkdir()
        link = self.game / 'YuanShen_Data/StreamingAssets/AssetBundles'
        try:
            link.symlink_to(shared, target_is_directory=True)
        except OSError:
            self.skipTest('symlinks unavailable')
        self.assertTrue(self.service.preview('global')['copy'])
        self.service.apply('global', self.worker)
        self.assertTrue((self.game/'GenshinImpact_Data/StreamingAssets/AssetBundles').is_symlink())
        self.assertTrue(shared.is_dir())
        self.assertEqual(self.service.status()['current'], 'global')

    def test_touched_game_link_rejected(self):
        self.native_package()
        linked = self.game/'YuanShen_Data/Native'
        target = self.root/'native-target'
        target.mkdir()
        try:
            linked.symlink_to(target,target_is_directory=True)
        except OSError:
            self.skipTest('symlinks unavailable')
        with self.assertRaises(ValueError):
            self.service.preview('global')

    def test_switch_without_config_uses_embedded_version_and_creates_config(self):
        import struct
        base = self.native_package()
        raw = b'7.1.0_48052158_48145775'
        marker = b'header' + struct.pack('<I', len(raw)) + raw + b'\x00'
        for path in [self.game/'YuanShen_Data/globalgamemanagers',
                     base/'原神米哈游官服/YuanShen_Data/globalgamemanagers',
                     base/'原神国际服/GenshinImpact_Data/globalgamemanagers']:
            path.write_bytes(marker)
        (self.game/'config.ini').unlink()
        result = self.service.preview('global')
        self.assertEqual(result['current'], 'cn')
        self.assertEqual(result['version'], '7.1.0')
        self.service.apply('global', self.worker)
        ini = read_ini(self.game/'config.ini')
        self.assertEqual(ini.get('general','game_version'), '7.1.0')
        self.assertEqual(ini.get('general','cps'), 'hoyoverse_PC')

    def test_symlink_package_rejected(self):
        source = self.service.root/'bilibili/PCGameSDK.dll'
        source.unlink()
        try:
            source.symlink_to(self.game/'YuanShen.exe')
        except OSError:
            self.skipTest('symlinks unavailable')
        with self.assertRaises(ValueError):
            self.service.preview('bilibili')

if __name__ == '__main__':
    unittest.main()
