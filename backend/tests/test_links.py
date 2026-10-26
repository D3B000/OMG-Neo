import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from link_service import LinkService


class LinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.gimi = self.root / 'GIMI'
        self.mods = self.gimi / 'Mods'
        self.mods.mkdir(parents=True)
        self.resource = self.root / '中文资源 & files'
        self.resource.mkdir()
        (self.resource / 'test.ini').write_text('[Test]', encoding='utf-8')
        self.service = LinkService(SimpleNamespace(get_gimi_dir=lambda: str(self.gimi)))
        self.params = dict(mode='junction', resource=str(self.resource),
                           destination=str(self.mods), name='中文 & link')

    @unittest.skipUnless(os.name == 'nt', 'Windows junction')
    def test_real_junction_and_duplicate(self):
        checked = self.service.validate(self.params)
        self.assertIn('支持重解析点', checked['message'])
        result = self.service.create(self.params)
        link = Path(result['path'])
        self.addCleanup(lambda: os.rmdir(link) if os.path.lexists(link) else None)
        self.assertEqual((link / 'test.ini').read_text(), '[Test]')
        with self.assertRaisesRegex(ValueError, '已存在'):
            self.service.create(self.params)

    def test_invalid_names_and_cycle(self):
        for name in ('', '../bad', 'CON', 'nul.ini', 'bad.', 'bad ', 'a:b', 'a\\b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.service.validate({**self.params, 'name': name})
        with self.assertRaisesRegex(ValueError, '递归'):
            self.service.validate({**self.params, 'destination': str(self.resource)})

    def test_unsupported_volume(self):
        with patch('link_service.volume_info', side_effect=ValueError('磁盘不支持')):
            with self.assertRaisesRegex(ValueError, '不支持'):
                self.service.create(self.params)
        self.assertFalse((self.mods / self.params['name']).exists())

    def test_include_relative_and_no_overwrite(self):
        params = dict(mode='include', resource=str(self.resource))
        result = self.service.create(params)
        path = Path(result['path'])
        content = path.read_text(encoding='utf-8')
        self.assertEqual(content, '[Include]\ninclude_recursive = ..\\..\\中文资源 & files\nexclude_recursive = DISABLED*\n')
        self.assertEqual((path.parent / '..' / '..' / self.resource.name).resolve(), self.resource)
        self.assertTrue(self.service.create(params)['alreadyIncluded'])
        self.assertEqual(path.read_text(encoding='utf-8'), content)

    def test_include_appends_before_exclude_preserving_config(self):
        target = self.mods / 'modFolder.ini'
        original = ('; 保留注释\r\n[Include]\r\ninclude_recursive = ..\\..\\旧资源\r\n'
                    'exclude_recursive = DISABLED*\r\n\r\n[Other]\r\nvalue = keep\r\n')
        target.write_bytes(original.encode('utf-8-sig'))
        params = dict(mode='include', resource=str(self.resource))
        preview = self.service.validate(params)
        self.assertEqual(target.read_bytes(), original.encode('utf-8-sig'))
        self.assertIn('include_recursive = ..\\..\\中文资源 & files\r\nexclude_recursive', preview['content'])
        self.service.create(params)
        expected = original.replace('exclude_recursive', 'include_recursive = ..\\..\\中文资源 & files\r\nexclude_recursive', 1)
        self.assertEqual(target.read_bytes(), expected.encode('utf-8-sig'))
        other = self.root / '新资源'
        other.mkdir()
        self.service.create(dict(mode='include', resource=str(other)))
        text = target.read_text(encoding='utf-8-sig')
        self.assertIn('include_recursive = ..\\..\\新资源\nexclude_recursive = DISABLED*', text)
        self.assertEqual(text.count('[Include]'), 1)
        self.assertEqual(text.count('exclude_recursive'), 1)

    def test_include_invalid_config_and_write_failure_preserve_original(self):
        target = self.mods / 'modFolder.ini'
        target.write_bytes(b'[Other]\nexclude_recursive = DISABLED*\n')
        params = dict(mode='include', resource=str(self.resource))
        with self.assertRaisesRegex(ValueError, '缺少'):
            self.service.create(params)
        original = b'[Include]\ninclude_recursive = ../../old\nexclude_recursive = DISABLED*'
        target.write_bytes(original)
        with patch('link_service.os.replace', side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):
                self.service.create(params)
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(list(self.mods.glob('.modFolder-*.tmp')), [])

    def test_include_non_sibling(self):
        nested = self.resource / 'nested'
        nested.mkdir()
        for resource in (nested, self.gimi, self.mods):
            with self.assertRaisesRegex(ValueError, '父目录'):
                self.service.create(dict(mode='include', resource=str(resource)))
        self.assertFalse((self.mods / 'modFolder.ini').exists())

    def test_stdio_include(self):
        from test_backend import Client
        client = Client(self.root / 'appdata')
        try:
            client.call('hello')
            response = client.call('config.patch', patch={'gimi_folder': str(self.gimi)})
            self.assertNotIn('error', response)
            params = dict(mode='include', resource=str(self.resource))
            checked = client.call('links.validate', **params)
            self.assertIn('content', checked['result'])
            created = client.call('links.create', **params)
            self.assertTrue(Path(created['result']['path']).is_file())
            self.assertTrue(client.call('links.create', **params)['result']['alreadyIncluded'])
            other = self.root / '第二资源'
            other.mkdir()
            appended = client.call('links.create', mode='include', resource=str(other))
            self.assertNotIn('error', appended)
            self.assertIn('include_recursive = ..\\..\\第二资源\nexclude_recursive',
                          Path(created['result']['path']).read_text(encoding='utf-8'))
        finally:
            client.close()


if __name__ == '__main__':
    unittest.main()
