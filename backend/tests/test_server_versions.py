import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server_versions import embedded_version, collect
import test_server_switch as fixtures

class VersionTests(unittest.TestCase):
    setUp=fixtures.SwitchTests.setUp
    write=fixtures.SwitchTests.write
    native_package=fixtures.SwitchTests.native_package

    def marker(self, path, value='7.1.0_48052158_48145775', prefix=b'header'):
        raw=value.encode('ascii')
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(prefix+struct.pack('<I',len(raw))+raw+b'\x00')

    def test_not_fixed_offset_and_chunk_boundary(self):
        p=self.root/'globalgamemanagers'
        self.marker(p,prefix=b'x'*(1024*1024-14))
        self.assertEqual(embedded_version(p),{'version':'7.1.0','build':'7.1.0_48052158_48145775'})
        p.write_bytes(b'7.1.0_48052158_48145775')
        with self.assertRaises(ValueError):embedded_version(p)
        first='7.1.0_48052158_48145775'.encode()
        second='7.2.0_48052158_48145775'.encode()
        p.write_bytes(struct.pack('<I',len(first))+first+b'\x00'+struct.pack('<I',len(second))+second+b'\x00')
        with self.assertRaisesRegex(ValueError,'多个'):embedded_version(p)

    def test_reports_native_local_and_both_packages_even_without_game_config(self):
        base=self.native_package()
        self.marker(self.game/'YuanShen_Data/globalgamemanagers')
        self.marker(base/'原神米哈游官服/YuanShen_Data/globalgamemanagers')
        self.marker(base/'原神国际服/GenshinImpact_Data/globalgamemanagers','7.2.0_48052158_48145775')
        result=collect(self.service)
        self.assertEqual([row['version'] for row in result['sources']],['7.1.0','7.1.0','7.2.0'])
        self.assertTrue(all(row['mismatch'] for row in result['sources']))
        (self.game/'config.ini').unlink()
        result=collect(self.service)
        self.assertEqual(result['sources'][0]['version'],'7.1.0')
        self.assertEqual(result['errors'], [])

    def test_custom_layout_missing_and_corrupt_are_explicit(self):
        self.marker(self.game/'YuanShen_Data/globalgamemanagers','7.0.0_48052158_48145775')
        self.marker(self.service.root/'cn/YuanShen_Data/globalgamemanagers','7.0.0_48052158_48145775')
        (self.service.root/'global/GenshinImpact_Data/globalgamemanagers').unlink()
        rows=collect(self.service)['sources']
        self.assertFalse(rows[0]['mismatch'])
        self.assertFalse(rows[1]['mismatch'])
        self.assertEqual(rows[2]['error'],'文件不存在')
        self.write('config.ini','broken config')
        self.assertTrue(collect(self.service)['errors'])

    def test_stdio_versions(self):
        from test_backend import Client
        self.marker(self.game/'YuanShen_Data/globalgamemanagers')
        client=Client(self.data)
        try:
            result=client.call('serverSwitch.versions')['result']
            self.assertEqual(result['sources'][0]['version'],'7.1.0')
        finally:client.close()

if __name__=='__main__':unittest.main()
