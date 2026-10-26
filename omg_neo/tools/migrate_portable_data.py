"""Move this machine's legacy Neo data into this project's portable release.

Copies and verifies every file before deleting any source file. Both backend
locks are held throughout; links and preexisting conflicting files are refused.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import time
from contextlib import ExitStack

APP = Path(__file__).resolve().parents[1]


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def entries(root):
    files, directories = [], []
    stack = [root]
    while stack:
        folder = stack.pop()
        for entry in folder.iterdir():
            info = entry.lstat()
            if entry.is_symlink() or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise RuntimeError(f"Migration refuses links: {entry}")
            if entry.is_dir():
                directories.append(entry)
                stack.append(entry)
            elif entry.name != ".backend.lock":
                files.append(entry)
    return files, directories


def lock(root, stack):
    import msvcrt
    handle = stack.enter_context((root / ".backend.lock").open("a+b"))
    handle.seek(0)
    if not handle.read(1):
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)


def migrate():
    source = Path(os.environ["LOCALAPPDATA"]) / "ObjNotFound/OMGNeo"
    destination = APP / "dist/OMG-Neo/AppData"
    source, destination = source.absolute(), destination.absolute()
    if not source.exists():
        print(f"No legacy data to migrate: {source}")
        return
    # Fixed, named roots; no recursive delete/move may escape these locations.
    assert source == Path(os.environ["LOCALAPPDATA"]).absolute() / "ObjNotFound/OMGNeo"
    assert destination == APP.absolute() / "dist/OMG-Neo/AppData"
    for root in (source, destination):
        current = root
        while True:
            if current.exists() and (current.is_symlink() or getattr(current.lstat(), "st_file_attributes", 0)
                                     & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                raise RuntimeError(f"Migration root contains a link: {current}")
            if current.parent == current:
                break
            current = current.parent
    destination.mkdir(parents=True, exist_ok=True)
    report = {"source": str(source), "destination": str(destination), "files": [], "bytes": 0}
    with ExitStack() as locks:
        lock(source, locks)
        lock(destination, locks)
        files, directories = entries(source)
        entries(destination)  # Refuse links before merging into an existing root.
        manifest = []
        for path in files:
            target = destination / path.relative_to(source)
            checksum = digest(path)
            if target.exists() and digest(target) != checksum:
                raise RuntimeError(f"Destination conflict, source untouched: {target}")
            manifest.append((path, target, checksum))
        for path in directories:
            (destination / path.relative_to(source)).mkdir(parents=True, exist_ok=True)
        for path, target, checksum in manifest:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(path, target)
            if digest(target) != checksum or digest(path) != checksum:
                raise RuntimeError(f"Verification failed, source retained: {path}")
            report["files"].append({"path": path.relative_to(source).as_posix(), "sha256": checksum})
            report["bytes"] += path.stat().st_size
        # Rebase persisted references to managed artifacts, not game/mod paths.
        def rebase(value):
            if isinstance(value, dict):
                return {rebase(key): rebase(item) for key, item in value.items()}
            if isinstance(value, list):
                return [rebase(item) for item in value]
            if isinstance(value, str):
                normalized, prefix = value.replace("\\", "/"), source.as_posix()
                if normalized.casefold() == prefix.casefold() or normalized.casefold().startswith(prefix.casefold() + "/"):
                    return destination.as_posix() + normalized[len(prefix):]
            return value
        for _, target, _ in manifest:
            if target.suffix.lower() not in (".json", ".bak"):
                continue
            try:
                value = json.loads(target.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError):
                continue
            updated = rebase(value)
            if updated != value:
                temporary = target.with_suffix(target.suffix + ".migration-tmp")
                temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(temporary, target)
        # Validate all copies/rewritten JSON before removing the old files.
        for path, target, checksum in manifest:
            assert path.absolute().is_relative_to(source)
            assert target.absolute().is_relative_to(destination)
            if digest(path) != checksum:
                raise RuntimeError(f"Source changed, migration not removed: {path}")
            if not target.is_file():
                raise RuntimeError(f"Missing copy: {target}")
        report_path = destination / f"migration-{time.strftime('%Y%m%d-%H%M%S')}.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        for path, _, _ in manifest:
            path.unlink()
        for path in sorted(directories, key=lambda p: len(p.parts), reverse=True):
            path.rmdir()  # Never recursively delete an unchecked computed path.
    (source / ".backend.lock").unlink()
    source.rmdir()
    print(f"Migrated {len(files)} files / {report['bytes']} bytes")
    print(f"Data: {destination}")
    print(f"Legacy C-drive data removed: {source}")
    print(f"Verification report: {report_path}")


if __name__ == "__main__":
    migrate()
