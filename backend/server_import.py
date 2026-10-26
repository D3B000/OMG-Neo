"""Recognize local replacement packages and publish only switcher files."""
from __future__ import annotations
import configparser
import io
import json
from pathlib import Path
import re
import shutil
import uuid

from server_backup import DATA_FILES, PLUGINS
from server_switch import DATA, file_version, local_tree, read_ini

PACKAGES = {'cn': '原神米哈游官服', 'global': '原神国际服'}


def cancelled(worker):
    if worker.cancel.is_set():
        raise ValueError('导入已取消')


def channels_at(base):
    result = {}
    for channel, name in PACKAGES.items():
        for folder in (base / name, base / channel):
            if folder.is_dir():
                if channel in result:
                    raise ValueError('不是一个明确的替换包：同一渠道存在多个目录')
                result[channel] = folder
        exe = 'YuanShen.exe' if channel == 'cn' else 'GenshinImpact.exe'
        if (base / exe).is_file() and (
                base.name == name or (base / 'manifest.json').is_file()):
            result[channel] = base
    return result


def discover(source, worker):
    """Inspect at most two wrapper levels, without walking game assets."""
    pending, found, inspected = [(source, 0)], [], 0
    while pending:
        cancelled(worker)
        base, depth = pending.pop()
        inspected += 1
        if inspected > 128:
            raise ValueError('不是一个明确的替换包：请拖入替换包所在的文件夹')
        local_tree(base, recursive=False)
        channels = channels_at(base)
        if channels:
            found.append((base, channels))
            continue
        if depth < 2:
            for child in base.iterdir():
                if not child.name.startswith('.') and child.is_dir():
                    local_tree(child, recursive=False)
                    pending.append((child, depth + 1))
                    if len(pending) + inspected > 128:
                        raise ValueError('不是一个明确的替换包：请拖入替换包所在的文件夹')
    if len(found) != 1:
        raise ValueError('不是一个替换包' if not found else '发现多个替换包，请每次只拖入一个')
    return found[0]


def collect(source, worker, located=None):
    base, channels = located if located is not None else discover(source, worker)
    metadata = base / '版本号.ini'
    if base.name in PACKAGES.values() and not metadata.exists():
        metadata = base.parent / '版本号.ini'
    local_tree(metadata, recursive=False)
    ini = read_ini(metadata) if metadata.is_file() else configparser.ConfigParser(interpolation=None)
    files, versions = {}, {}
    for channel, folder in channels.items():
        cancelled(worker)
        local_tree(folder, recursive=False)
        data = DATA[channel]
        exe = 'YuanShen.exe' if channel == 'cn' else 'GenshinImpact.exe'
        required = [exe, 'mhypbase.dll', 'pkg_version', f'{data}/app.info',
                    f'{data}/globalgamemanagers', f'{data}/globalgamemanagers.assets',
                    f'{data}/globalgamemanagers.assets.resS',
                    f'{data}/Native/Data/Metadata/global-metadata.dat',
                    f'{data}/Native/Data/Metadata/startup-metadata.dat']
        for name in required:
            file = folder / name
            local_tree(file, recursive=False)
            if not file.is_file():
                raise ValueError(f'不是一个完整的替换包：缺少 {name}')
        key = '国服版本' if channel == 'cn' else '外服版本'
        declared = ini.get('配置', key, fallback='').strip()
        manifest = folder / 'manifest.json'
        local_tree(manifest, recursive=False)
        if not declared and manifest.is_file():
            declared = str(json.loads(manifest.read_text(encoding='utf-8-sig')).get('game_version', ''))
        version = file_version(folder / data / 'globalgamemanagers', declared)
        if not re.fullmatch(r'\d{1,2}\.\d{1,2}\.\d{1,3}', version):
            raise ValueError('不是一个可用的替换包：版本号无效')
        if declared and version != declared:
            raise ValueError(f'不是一个可用的替换包：{key}声明与文件不一致')
        versions[key] = version
        names = [exe, 'mhypbase.dll', 'pkg_version', 'Audio_Chinese_pkg_version', 'UnityPlayer.dll']
        names += [f'{data}/{name}' for name in DATA_FILES]
        names += [f'{data}/Plugins/{name}' for name in PLUGINS]
        streaming = folder / data / 'StreamingAssets'
        local_tree(streaming, recursive=False)
        names += [file.relative_to(folder).as_posix() for file in streaming.glob('*.blk') if file.is_file()]
        for name in names:
            file = folder / name
            local_tree(file, recursive=False)
            if file.is_file():
                files[f'{PACKAGES[channel]}/{name}'] = file
    if 'cn' in channels:
        # Original-layout extras take precedence over legacy bilibili extras.
        sdk = next((f for f in (base / 'PCGameSDK.dll', base / 'bilibili/PCGameSDK.dll') if f.is_file()), None)
        if sdk:
            local_tree(sdk, recursive=False)
            files['PCGameSDK.dll'] = sdk
        login = next((f for f in (base / '原神B服新登录框窗口/BLPlatform64',
                                  base / 'bilibili/BLPlatform64') if f.is_dir()), None)
        if login:
            local_tree(login)
            for file in login.rglob('*'):
                cancelled(worker)
                if file.is_file():
                    files[f'原神B服新登录框窗口/BLPlatform64/{file.relative_to(login).as_posix()}'] = file
    return files, versions, channels


def import_package(params, service, worker):
    worker.progress.emit({'message': '识别中…'})
    cancelled(worker)
    value = params.get('source')
    if not isinstance(value, str) or not value.strip():
        raise ValueError('不是一个替换包：请拖入一个文件夹')
    source = Path(value).absolute()
    local_tree(source, recursive=False)
    if not source.is_dir():
        raise ValueError('不是一个替换包：请拖入一个文件夹')
    root = service.root.absolute()
    local_tree(root, recursive=False)
    target = root / '替换包'
    local_tree(target)
    if source == root or source in root.parents or source == target or target in source.parents:
        raise ValueError('请不要把正在使用的替换包目录拖入自身')
    game = service.config.snapshot()['settings'].get('game_folder', '').strip()
    if game:
        game = Path(game).absolute()
        if source == game or source in game.parents or game in source.parents:
            raise ValueError('请拖入替换包，不要拖入当前游戏目录')
    if (root / 'pending.json').exists():
        raise ValueError('请先恢复未完成的切换，再导入替换包')
    existing = service.native_root()
    if existing is not None and existing != target:
        raise ValueError('其他位置已存在替换包，请先整理到 server-switch\\替换包')
    try:
        files, versions, channels = collect(source, worker)
    except (OSError, ValueError, configparser.Error) as exc:
        cancelled(worker)
        if str(exc).startswith('不是一个'):
            raise
        raise ValueError(f'不是一个替换包：{exc}') from exc
    # Once a native package exists, the switcher reads both channels there.
    # Carry forward a usable opposite legacy channel so partial imports do not
    # make an existing server unavailable. Original legacy folders stay intact.
    if existing is None:
        for channel in PACKAGES:
            folder = root / channel
            if channel not in channels and folder.is_dir():
                try:
                    old_files, old_versions, old_channels = collect(
                        root, worker, located=(root, {channel: folder}))
                except (OSError, ValueError, configparser.Error):
                    cancelled(worker)
                    continue
                files.update(old_files)
                versions.update(old_versions)
                channels.update(old_channels)
        if 'cn' in channels and 'PCGameSDK.dll' not in files and (root / 'cn').is_dir():
            try:
                legacy, legacy_versions, _ = collect(root, worker, located=(root, {'cn': root / 'cn'}))
                local_tree(root / 'bilibili/manifest.json', recursive=False)
                b_version = json.loads((root / 'bilibili/manifest.json').read_text(encoding='utf-8-sig')).get('game_version')
                if legacy_versions['国服版本'] == versions['国服版本'] == b_version:
                    files.update({name: file for name, file in legacy.items()
                                  if name == 'PCGameSDK.dll' or name.startswith('原神B服新登录框窗口/')})
            except (OSError, ValueError, configparser.Error):
                cancelled(worker)
    cancelled(worker)
    root.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    stage = root / f'.server-import-{token}'
    stage.mkdir()
    changes = []
    target_created = not target.exists()
    history = target / '.history' / token
    try:
        total = sum(file.stat().st_size for file in files.values())
        done = 0
        for rel, file in files.items():
            cancelled(worker)
            local_tree(file, recursive=False)
            before = file.stat()
            dest = stage / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            with file.open('rb') as reader, dest.open('xb') as writer:
                while chunk := reader.read(4 * 1024 * 1024):
                    cancelled(worker)
                    writer.write(chunk)
                    done += len(chunk)
                    worker.progress.emit({'message': f'正在导入 {rel}',
                                          'progress': .1 + .85 * min(1, done / max(1, total))})
            after = file.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError('替换包文件已变化，请重新导入')
            shutil.copystat(file, dest)
        ini = read_ini(target / '版本号.ini') if (target / '版本号.ini').exists() else configparser.ConfigParser(interpolation=None)
        if not ini.has_section('配置'):
            ini.add_section('配置')
        ini['配置'].update(versions)
        for channel in channels:
            key = '国服版本' if channel == 'cn' else '外服版本'
            if file_version(stage / PACKAGES[channel] / DATA[channel] / 'globalgamemanagers', versions[key]) != versions[key]:
                raise ValueError('替换包版本已变化，请重新导入')
        stream = io.StringIO()
        ini.write(stream, space_around_delimiters=False)
        (stage / '版本号.ini').write_text(stream.getvalue(), encoding='utf-8-sig')
        cancelled(worker)
        local_tree(target)
        target.mkdir(exist_ok=True)
        names = [PACKAGES[channel] for channel in channels]
        if 'cn' in channels:
            names += ['PCGameSDK.dll', '原神B服新登录框窗口']
        names.append('版本号.ini')
        try:
            for name in names:
                cancelled(worker)
                dest = target / name
                local_tree(dest)
                change = {'name': name, 'saved': False, 'published': False}
                changes.append(change)
                if dest.exists():
                    local_tree(history, recursive=False)
                    history.mkdir(parents=True, exist_ok=True)
                    dest.rename(history / name)
                    change['saved'] = True
                if (stage / name).exists():
                    (stage / name).rename(dest)
                    change['published'] = True
            cancelled(worker)
        except Exception:
            for change in reversed(changes):
                dest = target / change['name']
                if change['published']:
                    shutil.rmtree(dest) if dest.is_dir() else dest.unlink()
                if change['saved']:
                    (history / change['name']).rename(dest)
            raise
        worker.progress.emit({'message': '替换包已导入', 'progress': 1})
        return {'message': f'替换包已导入（{len(files)} 个文件）', 'path': str(target), 'count': len(files)}
    finally:
        # Only this request's uniquely created staging tree is disposable.
        if stage.exists():
            shutil.rmtree(stage)
        if target_created and target.exists() and not any(target.iterdir()):
            target.rmdir()
