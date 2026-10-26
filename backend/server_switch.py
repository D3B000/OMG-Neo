"""Genshin channel conversion using user-supplied, versioned local packages."""
from __future__ import annotations
import configparser
import io
import json
import os
from pathlib import Path
import shutil
import uuid

CHANNELS = {'cn': ('1', '1', 'mihoyo'), 'bilibili': ('14', '0', 'bilibili'),
            'global': ('1', '0', 'hoyoverse_PC')}
DATA = {'cn': 'YuanShen_Data', 'global': 'GenshinImpact_Data'}


def read_ini(path):
    raw = path.read_bytes()
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeError:
            continue
    else:
        raise ValueError(f'无法读取配置：{path}')
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    for section in list(parser.sections()):
        if section.casefold() == 'general' and section != 'general':
            if parser.has_section('general'):
                raise ValueError('游戏配置存在重复的 General 段')
            parser['general'] = dict(parser[section])
            parser.remove_section(section)
    return parser


def local_tree(path, recursive=True):
    """Reject links/junctions before any recursive copy or game mutation."""
    for item in [path, *path.parents]:
        if item.is_symlink() or (item.exists() and os.name == 'nt' and item.lstat().st_file_attributes & 0x400):
            raise ValueError(f'不支持链接或目录联接：{item}')
    if recursive and path.is_dir():
        for base, dirs, files in os.walk(path, followlinks=False):
            for name in dirs + files:
                item = Path(base) / name
                if item.is_symlink() or (item.lstat().st_file_attributes & 0x400 if os.name == 'nt' else False):
                    raise ValueError(f'不支持重解析点：{item}')


def load_game_ini(game):
    try:
        ini = read_ini(Path(game) / 'config.ini')
    except (OSError, configparser.Error):
        ini = configparser.ConfigParser(interpolation=None)
    if not ini.has_section('general'):
        ini.add_section('general')
    return ini


def file_version(path, declared=''):
    from server_versions import embedded_version
    try:
        return embedded_version(path)['version']
    except FileNotFoundError:
        pass
    except ValueError as exc:
        if '多个' in str(exc):
            raise
    if declared:
        return declared.strip()
    raise ValueError(f'无法从游戏文件读取版本：{path}')


def identify_game(game):
    game = Path(game)
    ini = load_game_ini(game)
    cps = ini.get('general', 'cps', fallback='').strip()
    known = next((key for key, values in CHANNELS.items() if values[2] == cps), None)
    layouts = [key for key, folder in DATA.items() if (game / folder).is_dir() and
               (game / ('GenshinImpact.exe' if key == 'global' else 'YuanShen.exe')).is_file()]
    if len(layouts) != 1:
        raise ValueError('游戏文件结构不明确，请确保只保留一套完整的国服或国际服客户端')
    layout = layouts[0]
    if known and ('global' if known == 'global' else 'cn') != layout:
        raise ValueError('config.ini 渠道与游戏文件结构不一致，请检查游戏目录')
    current = known or ('global' if layout == 'global' else
                        'bilibili' if (game / DATA['cn'] / 'Plugins/PCGameSDK.dll').is_file() else 'cn')
    manager = game / DATA[layout] / 'globalgamemanagers'
    local_tree(manager, recursive=False)
    declared = ini.get('general', 'game_version', fallback='').strip()
    return {'current': current, 'version': file_version(manager, declared), 'declaredVersion': declared}


class ServerSwitchService:
    def __init__(self, root, config, game_stopped):
        self.root = Path(root) / 'server-switch'
        self.config = config
        self.game_stopped = game_stopped

    def open_directory(self):
        from resource_service import no_links
        import subprocess
        folder = no_links(self.root, self.root.parent)
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(['explorer.exe', str(folder)])
        return {}

    def game(self):
        settings = self.config.snapshot()['settings']
        value = settings.get('game_folder', '').strip()
        if not value or not Path(value).is_dir():
            raise ValueError('请先在设置中配置原神游戏目录')
        game = Path(value).resolve()
        local_tree(Path(value).absolute(), recursive=False)
        if game == self.root or game in self.root.parents or self.root in game.parents:
            raise ValueError('游戏目录与替换资源目录不能互相包含')
        return game, settings

    def status(self):
        game, _ = self.game()
        return {**identify_game(game), 'resourceRoot': str(self.root), 'game': str(game),
                'backupRoot': str(self.root / '备份包'),
                'recovery': (self.root / 'pending.json').exists()}

    def native_root(self):
        candidates = [base for base in (self.root, self.root / '替换包', self.root / '原神资源替换包')
                      if (base / '版本号.ini').is_file() or (base / '原神米哈游官服').is_dir() or (base / '原神国际服').is_dir()]
        if len(candidates) > 1:
            raise ValueError('发现多个替换包，请只保留一套')
        return candidates[0] if candidates else None

    def native_meta(self, base, channel, version):
        local_tree(base)
        try:
            ini = read_ini(base / '版本号.ini')
        except FileNotFoundError:
            ini = configparser.ConfigParser(interpolation=None)
        key = '外服版本' if channel == 'global' else '国服版本'
        declared = ini.get('配置', key, fallback='').strip()
        package = base / ('原神国际服' if channel == 'global' else '原神米哈游官服')
        actual = file_version(package / DATA[channel] / 'globalgamemanagers', declared)
        if actual != version:
            raise ValueError(f'替换包{key}与游戏版本不一致：{actual} / {version}')
        return {'game_version': actual}

    def plan(self, target):
        if target not in CHANNELS:
            raise ValueError('未知服务器')
        state = self.status()
        if state['recovery']:
            raise ValueError('上次切换未完成，请先恢复')
        if state['current'] is None or not state['version']:
            raise ValueError('无法识别当前渠道或游戏版本，请检查游戏 config.ini')
        game, settings = self.game()
        old = DATA['global' if state['current'] == 'global' else 'cn']
        new = DATA['global' if target == 'global' else 'cn']
        local_tree(game / old, recursive=False)
        if not (game / old).is_dir() or (old != new and (game / new).exists()):
            raise ValueError('游戏数据目录缺失或国服、国际服目录同时存在，请先修复')
        copies = {}
        cross = old != new
        native = self.native_root()
        channel = 'global' if target == 'global' else 'cn'
        package = (native / ('原神国际服' if channel == 'global' else '原神米哈游官服')
                   if native else self.root / channel)
        meta = {}
        if cross:
            local_tree(package)
            meta = (self.native_meta(native, channel, state['version']) if native else
                    json.loads((package / 'manifest.json').read_text(encoding='utf-8-sig')))
            if native:
                self.native_meta(native, 'global' if state['current'] == 'global' else 'cn', state['version'])
                cn_hdiff = native / '原神米哈游官服/YuanShen_Data/Plugins/hdiffz.dll'
                if channel == 'global' and cn_hdiff.is_file() and not (package / f'{new}/Plugins/hdiffz.dll').exists():
                    meta['remove'] = [f'{new}/Plugins/hdiffz.dll']
            meta['game_version'] = file_version(package / DATA[channel] / 'globalgamemanagers', meta.get('game_version', ''))
            if meta.get('game_version') != state['version']:
                raise ValueError('替换包版本与游戏版本不一致')
            exe = 'GenshinImpact.exe' if target == 'global' else 'YuanShen.exe'
            required = [exe, 'mhypbase.dll', 'pkg_version', f'{new}/app.info',
                        f'{new}/globalgamemanagers', f'{new}/globalgamemanagers.assets',
                        f'{new}/globalgamemanagers.assets.resS',
                        f'{new}/Native/Data/Metadata/global-metadata.dat',
                        f'{new}/Native/Data/Metadata/startup-metadata.dat']
            for name in required:
                if not (package / name).is_file():
                    raise ValueError(f'替换包缺少文件：{name}')
            allowed = {exe, 'mhypbase.dll', 'UnityPlayer.dll', 'pkg_version',
                       'Audio_Chinese_pkg_version'}
            for src in package.rglob('*'):
                if src.is_file() and src.name != 'manifest.json':
                    rel = src.relative_to(package)
                    # Backup config is version evidence, never overwrite the live configuration.
                    if rel.as_posix() == 'config.ini':
                        continue
                    if rel.as_posix() == f'{new}/Plugins/PCGameSDK.dll' or rel.as_posix().startswith(f'{new}/Plugins/BLPlatform64/'):
                        continue
                    if rel.as_posix() not in allowed and rel.parts[0] != new:
                        raise ValueError(f'替换包包含非预期文件：{rel}')
                    copies[rel.as_posix()] = src
        sdk = f'{new}/Plugins/PCGameSDK.dll'
        login = f'{new}/Plugins/BLPlatform64'
        if target == 'bilibili':
            bpack = native if native else self.root / 'bilibili'
            local_tree(bpack)
            bmeta = (self.native_meta(native, 'cn', state['version']) if native else
                     json.loads((bpack / 'manifest.json').read_text(encoding='utf-8-sig')))
            if bmeta.get('game_version') != state['version']:
                raise ValueError('B 服登录组件版本与游戏版本不一致')
            sdk_source = bpack / 'PCGameSDK.dll'
            login_source = (bpack / '原神B服新登录框窗口/BLPlatform64' if native else bpack / 'BLPlatform64')
            if not sdk_source.is_file() or not (login_source / 'PCGamePlatform.exe').is_file():
                raise ValueError('缺少 B 服 SDK 或登录窗口组件；请使用 B 服备份补齐组件')
            copies[sdk] = sdk_source
            copies[login] = login_source
        deletes = [] if target == 'bilibili' else [sdk, login]
        if cross:
            deletes.append('YuanShen.exe' if target == 'global' else 'GenshinImpact.exe')
            # Version-specific removals must be supplied explicitly by the package.
            for rel in meta.get('remove', []):
                if not isinstance(rel, str) or rel != f'{new}/Plugins/hdiffz.dll':
                    raise ValueError('不支持的替换包清理规则')
                deletes.append(rel)
        # Large shared resource directories may be junctions. Validate only paths
        # that this transaction reads, overwrites or removes, including ancestors.
        for rel in [*copies, *deletes, 'config.ini']:
            source_rel = old + rel[len(new):] if rel.startswith(new + '/') else rel
            local_tree(game / source_rel)
        return state, game, settings, old, new, copies, deletes

    def preview(self, target):
        state, game, _, old, new, copies, deletes = self.plan(target)
        return {**state, 'target': target, 'rename': f'{old} → {new}' if old != new else '',
                'copy': list(copies), 'remove': deletes}

    def restore(self):
        pending = self.root / 'pending.json'
        record = json.loads(pending.read_text(encoding='utf-8'))
        game, settings = self.game()
        self.game_stopped(settings)
        if str(game) != record['game']:
            raise ValueError('恢复记录与当前游戏目录不同，请还原游戏路径设置')
        local_tree(self.root)
        if not isinstance(record.get('id'), str) or len(record['id']) != 32 or any(c not in '0123456789abcdef' for c in record['id']):
            raise ValueError('恢复记录编号无效')
        backup = self.root / 'backups' / record['id']
        old, new = record['old'], record['new']
        if old not in DATA.values() or new not in DATA.values():
            raise ValueError('恢复记录目录无效')
        if old != new and (game / old).exists() and (game / new).exists():
            raise ValueError('两个数据目录同时存在，无法自动恢复')
        for entry in record['entries']:
            rel = Path(entry['path'])
            if rel.is_absolute() or '..' in rel.parts or ':' in str(rel) or str(rel) in ('', '.'):
                raise ValueError('恢复记录路径无效')
            source_rel = old + rel.as_posix()[len(new):] if rel.as_posix().startswith(new + '/') else rel.as_posix()
            local_tree(game / source_rel)
            local_tree(game / rel)
            if entry['exists'] and not (backup / rel).exists():
                raise ValueError(f'恢复备份缺失：{rel}')
        # The rename may have failed before mutation; restore to the directory that exists.
        renamed = old != new and (game / new).exists() and not (game / old).exists()
        for entry in reversed(record['entries']):
            rel = entry['path']
            if old != new and not renamed and rel.startswith(new + '/'):
                rel = old + rel[len(new):]
            dest = game / rel
            if dest.is_dir():
                shutil.rmtree(dest)
            elif dest.exists():
                dest.unlink()
            if entry['exists']:
                src = backup / entry['path']
                dest.parent.mkdir(parents=True, exist_ok=True)
                if src.is_dir():
                    shutil.copytree(src, dest)
                else:
                    shutil.copy2(src, dest)
        if renamed:
            (game / new).rename(game / old)
        pending.unlink()
        return {'message': '已恢复切换前文件', 'backup': str(backup)}

    def apply(self, target, worker):
        state, game, settings, old, new, copies, deletes = self.plan(target)
        self.game_stopped(settings)
        if target == state['current']:
            return {'message': '已经是目标服务器'}
        local_tree(self.root)
        tx = uuid.uuid4().hex
        backup = self.root / 'backups' / tx
        backup.mkdir(parents=True)
        entries = []
        paths = list(dict.fromkeys([*copies, *deletes, 'config.ini']))
        # All backups complete before the first game write.
        for rel in paths:
            source_rel = old + rel[len(new):] if rel.startswith(new + '/') else rel
            source = game / source_rel
            entries.append({'path': rel, 'exists': source.exists()})
            if source.exists():
                dest = backup / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(source, dest)
                else:
                    shutil.copy2(source, dest)
        record = {'id': tx, 'game': str(game), 'old': old, 'new': new, 'entries': entries}
        (backup / 'transaction.json').write_text(json.dumps(record), encoding='utf-8')
        pending = self.root / 'pending.json'
        temp = self.root / 'pending.tmp'
        temp.write_text(json.dumps(record), encoding='utf-8')
        temp.replace(pending)
        try:
            if worker.cancel.is_set():
                raise ValueError('切换已取消')
            if old != new:
                (game / old).rename(game / new)
            for index, (rel, src) in enumerate(copies.items()):
                if worker.cancel.is_set():
                    raise ValueError('切换已取消')
                dest = game / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if src.is_dir():
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(src, dest)
                else:
                    shutil.copy2(src, dest)
                worker.progress.emit({'message': f'正在替换 {rel}', 'progress': (index + 1) / (len(copies) + 1)})
            for rel in deletes:
                dest = game / rel
                if dest.is_dir():
                    shutil.rmtree(dest)
                elif dest.exists():
                    dest.unlink()
            ini = load_game_ini(game)
            ini.set('general', 'game_version', state['version'])
            for key, value in zip(('channel', 'sub_channel', 'cps'), CHANNELS[target]):
                ini.set('general', key, value)
            app = 'hk4e_global' if target == 'global' else 'hk4e_cn'
            ini.set('general', 'uapc', json.dumps({app: {'uapc': ''}, 'hyp': {'uapc': ''}}))
            stream = io.StringIO()
            ini.write(stream, space_around_delimiters=False)
            (game / 'config.ini').write_text(stream.getvalue(), encoding='utf-8')
            pending.unlink()
        except Exception as exc:
            try:
                self.restore()
            except Exception as recovery:
                raise RuntimeError(f'切换失败：{exc}；自动恢复失败：{recovery}。请使用恢复按钮。') from exc
            raise RuntimeError(f'切换失败并已回滚：{exc}') from exc
        return {'message': '服务器切换完成', 'backup': str(backup), 'target': target}
