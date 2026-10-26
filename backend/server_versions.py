"""Read embedded build identifiers without running or modifying the client."""
from __future__ import annotations
import configparser
import json
from pathlib import Path
import re
import struct

BUILD = re.compile(rb'(?<![0-9.])([0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,3})_[0-9]{5,}_[0-9]{5,}(?![0-9])')


def embedded_version(path):
    """Locate a length-prefixed build string; offsets differ between clients."""
    found = set()
    tail = b''
    with Path(path).open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            data = tail + chunk
            for match in BUILD.finditer(data):
                start = match.start()
                if start >= 4 and struct.unpack_from('<I', data, start - 4)[0] == len(match.group()):
                    found.add((match.group(1).decode('ascii'), match.group().decode('ascii')))
            tail = data[-256:]
    if not found:
        raise ValueError('未找到有效的内嵌版本')
    if len(found) != 1:
        raise ValueError('发现多个内嵌版本，无法确定')
    version, build = found.pop()
    return {'version': version, 'build': build}


def collect(service):
    from server_switch import DATA, local_tree, read_ini
    rows = []
    errors = []
    try:
        game, _ = service.game()
    except (OSError, ValueError, configparser.Error) as exc:
        game = None
        errors.append(str(exc))
    declared = ''
    if game:
        try:
            declared = read_ini(game / 'config.ini').get('general', 'game_version', fallback='').strip()
        except FileNotFoundError:
            pass  # Optional: channel/version can be inferred from client files.
        except (OSError, ValueError, configparser.Error) as exc:
            errors.append(f'游戏配置不可读，仍显示内嵌版本：{exc}')
    try:
        native = service.native_root()
        if native is None:
            candidates = [p for p in (service.root, service.root / '替换包', service.root / '原神资源替换包')
                          if (p / '原神米哈游官服').is_dir() or (p / '原神国际服').is_dir()]
            if len(candidates) > 1:
                raise ValueError('发现多个替换包，请只保留一套')
            native = candidates[0] if candidates else None
    except (OSError, ValueError, configparser.Error) as exc:
        native = None
        errors.append(f'替换包：{exc}')
        return {'sources': _local_rows(game, declared), 'errors': errors, 'resourceRoot': str(service.root), 'backupRoot': str(service.root / '备份包')}
    rows.extend(_local_rows(game, declared))
    for channel, label in [('cn', '国服'), ('global', '国际服')]:
        package = native / ('原神米哈游官服' if channel == 'cn' else '原神国际服') if native else service.root / channel
        value, note = '', ''
        try:
            if native:
                value = read_ini(native / '版本号.ini').get('配置', '国服版本' if channel == 'cn' else '外服版本', fallback='').strip()
            else:
                value = str(json.loads((package / 'manifest.json').read_text(encoding='utf-8-sig')).get('game_version', ''))
        except (OSError, ValueError, configparser.Error) as exc:
            note = f'声明配置不可读：{exc}'
        rows.append(_row(f'package.{channel}', f'替换包 / {label}', package / DATA[channel] / 'globalgamemanagers', value, note))
    return {'sources': rows, 'errors': errors, 'resourceRoot': str(service.root), 'backupRoot': str(service.root / '备份包')}


def _local_rows(game, declared):
    from server_switch import DATA
    if game is None:
        return []
    existing = [(key, folder) for key, folder in DATA.items() if (game / folder).is_dir()]
    if not existing:
        return [_row('local', '本地游戏', game / 'YuanShen_Data/globalgamemanagers', declared)]
    return [_row(f'local.{key}', f'本地游戏 / {"国服" if key == "cn" else "国际服"}',
                 game / folder / 'globalgamemanagers', declared) for key, folder in existing]


def _row(key, label, path, declared, note=''):
    from server_switch import local_tree
    row = {'id': key, 'label': label, 'path': str(path), 'declaredVersion': declared,
           'version': '', 'build': '', 'mismatch': False, 'error': '', 'note': note}
    try:
        local_tree(path, recursive=False)
        row.update(embedded_version(path))
        row['mismatch'] = bool(declared and declared != row['version'])
    except (OSError, ValueError, configparser.Error) as exc:
        row['error'] = '文件不存在' if isinstance(exc, FileNotFoundError) else str(exc)
    return row
