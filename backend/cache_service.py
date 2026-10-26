"""Cleanup of explicitly owned disposable data, never arbitrary user paths."""
from pathlib import Path
import os
import logging
import re
import shutil
import stat
import time


class CacheService:
    def __init__(self, root):
        self.root = Path(os.path.abspath(root))

    def inspect(self, path):
        """Validate before traversing; reject junctions and even dangling links."""
        path.relative_to(self.root)
        chain = [path, *path.parents]
        for part in chain[:chain.index(self.root) + 1]:
            if part.is_symlink() or (part.exists() and getattr(part.lstat(), 'st_file_attributes', 0)
                                    & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                raise ValueError(f'缓存或备份中存在链接，未执行清理：{part}')
        info = path.stat()
        size, modified = (info.st_size if path.is_file() else 0), info.st_mtime_ns
        if path.is_dir():
            for child in path.iterdir():
                child_size, child_modified = self.inspect(child)
                size += child_size
                modified = max(modified, child_modified)
        return size, modified

    def groups(self):
        # Each immediate child is one complete generation (directory or file).
        for relative in ('cache', 'resource-backups', 'dll-backups',
                         'build-work/temp', 'server-switch/备份包/.history',
                         'server-switch/替换包/.history',
                         'server-switch/原神资源替换包/.history',
                         'server-switch/.history'):
            yield self.children(self.root / relative)
        # A pending transaction owns recovery copies; never remove any of them.
        if not os.path.lexists(self.root / 'server-switch/pending.json'):
            yield self.children(self.root / 'server-switch/backups')
        # TEMP also contains the running frozen Python runtime. Only select
        # known Neo operation names, never _MEI directories or unknown files.
        temporary = self.children(self.root / 'temp')
        for prefix in ('injection-', 'omg_gimi_rollback_'):
            yield [p for p in temporary if p.name.startswith(prefix)]
        yield [p for p in temporary if p.name == 'omg_gimi_latest.zip']
        yield [p for p in self.children(self.root) if p.name.startswith('update-') and p.is_dir()]
        switch = self.children(self.root / 'server-switch')
        yield [p for p in switch if re.fullmatch(r'\.server-import-[0-9a-f]{32}', p.name)]
        yield [p for p in self.children(self.root / 'server-switch/备份包')
               if re.fullmatch(r'\.server-backup-[0-9a-f]{32}', p.name)]
        # Atomic-write leftovers, only at exact known managed paths.
        yield [p for p in self.children(self.root) if p.name in (
            'config.json.tmp', 'build-options.tmp', 'build-products.tmp',
            'resource-cards.tmp')]
        if not os.path.lexists(self.root / 'server-switch/pending.json'):
            yield [p for p in switch if p.name == 'pending.tmp']
        # The current service log stays open on Windows. Preserve every active
        # handler's file and rotations; explicitly exported logs are user output.
        active = set()
        for logger in [logging.getLogger(), *logging.Logger.manager.loggerDict.values()]:
            if isinstance(logger, logging.Logger):
                for handler in logger.handlers:
                    if getattr(handler, 'baseFilename', None):
                        active.add(os.path.normcase(os.path.abspath(handler.baseFilename)))
        logs = self.children(self.root / 'log')
        for prefix in ('omg_', 'injector-'):
            yield [p for p in logs if p.name.startswith(prefix)
                   and (p.suffix == '.log' or re.search(r'\.log\.\d+$', p.name))
                   and not any(os.path.normcase(str(p)) == name or
                               os.path.normcase(str(p)).startswith(name + '.') for name in active)]

    def children(self, folder):
        if not os.path.lexists(folder):
            return []
        # Do not follow links while discovering candidates.
        for part in [folder, *folder.parents]:
            if part.is_symlink() or (part.exists() and getattr(part.lstat(), 'st_file_attributes', 0)
                                    & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                raise ValueError(f'缓存或备份目录不能为链接：{part}')
            if part == self.root:
                break
        return list(folder.iterdir())

    def run(self, *, clear=False, keep_latest=False, progress=None):
        # Build and validate the entire plan before the first deletion.
        last_report = 0.
        def report(value, message, force=False):
            nonlocal last_report
            now = time.monotonic()
            if progress and (force or now - last_report >= .05):
                progress({'progress': value, 'message': message})
                last_report = now
        report(None, '正在统计缓存与备份…', True)
        plan = []
        total = 0
        for group in self.groups():
            entries = []
            for p in group:
                report(None, f'正在扫描 {p.name}')
                entries.append((p, *self.inspect(p)))
            total += sum(size for _, size, _ in entries)
            entries.sort(key=lambda row: (row[2], row[0].name), reverse=True)
            plan.extend(entries[1:] if keep_latest else entries)
        removed, errors = 0, []
        if clear:
            report(0., '正在清理缓存与备份…', True)
            for index, (path, size, _) in enumerate(plan):
                report(index / max(1, len(plan)) * .95, f'正在清理 {path.name}')
                try:
                    self.inspect(path)
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                    removed += size
                except OSError as exc:
                    errors.append(f'{path.name}: {exc}')
        # Rescan so partial deletion or locked files report actual remaining use.
        remaining = sum(self.inspect(p)[0] for group in self.groups() for p in group) if clear else total
        message = f'缓存与备份已清理，释放 {removed / 1024 / 1024:.2f} MB'
        if errors:
            message += '；部分文件清理失败：' + '；'.join(errors)
        report(1., message, True)
        return {'bytes': remaining, 'clearedBytes': removed, 'errors': errors, 'message': message}
