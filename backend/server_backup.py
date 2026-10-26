"""Export original-switcher-compatible differential backups, without editing games."""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
import shutil
import uuid
from server_switch import DATA, identify_game, local_tree, read_ini

PLUGINS = ('cri_mana_vpx.dll', 'cri_vip_unity_pc.dll', 'cri_ware_unity.dll',
           'd3dcompiler_43.dll', 'd3dcompiler_47.dll', 'hdiffz.dll', 'hpatchz.dll',
           'mihoyonet.dll', 'Mmoron.dll', 'MTBenchmark_Windows.dll', 'NamedPipeClient.dll',
           'UnityNativeChromaSDK.dll', 'UnityNativeChromaSDK3.dll', 'xlua.dll')
DATA_FILES = ('app.info', 'globalgamemanagers', 'globalgamemanagers.assets',
              'globalgamemanagers.assets.resS', 'upload_crash.exe',
              'Managed/Metadata/global-metadata.dat', 'Native/UserAssembly.dll',
              'Native/UserAssembly.exp', 'Native/UserAssembly.lib',
              'Native/Data/Metadata/global-metadata.dat',
              'Native/Data/Metadata/startup-metadata.dat')


def backup_plan(params, config, resource_root):
    source = str(params.get('source') or config.snapshot()['settings'].get('game_folder', '')).strip()
    output = str(params.get('destination') or '').strip() or str(Path(resource_root) / '备份包')
    channel = params.get('channel')
    if channel not in ('cn', 'global') or not source or not output:
        raise ValueError('请选择国服或外服，并指定游戏目录和备份输出父目录')
    game, parent = Path(source).absolute(), Path(output).absolute()
    local_tree(game, recursive=False)
    local_tree(parent, recursive=False)
    game, parent = game.resolve(), parent.resolve()
    if not game.is_dir():
        raise ValueError('游戏目录不存在')
    resource_root = Path(resource_root).resolve()
    if parent == game or game in parent.parents or parent in game.parents:
        raise ValueError('备份路径与游戏目录不能互相包含')
    if (parent == resource_root or resource_root in parent.parents or parent in resource_root.parents) and parent != resource_root / '备份包':
        raise ValueError('请使用默认备份包目录，或选择替换资源目录之外的输出目录')
    info = identify_game(game)
    if ('global' if info['current'] == 'global' else 'cn') != channel:
        raise ValueError('所选备份类型与游戏渠道不符，请检查文件结构')
    version = info['version']
    data = DATA[channel]
    exe = 'YuanShen.exe' if channel == 'cn' else 'GenshinImpact.exe'
    package = '原神米哈游官服' if channel == 'cn' else '原神国际服'
    names = [exe, 'mhypbase.dll', 'pkg_version', 'Audio_Chinese_pkg_version', 'UnityPlayer.dll']
    names += [f'{data}/{name}' for name in DATA_FILES]
    names += [f'{data}/Plugins/{name}' for name in PLUGINS]
    required = [exe, 'mhypbase.dll', 'pkg_version', f'{data}/app.info',
                f'{data}/globalgamemanagers', f'{data}/globalgamemanagers.assets',
                f'{data}/globalgamemanagers.assets.resS',
                f'{data}/Native/Data/Metadata/global-metadata.dat',
                f'{data}/Native/Data/Metadata/startup-metadata.dat']
    for name in required:
        if not (game / name).is_file():
            raise ValueError(f'游戏缺少必要文件，不能生成可用替换包：{name}')
    files, missing = {}, []
    for name in names:
        if (game / name).is_file():
            files[f'{package}/{name}'] = game / name
        else:
            missing.append(name)
    # Original binary contains a root StreamingAssets path and the *.blk mask.
    local_tree(game / data / 'StreamingAssets', recursive=False)
    for file in sorted((game / data / 'StreamingAssets').glob('*.blk')):
        if file.is_file():
            files[f'{package}/{data}/StreamingAssets/{file.name}'] = file
    if channel == 'cn':
        sdk = game / data / 'Plugins/PCGameSDK.dll'
        if sdk.is_file():
            files['PCGameSDK.dll'] = sdk
        login = game / data / 'Plugins/BLPlatform64'
        if login.is_dir():
            for file in sorted(login.rglob('*')):
                if file.is_file():
                    files[f'原神B服新登录框窗口/BLPlatform64/{file.relative_to(login).as_posix()}'] = file
    for file in files.values():
        local_tree(file, recursive=False)
    return {'game': str(game), 'destination': str(parent), 'channel': channel,
            'version': version, 'files': files, 'missing': missing,
            'bytes': sum(file.stat().st_size for file in files.values())}


def preview(params, config, resource_root):
    plan = backup_plan(params, config, resource_root)
    return {**plan, 'files': list(plan['files']), 'count': len(plan['files'])}


def export(params, config, resource_root, game_stopped, worker):
    plan = backup_plan(params, config, resource_root)
    settings = dict(config.snapshot()['settings'], game_folder=plan['game'])
    game_stopped(settings)
    parent = Path(plan['destination'])
    parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    final = parent
    stage = parent / f'.server-backup-{token}'
    stage.mkdir()
    done, report = 0, []
    try:
        for rel, source in plan['files'].items():
            dest = stage / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            with source.open('rb') as reader, dest.open('xb') as writer:
                while True:
                    if worker.cancel.is_set():
                        raise ValueError('备份已取消')
                    chunk = reader.read(4 * 1024 * 1024)
                    if not chunk:
                        break
                    writer.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                    done += len(chunk)
                    worker.progress.emit({'message': f'正在备份 {rel}',
                                          'progress': min(.99, done / max(1, plan['bytes']))})
            shutil.copystat(source, dest)
            report.append({'path': rel, 'bytes': size, 'sha256': digest.hexdigest()})
        if identify_game(Path(plan['game']))['version'] != plan['version']:
            raise ValueError('备份期间游戏版本发生变化，请退出启动器后重试')
        import configparser
        version_ini = configparser.ConfigParser(interpolation=None)
        if (parent / '版本号.ini').is_file():
            version_ini = read_ini(parent / '版本号.ini')
        if not version_ini.has_section('配置'):
            version_ini.add_section('配置')
        version_ini['配置'].update({
            '国服版本' if plan['channel'] == 'cn' else '外服版本': plan['version'],
            '替换包版本号': plan['version'], '备份工具': 'OMG-Neo',
            '备份功能版本': '原切换器静态清单 + StreamingAssets 根目录 *.blk'})
        stream = io.StringIO()
        version_ini.write(stream, space_around_delimiters=False)
        (stage / '版本号.ini').write_text(stream.getvalue(), encoding='utf-8-sig')
        (stage / 'backup-report.json').write_text(json.dumps({
            'channel': plan['channel'], 'game_version': plan['version'],
            'files': report, 'missingOptional': plan['missing']}, ensure_ascii=False, indent=2), encoding='utf-8')
        if worker.cancel.is_set():
            raise ValueError('备份已取消')
        # Publish only this backup's top-level entries. Keep the other channel
        # untouched and retain overwritten entries as a recoverable history.
        history = parent / '.history' / token
        changes = []
        local_tree(history, recursive=False)
        try:
            names = [item.name for item in stage.iterdir() if item.name != '版本号.ini']
            if plan['channel'] == 'cn':
                names += [name for name in ('PCGameSDK.dll', '原神B服新登录框窗口') if name not in names]
            names.append('版本号.ini')
            for name in names:
                if worker.cancel.is_set():
                    raise ValueError('备份已取消')
                dest = parent / name
                local_tree(dest)
                change = {'name': name, 'saved': False, 'published': False}
                changes.append(change)
                if dest.exists():
                    history.mkdir(parents=True, exist_ok=True)
                    dest.rename(history / name)
                    change['saved'] = True
                if (stage / name).exists():
                    (stage / name).rename(dest)
                    change['published'] = True
        except Exception:
            for change in reversed(changes):
                dest = parent / change['name']
                if change['published']:
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()
                if change['saved']:
                    (history / change['name']).rename(dest)
            raise
        stage.rmdir()
    except Exception:
        # Only the uniquely created staging directory is disposable.
        if stage.parent == parent and stage.name == f'.server-backup-{token}':
            if stage.exists():
                shutil.rmtree(stage)
        raise
    return {'message': f'备份完成：{final}（{len(report)} 个文件）', 'path': str(final),
            'count': len(report), 'missingOptional': plan['missing']}
