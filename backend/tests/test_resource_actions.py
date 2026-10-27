"""Resource card/search and transactional drop regression tests (temporary files only)."""
import ctypes
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND), str(BACKEND.parent / 'OMGLite' / 'src')]
from resource_browser import ResourceService


class ResourceActionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'GIMI' / 'Mods'
        self.root.mkdir(parents=True)
        self.service = ResourceService(self.base / 'data', SimpleNamespace(get_gimi_dir=lambda: str(self.root.parent)))

    def test_card_preferences_thumbnails_configs_search_and_empty_filter(self):
        mod = self.root / 'group' / 'Outfit'
        mod.mkdir(parents=True)
        (mod / 'a.ini').write_text('[KeyOutfit]\nkey=X\n')
        (mod / 'preview.png').write_bytes(b'preview')
        (self.root / 'empty').mkdir()
        listing = self.service.listing('group')
        item = listing['items'][0]
        params = {'id': item['id'], 'revision': listing['revision'], 'path': 'group', 'isMod': False, 'masked': True}
        folder = self.service.card(params, None)['items'][0]
        self.assertFalse(folder['isMod'])
        self.assertEqual(folder['thumbnailPath'], str(mod / 'preview.png'))
        self.assertTrue(folder['masked'])
        fresh = ResourceService(self.base / 'data', self.service.config)
        self.assertFalse(fresh.listing('group')['items'][0]['isMod'])
        listing = self.service.listing('group')
        item = listing['items'][0]
        files = self.service.config_files({'id': item['id'], 'revision': listing['revision']})
        self.assertEqual(files[0]['name'], 'a.ini')
        self.assertEqual([i['name'] for i in self.service.listing(query='Outfit', recursive=True)['items']], ['Outfit'])
        self.assertEqual(self.service.listing(query='Outfit')['items'], [])
        self.assertNotIn('empty', [i['name'] for i in self.service.listing(hide_empty=True)['items']])
        # Breadcrumb lookup is read-only and must not invalidate card handles.
        self.service.folders('')
        listing = self.service.listing('group')
        item = listing['items'][0]
        renamed = self.service.toggle({'id': item['id'], 'revision': listing['revision'], 'enabled': False}, None)['items'][0]
        self.assertEqual(renamed['uiKey'], item['uiKey'])
        self.assertNotEqual(renamed['id'], item['id'])
        self.assertFalse(renamed['isMod'])
        self.assertTrue(renamed['masked'])

    def test_thumbnail_recurses_and_prioritizes_exact_preview_case_insensitively(self):
        mod = self.root / 'Outfit'
        nested = mod / 'assets' / 'images' / 'deep' / 'more'
        nested.mkdir(parents=True)
        (mod / 'mod.ini').write_text('[Constants]\n')
        for name in ('cover.png', 'preview-other.jpg', 'preview2.png'):
            (mod / name).write_bytes(b'image')
        image = nested / 'PrEvIeW.PNG'
        image.write_bytes(b'preview')
        listing = self.service.listing()
        item = listing['items'][0]
        self.assertTrue(item['isMod'])
        self.assertEqual(item['thumbnailPath'], str(image))
        with patch('resource_browser.os.startfile') as start:
            self.service.open_image({'id': item['id'], 'revision': listing['revision']})
            start.assert_called_once_with(str(image))

    def test_mod_thumbnail_refresh_observes_nested_changes(self):
        mod = self.root / 'group'
        nested = mod / 'assets'
        nested.mkdir(parents=True)
        (mod / 'mod.ini').write_text('[Constants]\n')
        (nested / 'mod.ini').write_text('[Constants]\n')
        (nested / 'normal.png').write_bytes(b'texture')
        self.assertIsNone(self.service.listing()['items'][0]['thumbnailPath'])
        image = nested / 'photo.jpg'
        image.write_bytes(b'image')
        item = self.service.listing()['items'][0]
        self.assertTrue(item['isMod'])
        self.assertEqual(item['thumbnailPath'], str(image))
        preview = nested / 'PREVIEW.webp'
        image.rename(preview)
        self.assertEqual(self.service.listing()['items'][0]['thumbnailPath'], str(preview))
        preview.unlink()
        self.assertIsNone(self.service.listing()['items'][0]['thumbnailPath'])

    def test_folder_thumbnail_is_shallow_and_has_no_preview_name_priority(self):
        folder = self.root / 'group'
        nested = folder / 'nested'
        nested.mkdir(parents=True)
        (nested / 'mod.ini').write_text('[Constants]\n')
        (nested / 'preview.png').write_bytes(b'nested preview')
        item = self.service.listing()['items'][0]
        self.assertFalse(item['isMod'])
        self.assertIsNone(item['thumbnailPath'])
        (folder / 'PREVIEW.png').write_bytes(b'preview')
        cover = folder / 'a.jpg'
        cover.write_bytes(b'cover')
        listing = self.service.listing()
        item = listing['items'][0]
        self.assertEqual(item['thumbnailPath'], str(cover))
        with patch('resource_browser.os.startfile') as start:
            self.service.open_image({'id': item['id'], 'revision': listing['revision']})
            start.assert_called_once_with(str(cover))

    def test_card_conversion_changes_thumbnail_search_and_persists(self):
        mod = self.root / 'Outfit'
        nested = mod / 'assets'
        nested.mkdir(parents=True)
        (mod / 'mod.ini').write_text('[Constants]\n')
        cover = mod / 'a.jpg'
        cover.write_bytes(b'cover')
        preview = nested / 'PrEvIeW.png'
        preview.write_bytes(b'preview')
        (mod / 'preview.jpg').write_bytes(b'direct preview')
        # Remove the direct preview after the first folder conversion so both
        # name priority and recursive search are checked using the same cache.
        listing = self.service.listing()
        for is_mod, expected in ((False, cover), (True, preview), (False, cover)):
            item = listing['items'][0]
            listing = self.service.card({'id': item['id'], 'revision': listing['revision'],
                                         'isMod': is_mod}, None)
            self.assertEqual(listing['items'][0]['isMod'], is_mod)
            self.assertEqual(listing['items'][0]['thumbnailPath'], str(expected))
            if not is_mod and (mod / 'preview.jpg').exists():
                (mod / 'preview.jpg').unlink()
                listing = self.service.listing()
        fresh = ResourceService(self.base / 'data', self.service.config)
        self.assertEqual(fresh.listing()['items'][0]['thumbnailPath'], str(cover))

    def test_thumbnail_prunes_directory_link_cycles(self):
        mod = self.root / 'Outfit'
        nested = mod / 'assets'
        nested.mkdir(parents=True)
        (mod / 'mod.ini').write_text('[Constants]\n')
        image = nested / 'preview.jpg'
        image.write_bytes(b'preview')
        original_token = self.service.token
        # Model a directory junction back to the card root without requiring
        # Windows symlink privileges on the machine running the tests.
        loop = nested / 'loop'
        loop.mkdir()
        with patch.object(self.service, 'token', side_effect=lambda path:
                          original_token(mod if path == loop else path)):
            self.assertEqual(self.service.listing()['items'][0]['thumbnailPath'], str(image))

    def test_directory_menus_list_direct_children_without_invalidating_handles(self):
        group = self.root / 'group'
        (group / 'empty').mkdir(parents=True)
        (group / 'nested').mkdir()
        (group / 'direct.INI').write_text('[Constants]\n')
        (group / 'nested/inner.ini').write_text('[Constants]\n')
        (group / 'readme.txt').write_text('ignored')
        listing = self.service.listing('group')
        entry = next(i for i in listing['items'] if i['name'] == 'direct.INI')
        menu = self.service.directory_entries('group')
        self.assertEqual([i['name'] for i in menu['folders']], ['empty', 'nested'])
        self.assertEqual(menu['files'], [{'name': 'direct.INI', 'path': 'group/direct.INI'}])
        self.assertEqual(self.service.config_files({'id': entry['id'], 'revision': listing['revision']})[0]['name'], 'direct.INI')
        with self.assertRaises(ValueError):
            self.service.directory_entries('..')

    def test_open_image_uses_resource_preview_and_rejects_stale_handles(self):
        mod = self.root / 'Outfit'
        mod.mkdir()
        image = mod / 'preview.png'
        image.write_bytes(b'preview')
        listing = self.service.listing()
        item = listing['items'][0]
        params = {'id': item['id'], 'revision': listing['revision'],
                  'path': 'untrusted.exe'}
        with patch('resource_browser.os.startfile') as start:
            self.service.open_image(params)
            start.assert_called_once_with(str(image))
            with self.assertRaises(ValueError):
                self.service.open_image({**params, 'revision': -1})
            image.unlink()
            with self.assertRaises(ValueError):
                self.service.open_image(params)
            self.assertEqual(start.call_count, 1)

    def test_open_image_without_preview_is_rejected(self):
        (self.root / 'empty').mkdir()
        listing = self.service.listing()
        with patch('resource_browser.os.startfile') as start:
            with self.assertRaises(ValueError):
                self.service.open_image({'id': listing['items'][0]['id'],
                                         'revision': listing['revision']})
            start.assert_not_called()

    def sources(self):
        folder = self.base / 'source'
        folder.mkdir()
        (folder / 'nested.txt').write_bytes(b'original folder')
        file = self.base / 'file.txt'
        file.write_bytes(b'original file')
        return [folder, file]

    def move(self, sources):
        with patch.object(self.service, 'open_path'):
            return self.service.move({'sources': [str(s) for s in sources]}, None)

    def assert_restored(self, sources):
        self.assertEqual((sources[0] / 'nested.txt').read_bytes(), b'original folder')
        self.assertEqual(sources[1].read_bytes(), b'original file')
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(list(self.base.glob('.omg-recovery-*')), [])

    def test_success_moves_files_and_folders_and_opens_destination(self):
        sources = self.sources()
        with patch.object(self.service, 'open_path') as opened:
            result = self.service.move({'sources': [str(s) for s in sources]}, None)
        opened.assert_called_once_with({'path': ''})
        self.assertTrue(result['message'].startswith('已移动 2 项'))
        self.assertFalse(any(s.exists() for s in sources))
        self.assertEqual((self.root / 'source' / 'nested.txt').read_bytes(), b'original folder')
        self.assertEqual((self.root / 'file.txt').read_bytes(), b'original file')

    def test_copy_failure_disk_full_keeps_all_sources(self):
        sources = self.sources()
        import shutil
        original = shutil.copy2
        def fail(source, dest, **kwargs):
            if Path(source) == sources[1]:
                Path(dest).write_bytes(b'partial')
                raise OSError(28, 'No space left on device')
            return original(source, dest, **kwargs)
        with patch('resource_browser.shutil.copy2', side_effect=fail):
            with self.assertRaisesRegex(ValueError, '原文件已恢复'):
                self.move(sources)
        self.assert_restored(sources)

    def test_second_commit_failure_rolls_back_already_committed_file(self):
        sources = self.sources()
        original = Path.rename
        def fail(source, dest):
            if source.parent.name.startswith('.omg-move-') and source.name == 'file.txt':
                raise PermissionError('occupied destination')
            return original(source, dest)
        with patch.object(Path, 'rename', fail):
            with self.assertRaisesRegex(ValueError, '原文件已恢复'):
                self.move(sources)
        self.assert_restored(sources)

    def test_collision_and_descendant_rejected_before_changes(self):
        sources = self.sources()
        (self.root / 'file.txt').write_bytes(b'existing')
        with self.assertRaisesRegex(ValueError, '同名'):
            self.move(sources)
        self.assertEqual((self.root / 'file.txt').read_bytes(), b'existing')
        nested = self.root / 'outer' / 'inner'
        nested.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, '自身'):
            self.service.move({'sources': [str(nested.parent)], 'path': 'outer/inner'}, None)

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing semantics')
    def test_real_occupied_file_rolls_back_previous_source_rename(self):
        sources = self.sources()
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.CreateFileW(str(sources[1]), 0x80000000, 1, None, 3, 0, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            with self.assertRaisesRegex(ValueError, '原文件已恢复'):
                self.move(sources)
        finally:
            kernel.CloseHandle(handle)
        self.assert_restored(sources)

if __name__ == '__main__':
    unittest.main()
