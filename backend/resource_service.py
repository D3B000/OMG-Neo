"""Strict managed-workspace path helpers and the resource service export.

Build/cache cleanup rejects links. Browsing uses its own junction-aware policy.
"""
from pathlib import Path
import os
import stat


def no_links(path: Path, root: Path):
    """Check lexical containment and every existing component before resolving."""
    path, root = Path(os.path.abspath(path)), Path(os.path.abspath(root))
    relative = path.relative_to(root)
    parts = [root]
    for name in relative.parts:
        parts.append(parts[-1] / name)
    for part in parts:
        if part.exists() and (part.is_symlink() or getattr(part.lstat(), "st_file_attributes", 0)
                              & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)):
            raise ValueError(f"不支持链接或联接目录：{part}")
    path.resolve().relative_to(root.resolve())
    return path


def safe_tree(path: Path, root: Path):
    path = no_links(path, root)
    if not path.is_dir():
        return
    # Containment and ancestors were checked above. Inspect each descendant
    # once without resolving its entire ancestor chain for every file. Reject
    # reparse points before descending, including dangling links and junctions.
    pending = [path]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if (stat.S_ISLNK(info.st_mode) or
                        getattr(info, "st_file_attributes", 0) &
                        getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)):
                    raise ValueError(f"不支持链接或联接目录：{entry.path}")
                if stat.S_ISDIR(info.st_mode):
                    pending.append(entry.path)


from resource_browser import ResourceService
