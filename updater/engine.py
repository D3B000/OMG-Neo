"""Local, journaled portable-directory updater. No application code is executed."""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable
import hashlib
import json
import os
import re
import shutil
import stat
import struct
import sys
import uuid
import zipfile

from platform_ops import exclusive_lock, inside, running_processes

MANIFEST = 'update-manifest.json'
UPDATER_EXE = 'OMG-Neo-Updater.exe'
PENDING_UPDATER = '.updater-pending'
MAX_BYTES = 8 * 1024**3
MAX_FILES = 30000
RESERVED = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
            *(f'LPT{i}' for i in range(1, 10))}
TERMINAL = {'installed', 'rolled_back', 'aborted'}


class UpdateError(RuntimeError):
    pass


def digest(path: Path, progress=None) -> str:
    with path.open('rb') as stream:
        if progress is None:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
        result, done, total = hashlib.sha256(), 0, path.stat().st_size
        progress(0, total)
        while chunk := stream.read(1024 * 1024):
            result.update(chunk)
            done += len(chunk)
            progress(done, total)
        return result.hexdigest()


def linked(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def safe_path(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    for candidate in [path, *path.parents]:
        if candidate.exists() or candidate.is_symlink():
            if linked(candidate):
                raise UpdateError(f'路径含符号链接或目录联接：{candidate}')
    return path


def safe_tree(root: Path):
    safe_path(root)
    if not root.exists():
        return
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            if linked(path):
                raise UpdateError(f'目录中存在链接，未操作：{path}')


def safe_program(root: Path):
    """Inspect only managed roots; user directories are never traversed."""
    safe_path(root)
    if root.exists():
        for entry in root.iterdir():
            if managed(entry.name):
                safe_tree(entry)


def managed(name: str) -> bool:
    lower = name.lower()
    return lower in {'omg_neo.exe', 'data', 'backend', PENDING_UPDATER, 'native_assets.json',
                     'readme.txt', 'launch.ps1', MANIFEST} or lower.endswith(('.dll', '.pdb'))


def bundled_updater(name: str) -> bool:
    return name.lower() in {UPDATER_EXE.lower(), UPDATER_EXE.lower() + '.sha256'}


def checked_name(name: str) -> tuple[str, ...]:
    if '\\' in name or name.startswith('/'):
        raise UpdateError(f'ZIP 路径不合法：{name}')
    parts = tuple(name.rstrip('/').split('/'))
    for part in parts:
        if (not part or part in {'.', '..'} or part[-1:] in {' ', '.'}
                or re.search(r'[<>:"|?*\x00-\x1f]', part)
                or part.split('.')[0].upper() in RESERVED):
            raise UpdateError(f'ZIP 路径不合法：{name}')
    return parts


def verify_pe(path: Path):
    with path.open('rb') as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:2] != b'MZ':
            raise UpdateError(f'不是 Windows EXE/DLL：{path.name}')
        offset = struct.unpack_from('<I', header, 60)[0]
        if offset > path.stat().st_size - 6:
            raise UpdateError(f'PE 头无效：{path.name}')
        stream.seek(offset)
        if stream.read(6) != b'PE\0\0\x64\x86':
            raise UpdateError(f'需要 Windows x64 程序：{path.name}')


def validate_payload(root: Path, *, verify_manifest: bool = True, progress=None) -> dict:
    for name in ('omg_neo.exe', 'flutter_windows.dll', 'backend/omg_backend.exe',
                 'backend/omg_injector.exe', 'data/icudtl.dat'):
        if not (root / name).is_file():
            raise UpdateError(f'更新包不完整，缺少 {name}')
    for name in ('data/flutter_assets', 'backend/_internal'):
        if not (root / name).is_dir() or not any((root / name).iterdir()):
            raise UpdateError(f'更新包不完整，缺少运行资源 {name}')
    debug = (root / 'data/flutter_assets/kernel_blob.bin').is_file()
    release = (root / 'data/app.so').is_file()
    if debug == release:
        raise UpdateError('更新包须明确包含一种 Debug 或 Release 前端。')
    for name in ('omg_neo.exe', 'flutter_windows.dll', 'backend/omg_backend.exe', 'backend/omg_injector.exe'):
        verify_pe(root / name)
    metadata = {'version': '未附版本清单', 'configuration': 'Debug' if debug else 'Release'}
    manifest_path = root / MANIFEST
    if verify_manifest and manifest_path.exists():
        if manifest_path.stat().st_size > 16 * 1024**2:
            raise UpdateError('更新清单过大。')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
        if (manifest.get('schema') != 1 or manifest.get('product') != 'OMG-Neo'
                or manifest.get('configuration') != metadata['configuration']
                or not isinstance(manifest.get('version'), str)):
            raise UpdateError('更新清单产品、格式或模式不匹配。')
        expected = manifest.get('files')
        actual = {}
        for entry in root.iterdir():
            if managed(entry.name) and entry.name not in {MANIFEST, PENDING_UPDATER}:
                for p in entry.rglob('*') if entry.is_dir() else [entry]:
                    if p.is_file():
                        actual[p.relative_to(root).as_posix()] = p
        if not isinstance(expected, dict) or set(expected) != set(actual):
            raise UpdateError('更新清单与包内文件不一致。')
        total_bytes = sum(p.stat().st_size for p in actual.values())
        checked = 0
        for name, path in actual.items():
            record = expected[name]
            report = (lambda done, total: progress('校验程序文件', name, checked + done, total_bytes)) if progress else None
            if record.get('size') != path.stat().st_size or record.get('sha256') != digest(path, report):
                raise UpdateError(f'文件校验失败：{name}')
            checked += path.stat().st_size
        metadata['version'] = manifest['version']
    return metadata


@dataclass
class Package:
    path: Path
    sha256: str
    hash_verified: bool
    files: list[tuple[str, str, int]]
    size: int


def resolve_sha256(value: str, package: Path) -> str:
    value = value.strip()
    if re.fullmatch('[a-fA-F0-9]{64}', value):
        return value.lower()
    if value:
        sidecar = safe_path(Path(value.strip('"').strip("'")))
        if sidecar.suffix.lower() != '.sha256' or not sidecar.is_file():
            raise UpdateError('请输入 64 位 SHA-256，或有效的 .sha256 文件路径。')
    else:
        sidecar = next((p for p in (package.with_suffix('.zip.sha256'), package.with_suffix('.sha256'))
                        if p.exists()), None)
        if sidecar is None:
            return ''
        safe_path(sidecar)
    if sidecar.stat().st_size > 4096:
        raise UpdateError('SHA-256 校验文件过大。')
    fields = sidecar.read_text(encoding='utf-8-sig').strip().split(maxsplit=1)
    if not fields or not re.fullmatch('[a-fA-F0-9]{64}', fields[0]):
        raise UpdateError('SHA-256 校验文件内容无效。')
    if len(fields) == 2 and fields[1].lstrip('*') != package.name:
        raise UpdateError('SHA-256 校验文件中的包名不匹配。')
    return fields[0].lower()


def inspect_package(path: Path, expected_sha256: str = '', progress=None) -> Package:
    path = safe_path(path)
    if not path.is_file() or path.suffix.lower() != '.zip':
        raise UpdateError('请选择完整的 OMG-Neo ZIP 分发包。')
    expected_sha256 = resolve_sha256(expected_sha256, path)
    actual_hash = digest(path, progress)
    if expected_sha256 and (not re.fullmatch('[a-fA-F0-9]{64}', expected_sha256)
                            or actual_hash != expected_sha256.lower()):
        raise UpdateError('更新包 SHA-256 不匹配。')
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_FILES:
            raise UpdateError('更新包文件数量超过限制。')
        # ZipInfo normalizes backslashes and truncates at NUL on Windows. Inspect
        # the original central-directory spelling before that normalization.
        names = [checked_name(entry.orig_filename) for entry in entries]
        roots = [parts[:-1] for entry, parts in zip(entries, names)
                 if not entry.is_dir() and parts[-1].lower() == 'omg_neo.exe']
        if len(roots) != 1 or len(roots[0]) > 1:
            raise UpdateError('请选择只有一套程序、至多一层外目录的更新包。')
        prefix = roots[0]
        files, seen, kinds = [], set(), {}
        total = 0
        for entry, parts in zip(entries, names):
            mode = entry.external_attr >> 16
            if (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)
                    or entry.external_attr & 0x400 or entry.flag_bits & 1):
                raise UpdateError(f'拒绝链接、特殊文件或加密条目：{entry.filename}')
            if parts == prefix and entry.is_dir():
                continue
            if parts[:len(prefix)] != prefix or len(parts) <= len(prefix):
                raise UpdateError('ZIP 外目录含额外文件。')
            relative = parts[len(prefix):]
            if (relative[0].lower() == PENDING_UPDATER or relative[0].lower().endswith('.pdb')
                    or not (managed(relative[0]) or bundled_updater(relative[0]))):
                raise UpdateError(f'更新包含非程序文件或用户数据：{relative[0]}')
            if len(relative) > 1 and relative[0].lower() not in {'data', 'backend'}:
                raise UpdateError(f'程序根文件不能是目录：{relative[0]}')
            key = '/'.join(relative).casefold()
            if key in seen:
                raise UpdateError(f'ZIP 存在重复／大小写冲突路径：{entry.filename}')
            seen.add(key)
            kinds[key] = entry.is_dir()
            if not entry.is_dir():
                total += entry.file_size
                if total > MAX_BYTES:
                    raise UpdateError('更新包解压体积超过 8 GiB。')
                files.append((entry.filename, '/'.join(relative), entry.file_size))
        for key in seen:
            for parent in PurePosixPath(key).parents:
                if str(parent) != '.' and kinds.get(str(parent)) is False:
                    raise UpdateError('ZIP 文件与目录路径冲突。')
    return Package(path, actual_hash, bool(expected_sha256), files, total)


def write_manifest(root: Path, version: str, configuration: str):
    safe_tree(root)
    if any(not (managed(path.name) or bundled_updater(path.name)) for path in root.iterdir()):
        raise UpdateError('只能为不含用户数据的洁净分发目录生成清单。')
    # Producer operation: rebuild after final packaging metadata (README) changes.
    # Installation still verifies the existing manifest with the default True.
    metadata = validate_payload(root, verify_manifest=False)
    if metadata['configuration'] != configuration or not version.strip():
        raise UpdateError('清单模式与前端产物不一致，或版本为空。')
    files = {p.relative_to(root).as_posix(): {'size': p.stat().st_size, 'sha256': digest(p)}
             for p in sorted(root.rglob('*')) if p.is_file() and p.name != MANIFEST
             and managed(p.relative_to(root).parts[0])}
    atomic_json(root / MANIFEST, {'schema': 1, 'product': 'OMG-Neo', 'version': version,
                                'configuration': configuration, 'files': files})


def atomic_json(path: Path, value: dict):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class Updater:
    def __init__(self, target: Path, progress: Callable = lambda *args: None,
                 process_check: Callable = running_processes):
        self.target = safe_path(target)
        if self.target == self.target.parent:
            raise UpdateError('不能将磁盘根目录作为安装目录。')
        self.workspace = self.target.parent / f'.{self.target.name}.updates'
        safe_path(self.workspace)
        self.progress = progress
        self.process_check = process_check

    def idle(self):
        if getattr(sys, 'frozen', False) and inside(Path(sys.executable), self.target):
            if managed(Path(sys.executable).absolute().relative_to(self.target).parts[0]):
                raise UpdateError('更新器不能放在待替换的 backend 或 data 等程序目录内。')
        if inside(Path.cwd(), self.target):
            relative = Path.cwd().relative_to(self.target)
            if relative.parts and managed(relative.parts[0]):
                raise UpdateError('请从 OMG-Neo 根目录或 updater 目录启动，避免占用程序目录。')
        running = self.process_check(self.target)
        if running:
            raise UpdateError('请正常退出以下程序后重试：\n' + '\n'.join(running))

    def current(self):
        safe_program(self.target)
        if not (self.target / 'omg_neo.exe').is_file() or not (self.target / 'backend').is_dir() or not (self.target / 'data').is_dir():
            raise UpdateError('目标不是完整的 OMG-Neo 安装目录。')

    def transactions(self) -> list[tuple[Path, dict]]:
        safe_path(self.workspace)
        result = []
        if self.workspace.exists():
            for path in sorted(self.workspace.glob('*/journal.json'), reverse=True):
                safe_path(path)
                if path.stat().st_size > 65536:
                    raise UpdateError('更新记录过大。')
                record = json.loads(path.read_text(encoding='utf-8'))
                if record.get('target') != str(self.target):
                    raise UpdateError(f'更新记录目标不匹配：{path}')
                result.append((path.parent, record))
        return sorted(result, key=lambda item: str(item[1].get('created', item[0].name)), reverse=True)

    def _locked(self):
        safe_path(self.workspace)
        self.workspace.mkdir(exist_ok=True)
        safe_path(self.workspace / '.lock')
        return exclusive_lock(self.workspace / '.lock')

    @contextmanager
    def _operation(self):
        with self._locked():
            self.current()
            self.idle()
            data = self.target / 'AppData'
            data.mkdir(exist_ok=True)
            safe_path(data / '.backend.lock')
            # Keep the backend lock throughout the program-only replacement.
            # AppData and the installation directory themselves never move.
            with exclusive_lock(data / '.backend.lock'):
                yield

    def _new(self, action: str) -> tuple[Path, dict]:
        pending = [p.name for p, r in self.transactions() if r['state'] not in TERMINAL]
        if pending:
            raise UpdateError('存在未完成事务，请先在恢复菜单处理：' + ', '.join(pending))
        work = self.workspace / (datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
        work.mkdir()
        record = {'schema': 1, 'target': str(self.target), 'action': action,
                  'state': 'preparing', 'created': datetime.now(timezone.utc).isoformat()}
        self._save(work, record, 'preparing')
        return work, record

    def _save(self, work: Path, record: dict, state: str):
        record['state'] = state
        atomic_json(work / 'journal.json', record)

    def _copy(self, source: Path, destination: Path):
        safe_tree(source)
        def copy_file(original, copied):
            original, copied = Path(original), Path(copied)
            total, done = original.stat().st_size, 0
            detail = str(original.relative_to(source.parent))
            self.progress('复制文件', detail, 0, total)
            with original.open('rb') as reader, copied.open('wb') as writer:
                while chunk := reader.read(1024 * 1024):
                    writer.write(chunk)
                    done += len(chunk)
                    self.progress('复制文件', detail, done, total)
            shutil.copystat(original, copied)
            return str(copied)
        if source.is_dir():
            shutil.copytree(source, destination, copy_function=copy_file)
        else:
            copy_file(source, destination)

    def _space(self, size: int):
        required = size + 64 * 1024**2
        if shutil.disk_usage(self.target.parent).free < required:
            raise UpdateError(f'磁盘空间不足，暂存至少需要 {required / 1024**2:.1f} MiB。')

    def _queue_updater(self, stage: Path):
        executable = next((p for p in stage.iterdir() if p.name.lower() == UPDATER_EXE.lower()), None)
        if executable is None:
            return
        verify_pe(executable)
        checksum = digest(executable, lambda done, total:
                          self.progress('暂存新版更新器', UPDATER_EXE, done, total))
        sidecar = next((p for p in stage.iterdir() if p.name.lower() == (UPDATER_EXE + '.sha256').lower()), None)
        if sidecar:
            if resolve_sha256(str(sidecar), executable) != checksum:
                raise UpdateError('随包更新器 SHA-256 不匹配。')
            sidecar.unlink()
        pending = stage / PENDING_UPDATER
        pending.mkdir()
        executable.rename(pending / UPDATER_EXE)
        atomic_json(pending / 'manifest.json', {'schema': 1, 'sha256': checksum})

    def _switch(self, work: Path, record: dict):
        self.idle()
        safe_program(self.target)
        safe_tree(work / 'stage')
        record['strategy'] = 'program-only'
        record['old_entries'] = sorted(p.name for p in self.target.iterdir() if managed(p.name))
        record['new_entries'] = sorted(p.name for p in (work / 'stage').iterdir())
        self._program_entries(record)
        backup = work / 'backup'
        # Persist both lists BEFORE any rename. Recovery also works when a
        # process dies between a rename and the next journal write.
        self._save(work, record, 'switching')
        backup.mkdir()
        for index, name in enumerate(record['old_entries'], 1):
            self.progress('备份旧版本', name, index, len(record['old_entries']))
            (self.target / name).rename(backup / name)
        self._save(work, record, 'backup_ready')
        for index, name in enumerate(record['new_entries'], 1):
            self.progress('替换程序', name, index, len(record['new_entries']))
            (work / 'stage' / name).rename(self.target / name)
        self._save(work, record, 'installed')

    @staticmethod
    def _program_entries(record):
        for field in ('old_entries', 'new_entries'):
            entries = record.get(field)
            if (not isinstance(entries, list) or len(entries) > MAX_FILES
                    or any(not isinstance(n, str) or len(checked_name(n)) != 1
                           or not managed(n) for n in entries)
                    or len({n.casefold() for n in entries}) != len(entries)):
                raise UpdateError('程序替换事务中的路径无效。')

    def _recover_program(self, work: Path, record: dict):
        self._program_entries(record)
        safe_program(self.target)
        for name in ('stage', 'backup', 'failed-install'):
            safe_tree(work / name)
        failed = work / 'failed-install'
        failed.mkdir(exist_ok=True)
        # A missing staged entry means it was installed. An existing failed
        # entry means recovery already removed it (and may have restored old).
        for name in record['new_entries']:
            target = self.target / name
            if not (work / 'stage' / name).exists() and not (failed / name).exists() and target.exists():
                target.rename(failed / name)
        for name in record['old_entries']:
            original = work / 'backup' / name
            if original.exists():
                if (self.target / name).exists():
                    raise UpdateError(f'恢复路径冲突，请保留现场：{name}')
                original.rename(self.target / name)
            elif not (self.target / name).exists():
                raise UpdateError(f'原程序及备份均缺失：{name}')
        self._save(work, record, 'rolled_back')

    def apply(self, archive: Path, expected_sha256: str = '', *, reviewed_sha256: str = '') -> Path:
        with self._operation():
            self.progress('校验更新包', str(archive))
            package = inspect_package(archive, expected_sha256, lambda done, total:
                                      self.progress('校验更新包', archive.name, done, total))
            if reviewed_sha256 and package.sha256 != reviewed_sha256:
                raise UpdateError('预览后更新包已变化，请重新检查并确认。')
            self._space(package.size)
            work, record = self._new('update')
            record.update(package=str(package.path), sha256=package.sha256,
                          hash_verified=package.hash_verified)
            try:
                stage = work / 'stage'
                stage.mkdir()
                with zipfile.ZipFile(package.path) as bundle:
                    for index, (name, relative, _) in enumerate(package.files):
                        output = stage / relative
                        output.parent.mkdir(parents=True, exist_ok=True)
                        with bundle.open(name) as source, output.open('xb') as target:
                            shutil.copyfileobj(source, target, 1024 * 1024)
                        self.progress('解压更新包', relative, index + 1, len(package.files))
                if digest(package.path) != package.sha256:
                    raise UpdateError('校验后 ZIP 已变化，更新已停止。')
                metadata = validate_payload(stage, progress=self.progress)
                record.update(metadata)
                self._queue_updater(stage)
                self._save(work, record, 'ready')
                self._switch(work, record)
            except BaseException:
                self._recover(work, record)
                raise
            return work

    def rollback(self, transaction: Path) -> Path:
        with self._operation():
            records = dict(self.transactions())
            transaction = Path(transaction)
            old = records.get(transaction)
            if not old or old['state'] != 'installed' or not (transaction / 'backup').is_dir():
                raise UpdateError('请选择有旧程序备份的已完成事务。')
            source = transaction / 'backup'
            safe_program(source)
            size = sum(p.stat().st_size for entry in source.iterdir() if managed(entry.name)
                       for p in (entry.rglob('*') if entry.is_dir() else [entry]) if p.is_file())
            self._space(size)
            work, record = self._new('rollback')
            record['from_transaction'] = transaction.name
            try:
                stage = work / 'stage'
                stage.mkdir()
                for path in source.iterdir():
                    if managed(path.name) and not path.name.lower().endswith('.pdb'):
                        self._copy(path, stage / path.name)
                record.update(validate_payload(stage, progress=self.progress))
                self._save(work, record, 'ready')
                self._switch(work, record)
            except BaseException:
                self._recover(work, record)
                raise
            return work

    def recover(self, transaction: Path):
        with self._locked():
            self.idle()
            record = dict(self.transactions()).get(Path(transaction))
            if not record or record['state'] in TERMINAL:
                raise UpdateError('该事务无需中断恢复。')
            self._recover(Path(transaction), record)

    def _recover(self, work: Path, record: dict):
        if record.get('strategy') == 'program-only':
            self._recover_program(work, record)
            return
        safe_tree(work)
        backup = work / 'backup'
        if backup.exists():
            safe_tree(self.target)  # Legacy whole-directory transactions only.
            if self.target.exists():
                self.target.rename(work / 'failed-install')
            backup.rename(self.target)
            self._save(work, record, 'rolled_back')
        elif self.target.exists():
            safe_program(self.target)
            self._save(work, record, 'aborted')
        else:
            raise UpdateError(f'目标和备份均不存在，请保留现场手动恢复：{work}')


def preview_payload(package: Package) -> dict:
    """Read only the optional tiny manifest for the review screen; apply revalidates everything."""
    with zipfile.ZipFile(package.path) as bundle:
        for name, relative, size in package.files:
            if relative == MANIFEST:
                if size > 16 * 1024**2:
                    raise UpdateError('更新清单过大。')
                data = json.loads(bundle.read(name).decode('utf-8-sig'))
                return {'version': data.get('version', '?'), 'configuration': data.get('configuration', '?')}
    return {'version': '旧包未附版本清单', 'configuration': '安装时检查'}
