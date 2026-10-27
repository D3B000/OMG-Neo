"""Apply the bundled updater on application startup, without launching a console."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import threading
import time

UPDATER = 'OMG-Neo-Updater.exe'


def _plain(path: Path):
    for entry in (path, *path.parents):
        if entry.exists() or entry.is_symlink():
            mode = entry.lstat()
            if stat.S_ISLNK(mode.st_mode) or getattr(mode, 'st_file_attributes', 0) & 0x400:
                raise ValueError(f'Updater handoff path contains a link: {entry}')


def _digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


@contextmanager
def _lock(path):
    _plain(path)
    with path.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            stream.write(b'0')
            stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def apply_pending_updater(install: Path, *, timeout=60, retry_delay=.25) -> bool:
    """Leave the pending payload intact on sharing violations or validation errors.

    Windows refuses replacing an executing EXE. Retry only that small atomic
    replace, off the UI thread, until the old updater/bootloader has exited.
    """
    install = Path(install).absolute()
    pending = install / '.updater-pending'
    metadata, incoming, target = pending / 'manifest.json', pending / UPDATER, install / UPDATER
    for path in (metadata, incoming, target, install / (UPDATER + '.sha256')):
        _plain(path)
    if not metadata.is_file():
        return False
    with _lock(pending / '.lock'):
        if not metadata.exists():
            return False
        if metadata.stat().st_size > 4096:
            raise ValueError('Updater handoff manifest is too large')
        record = json.loads(metadata.read_text(encoding='utf-8'))
        checksum = record.get('sha256', '')
        if record.get('schema') != 1 or not re.fullmatch('[a-f0-9]{64}', checksum):
            raise ValueError('Invalid updater handoff manifest')
        if incoming.exists():
            if _digest(incoming) != checksum:
                raise ValueError('Pending updater checksum mismatch')
            deadline = time.monotonic() + timeout
            while True:
                try:
                    os.replace(incoming, target)
                    break
                except OSError as error:
                    if getattr(error, 'winerror', None) not in (5, 32, 33) and not isinstance(error, PermissionError):
                        raise
                    if time.monotonic() >= deadline:
                        return False
                    time.sleep(retry_delay)
        elif not target.is_file() or _digest(target) != checksum:
            raise ValueError('Pending updater payload is missing')
        # A crash after os.replace is harmless: next startup finishes the sidecar.
        (install / (UPDATER + '.sha256')).write_text(f'{checksum}  {UPDATER}\n', encoding='ascii')
        metadata.unlink()
        return True


def start_pending_updater(install: Path):
    def worker():
        try:
            apply_pending_updater(install)
        except Exception as error:
            # stderr is the backend diagnostic stream, never the protocol pipe.
            print(f'Updater handoff deferred: {error}', file=sys.stderr)
    thread = threading.Thread(target=worker, name='updater-handoff', daemon=True)
    thread.start()
    return thread
