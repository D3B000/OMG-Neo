import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_server_switch as fixtures
from server_backup import export, preview
from server_switch import read_ini

class BackupTests(unittest.TestCase):
    setUp = fixtures.SwitchTests.setUp
    write = fixtures.SwitchTests.write
    snapshot = fixtures.SwitchTests.snapshot

    def prepare(self, channel='cn'):
        package = self.service.root / channel
        for file in package.rglob('*'):
            if file.is_file() and file.name != 'manifest.json':
                dest = self.game / file.relative_to(package)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, dest)
        if channel == 'global':
            self.write('config.ini','[general]\ncps=hoyoverse_PC\ngame_version=7.0.0\n')
            shutil.rmtree(self.game / 'YuanShen_Data')
        return {'source': str(self.game), 'destination': str(self.root / 'exports'), 'channel': channel}

    def test_precise_file_selection_and_no_game_writes(self):
        params = self.prepare()
        self.write('YuanShen_Data/StreamingAssets/root.blk','root')
        self.write('YuanShen_Data/StreamingAssets/sub/huge.blk','exclude')
        self.write('YuanShen_Data/Plugins/unrelated.dll','exclude')
        self.write('YuanShen_Data/Plugins/PCGameSDK.dll','sdk')
        self.write('YuanShen_Data/Plugins/BLPlatform64/PCGamePlatform.exe','login')
        before = self.snapshot()
        result = export(params,self.config,self.service.root,lambda _: None,self.worker)
        folder = Path(result['path'])
        self.assertTrue((folder/'原神米哈游官服/YuanShen_Data/StreamingAssets/root.blk').exists())
        self.assertFalse((folder/'原神米哈游官服/YuanShen_Data/StreamingAssets/sub/huge.blk').exists())
        self.assertFalse((folder/'原神米哈游官服/YuanShen_Data/Plugins/unrelated.dll').exists())
        self.assertTrue((folder/'PCGameSDK.dll').exists())
        self.assertTrue((folder/'原神B服新登录框窗口/BLPlatform64/PCGamePlatform.exe').exists())
        self.assertEqual(read_ini(folder/'版本号.ini').get('配置','国服版本'),'7.0.0')
        self.assertEqual(before,self.snapshot())
        report = json.loads((folder/'backup-report.json').read_text(encoding='utf-8'))
        self.assertIn('UnityPlayer.dll',report['missingOptional'])
        self.assertEqual(len(report['files']),result['count'])

    def test_global_export_can_be_used_by_switcher(self):
        params = self.prepare('global')
        result = export(params,self.config,self.service.root,lambda _: None,self.worker)
        folder = Path(result['path'])
        self.assertTrue((folder/'原神国际服/GenshinImpact.exe').exists())
        self.assertEqual(read_ini(folder/'版本号.ini').get('配置','外服版本'),'7.0.0')
        imported = self.service.root/'替换包'
        shutil.copytree(folder,imported)
        ini=read_ini(imported/'版本号.ini')
        ini.set('配置','国服版本','7.0.0')
        with (imported/'版本号.ini').open('w',encoding='utf-8') as stream:
            ini.write(stream)
        # Switch preview accepts the generated original-layout foreign package.
        shutil.rmtree(self.game/'GenshinImpact_Data')
        self.write('YuanShen_Data/placeholder','shared')
        self.write('config.ini','[general]\ncps=mihoyo\ngame_version=7.0.0\n')
        self.assertTrue(self.service.preview('global')['copy'])

    def test_failed_export_not_published(self):
        params = self.prepare()
        before = self.snapshot()
        with patch('server_backup.shutil.copystat',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                export(params,self.config,self.service.root,lambda _:None,self.worker)
        self.assertEqual(list((self.root/'exports').iterdir()),[])
        self.assertEqual(before,self.snapshot())

    def test_cancel_and_process_guard(self):
        params=self.prepare()
        self.worker.cancel.set()
        with self.assertRaisesRegex(ValueError,'取消'):
            export(params,self.config,self.service.root,lambda _:None,self.worker)
        self.assertEqual(list((self.root/'exports').iterdir()),[])
        def running(_):
            raise ValueError('running')
        with self.assertRaisesRegex(ValueError,'running'):
            export(params,self.config,self.service.root,running,self.worker)

    def test_stdio_backup_task(self):
        from test_backend import Client
        params = self.prepare()
        client = Client(self.root / 'protocol-data', {'_gameRunning': False})
        try:
            checked = client.call('serverSwitch.backupPreview', **params)
            self.assertGreater(checked['result']['count'], 0)
            accepted = client.call('serverSwitch.backup', **params)
            finished = client.finished(accepted['result']['taskId'])
            self.assertEqual(finished['state'], 'succeeded', finished)
            self.assertTrue((Path(finished['result']['path']) / '版本号.ini').exists())
        finally:
            client.close()

    def test_default_backup_merges_channels_and_keeps_history(self):
        import struct
        params = self.prepare()
        params.pop('destination')
        raw = b'7.1.0_48052158_48145775'
        marker = struct.pack('<I', len(raw)) + raw + b'\x00'
        (self.game/'YuanShen_Data/globalgamemanagers').write_bytes(marker)
        (self.game/'config.ini').unlink()
        self.write('YuanShen_Data/Plugins/PCGameSDK.dll', 'sdk')
        self.write('YuanShen_Data/Plugins/BLPlatform64/PCGamePlatform.exe', 'login')
        result = export(params,self.config,self.service.root,lambda _:None,self.worker)
        folder = self.service.root/'备份包'
        self.assertEqual(Path(result['path']), folder)
        self.assertTrue((folder/'原神米哈游官服/YuanShen.exe').exists())
        self.assertEqual(read_ini(folder/'版本号.ini').get('配置','国服版本'), '7.1.0')
        (self.game/'YuanShen_Data/Plugins/PCGameSDK.dll').unlink()
        import shutil
        shutil.rmtree(self.game/'YuanShen_Data/Plugins/BLPlatform64')
        export(params,self.config,self.service.root,lambda _:None,self.worker)
        self.assertFalse((folder/'PCGameSDK.dll').exists())
        self.assertTrue(list((folder/'.history').rglob('PCGameSDK.dll')))
        params = self.prepare('global')
        params.pop('destination')
        (self.game/'GenshinImpact_Data/globalgamemanagers').write_bytes(marker)
        (self.game/'config.ini').unlink()
        export(params,self.config,self.service.root,lambda _:None,self.worker)
        self.assertTrue((folder/'原神国际服/GenshinImpact.exe').exists())
        self.assertTrue((folder/'原神米哈游官服/YuanShen.exe').exists())
        ini=read_ini(folder/'版本号.ini')
        self.assertEqual(ini.get('配置','国服版本'),'7.1.0')
        self.assertEqual(ini.get('配置','外服版本'),'7.1.0')

    def test_publication_failure_restores_existing_backup(self):
        params=self.prepare()
        export(params,self.config,self.service.root,lambda _:None,self.worker)
        folder=Path(params['destination'])
        before={p.relative_to(folder).as_posix():p.read_bytes() for p in folder.rglob('*') if p.is_file()}
        original=Path.rename
        def fail_version(source,destination):
            if source.name=='版本号.ini' and source.parent.name.startswith('.server-backup-'):
                raise OSError('publish failed')
            return original(source,destination)
        with patch('pathlib.Path.rename',fail_version):
            with self.assertRaises(OSError):
                export(params,self.config,self.service.root,lambda _:None,self.worker)
        after={p.relative_to(folder).as_posix():p.read_bytes() for p in folder.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_type_and_output_path_checks(self):
        params=self.prepare()
        with self.assertRaisesRegex(ValueError,'渠道不符'):
            preview(dict(params,channel='global'),self.config,self.service.root)
        for path in [self.game/'backup',self.service.root/'backup']:
            with self.assertRaises(ValueError):
                preview(dict(params,destination=str(path)),self.config,self.service.root)
        (self.game/'mhypbase.dll').unlink()
        with self.assertRaisesRegex(ValueError,'必要文件'):
            preview(params,self.config,self.service.root)

if __name__=='__main__':
    unittest.main()
