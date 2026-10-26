"""Mods listings with recursive previews, lazy INI keys and junction-aware operations."""
from collections import OrderedDict
from pathlib import Path
import hashlib
import json
import subprocess
import logging
import os
import shutil
import stat
import time
import uuid
from file_io import sha256_file


class ResourceService:
    def __init__(self, data_root, config):
        from omg.core import mods_manager
        self.mm, self.config = mods_manager, config
        self.data_root = data_root
        self.handles = {}
        self.revision = 0
        self.direct_cache = OrderedDict()
        self.ini_cache = OrderedDict()
        self.preferences_path = self.data_root / "resource-cards.json"
        try:
            self.preferences = json.loads(self.preferences_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.preferences = {}


    @staticmethod
    def token(path):
        try:
            return os.path.normcase(str(path.resolve(strict=True)))
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"目录链接已失效或形成循环：{path}") from exc

    def root(self):
        gimi = self.config.get_gimi_dir()
        if not gimi:
            raise ValueError("请先在设置中配置 GIMI 目录")
        root = Path(os.path.abspath(Path(gimi) / "Mods"))
        if not root.is_dir():
            raise ValueError(f"Mods 目录不存在：{root}")
        return root

    def resource_path(self, path, root):
        path = Path(os.path.abspath(path))
        try:
            relative = path.relative_to(root)
        except ValueError as exc:
            raise ValueError("资源路径超出 Mods 目录") from exc
        # Directory links explicitly present in Mods are user-owned entries,
        # including targets outside Mods. Prevent logical escape and cycles.
        seen = {self.token(root)}
        current = root
        for name in relative.parts:
            current = current / name
            token = self.token(current)
            if token in seen:
                raise ValueError(f"目录链接形成循环：{current}")
            seen.add(token)
        return path

    @staticmethod
    def cancelled(worker):
        if worker and worker.cancel.is_set():
            raise ValueError("已取消；当前阶段已收尾")

    def binding(self, path):
        physical = self.token(path)
        link = path.lstat()
        target = path.stat()
        return (physical, link.st_mtime_ns, target.st_mtime_ns, target.st_dev, target.st_ino)

    @staticmethod
    def cached(cache, key, factory, limit):
        if key in cache:
            cache.move_to_end(key)
            return cache[key]
        result = factory()
        cache[key] = result
        if len(cache) > limit:
            cache.popitem(last=False)
        return result

    def directory_metadata(self, path, stamp):
        """Cache each directory separately so nested image changes are visible."""
        key = (stamp[0], stamp[2], stamp[3], stamp[4])
        def inspect():
            is_mod, images, directories = False, [], []
            with os.scandir(path) as entries:
                for entry in entries:
                    lower = entry.name.lower()
                    extension = os.path.splitext(lower)[1]
                    if entry.is_dir():
                        directories.append(entry.name)
                        continue
                    if extension in (".ini", ".modinfo") and entry.is_file():
                        is_mod = True
                    if extension not in self.mm._IMAGE_EXTS or not entry.is_file():
                        continue
                    if any(word in lower for word in self.mm._PREVIEW_EXCLUDE):
                        continue
                    score = 200 + (2000 if os.path.splitext(lower)[0] == "preview" else
                                   1000 if lower.startswith("preview") else
                                   500 if "preview" in lower else
                                   300 if any(word in lower for word in self.mm._PREVIEW_HINTS) else 0)
                    images.append((-score, entry.name))
            return is_mod, images, directories
        return self.cached(self.direct_cache, key, inspect, 2048)

    def direct_metadata(self, path, stamp, worker=None):
        """Keep mod detection shallow and search all descendants for a preview."""
        stack, seen, best, is_mod = [(path, stamp)], set(), None, False
        while stack:
            self.cancelled(worker)
            current, current_stamp = stack.pop()
            try:
                current_stamp = current_stamp or self.binding(current)
                if current_stamp[0] in seen:
                    continue
                seen.add(current_stamp[0])
                direct_mod, images, directories = self.directory_metadata(current, current_stamp)
            except (OSError, ValueError):
                if current == path:
                    raise
                continue
            if current == path:
                is_mod = direct_mod
            for score, name in images:
                relative = (current / name).relative_to(path)
                candidate = (score, len(relative.parts), relative.as_posix().casefold(), relative.as_posix())
                if best is None or candidate < best:
                    best = candidate
            stack.extend((current / name, None) for name in sorted(directories, reverse=True))
        return is_mod, best[3] if best else None

    def listing(self, relative="", worker=None, query="", recursive=False, hide_empty=False):
        started = time.perf_counter()
        root = self.root()
        folder = self.resource_path(root / relative, root)
        if not folder.is_dir():
            raise ValueError("目录已移动或不存在，请刷新")
        # Validate this breadcrumb once. Children come from scandir(folder),
        # so repeating every ancestor resolution for every card is redundant.
        ancestors = set()
        ancestor = folder
        while True:
            ancestors.add(self.token(ancestor))
            if ancestor == root:
                break
            ancestor = ancestor.parent
        self.revision += 1
        revision = self.revision
        items, handles = [], {}
        def scan_entries():
            stack, seen = [root if recursive and query else folder], set()
            while stack:
                current = stack.pop()
                self.cancelled(worker)
                token = self.token(current)
                if token in seen:
                    continue
                seen.add(token)
                with os.scandir(current) as scan:
                    children = sorted(scan, key=lambda e: (not e.is_dir(), e.name.casefold()))
                for entry in children:
                    if recursive and query and entry.is_dir():
                        try:
                            if self.token(Path(entry.path)) not in seen:
                                stack.append(Path(entry.path))
                        except ValueError:
                            pass
                    yield entry
        entries = scan_entries()
        for entry in entries:
            self.cancelled(worker)
            path = Path(entry.path)
            if path.name.startswith((".omg-move-", ".omg-recovery-")):
                continue
            try:
                directory = entry.is_dir()
                if not directory and path.suffix.lower() != ".ini":
                    continue
                if query.casefold() not in path.name.casefold():
                    continue
                if directory and hide_empty:
                    with os.scandir(path) as contents:
                        if next(contents, None) is None:
                            continue
                stamp = self.binding(path)
                if stamp[0] in ancestors:
                    raise ValueError(f"目录链接形成循环：{path}")
                entry_stat = path.lstat()
                is_link = bool(getattr(entry_stat, "st_file_attributes", 0)
                               & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)) or path.is_symlink()
                is_mod, thumbnail = self.direct_metadata(path, stamp, worker) if directory else (True, None)
                preference = self.preferences.get(self.token(path), {})
                is_mod = preference.get("isMod", is_mod)
                identity = uuid.uuid4().hex
                handles[identity] = (str(root), str(path), revision, stamp)
                # UI-only identity survives rename; RPCs still use fresh handles.
                ui_key = (f"{entry_stat.st_dev}:{entry_stat.st_ino}" if entry_stat.st_ino
                          and (directory or entry_stat.st_nlink == 1) else str(path))
                items.append({"id": identity, "uiKey": ui_key, "name": path.name,
                              "relativePath": path.relative_to(root).as_posix(),
                              "isDirectory": directory, "isMod": is_mod, "isLink": is_link,
                              "masked": preference.get("masked", False),
                              "targetPath": stamp[0] if is_link else None,
                              "enabled": not self.mm.is_disabled(path.name),
                              "thumbnailPath": str(path / thumbnail) if thumbnail else None,
                              "keys": [], "keysLoaded": False})
            except (OSError, ValueError) as exc:
                # An unavailable link must not hide the rest of the directory.
                if entry.is_dir(follow_symlinks=False):
                    items.append({"id": uuid.uuid4().hex, "name": path.name,
                                  "relativePath": path.relative_to(root).as_posix(),
                                  "isDirectory": True, "isMod": False, "isLink": True,
                                  "enabled": False, "keys": [], "blockedReason": str(exc)})
        self.handles = handles
        relative_path = folder.relative_to(root).as_posix()
        return {"root": str(root), "relativePath": "" if relative_path == "." else relative_path,
                "revision": revision, "items": items, "message": f"已读取 {len(items)} 项",
                "elapsedMs": round((time.perf_counter() - started) * 1000, 2)}

    def checked_handle(self, params):
        handle = self.handles.get(params.get("id"))
        if not handle or params.get("revision") != handle[2]:
            raise ValueError("资源列表已变化，请刷新后重试")
        root, path, revision, stamp = handle
        root, path = Path(root), Path(path)
        if self.root() != root:
            raise ValueError("GIMI 目录已变化，请刷新")
        self.resource_path(path, root)
        if self.binding(path) != stamp:
            raise ValueError("资源或链接目标已被外部修改，请刷新后重试")
        return root, path

    def ini_files(self, folder, worker=None):
        """Follow directory junctions, prune cycles and deduplicate aliases."""
        stack = [folder]
        directories, files = set(), set()
        while stack:
            self.cancelled(worker)
            current = stack.pop()
            token = self.token(current)
            if token in directories:
                continue
            directories.add(token)
            if current.is_file():
                entries = [current]
            else:
                with os.scandir(current) as scan:
                    children = sorted(scan, key=lambda e: e.name.casefold())
                entries = []
                for entry in children:
                    self.cancelled(worker)
                    path = Path(entry.path)
                    if entry.is_dir():
                        if self.token(path) not in directories:
                            stack.append(path)
                    elif entry.name.lower().endswith(".ini") and entry.is_file():
                        entries.append(path)
            for path in entries:
                self.cancelled(worker)
                if path.suffix.lower() != ".ini":
                    continue
                token = self.token(path)
                if token not in files:
                    files.add(token)
                    yield path

    def keys(self, params, worker):
        started = time.perf_counter()
        root, path = self.checked_handle(params)
        keys, parsed = [], 0
        for ini in self.ini_files(path, worker):
            st = ini.stat()
            cache_key = (self.token(ini), st.st_mtime_ns, st.st_size)
            def parse():
                nonlocal parsed
                parsed += 1
                return self.mm._parse_ini_file(str(ini))
            keys.extend(self.cached(self.ini_cache, cache_key, parse, 4096))
        self.checked_handle(params)
        return {"id": params["id"], "keys": keys, "parsedFiles": parsed,
                "elapsedMs": round((time.perf_counter() - started) * 1000, 2), "message": "切换键已读取"}

    def toggle(self, params, worker):
        root, path = self.checked_handle(params)
        if not isinstance(params.get("enabled"), bool):
            raise ValueError("启停状态无效")
        self.cancelled(worker)
        # Rename the logical junction entry, never rename its target directory.
        old_key = self.token(path)
        ok, new_path, message = self.mm.set_mod_enabled(str(path), params["enabled"])
        if not ok:
            raise ValueError(message)
        preference = self.preferences.pop(old_key, None)
        if preference is not None:
            self.preferences[self.token(Path(new_path))] = preference
            self.save_preferences()
        result = self.refresh(params, path.parent.relative_to(root).as_posix())
        result["message"] = f"已{'启用' if params['enabled'] else '停用'} {Path(new_path).name}；游戏内请重新加载"
        result["renamedPath"] = new_path
        return result

    def writeback(self, worker):
        root = self.root()
        master = root.parent / "d3dx_user.ini"
        if not master.is_file():
            raise ValueError("未找到 GIMI/d3dx_user.ini")
        inis = [p for p in self.ini_files(root, worker) if "DISABLED" not in p.name.upper()]
        backup = self.data_root / "resource-backups" / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        before = {}
        for path in inis:
            self.cancelled(worker)
            dest = backup / path.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            before[str(path)] = (self.token(path), sha256_file(path))
        logs = []
        def emit(line):
            logs.append(line)
            worker.progress.emit({"message": line})
        self.cancelled(worker)
        for name, (target, _) in before.items():
            if self.token(Path(name)) != target:
                raise ValueError("链接目标已变化，未开始写回，请刷新后重试")
        ok, message = self.mm.write_back_swapkeys(str(root), target_dir=None, emit=emit,
                                                ini_files=[str(p) for p in inis])
        changed = sum(Path(p).exists() and sha256_file(p) != digest
                      for p, (_, digest) in before.items())
        self.ini_cache.clear()
        failures = [line for line in logs if line.startswith(("[失败]", "[跳过]"))]
        return {"ok": ok, "message": f"{message}；备份：{backup}", "backup": str(backup),
                "changedFiles": changed, "failures": failures, "logs": logs,
                "partial": bool(failures) and changed > 0}

    def save_preferences(self):
        self.data_root.mkdir(parents=True, exist_ok=True)
        temporary = self.preferences_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.preferences, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self.preferences_path)

    def refresh(self, params, fallback="", worker=None):
        return self.listing(params.get("path", fallback), worker,
                            params.get("query", ""), params.get("recursive", False),
                            params.get("hideEmpty", False))

    def card(self, params, worker):
        root, path = self.checked_handle(params)
        preference = dict(self.preferences.get(self.token(path), {}))
        for key in ("isMod", "masked"):
            if key in params:
                if not isinstance(params[key], bool):
                    raise ValueError("卡片设置无效")
                preference[key] = params[key]
        if not path.is_dir() and preference.get("isMod") is False:
            raise ValueError("INI 文件不能转换为文件夹")
        self.preferences[self.token(path)] = preference
        self.save_preferences()
        return self.refresh(params, worker=worker)

    def folders(self, relative):
        root = self.root()
        folder = self.resource_path(root / relative, root)
        with os.scandir(folder) as scan:
            return [{"name": e.name, "path": Path(e.path).relative_to(root).as_posix()}
                    for e in sorted(scan, key=lambda e: e.name.casefold()) if e.is_dir()]

    def directory_entries(self, relative):
        """Direct children only; independent of search, card types and listing handles."""
        root = self.root()
        folder = self.resource_path(root / relative, root)
        folders, files = [], []
        with os.scandir(folder) as scan:
            for entry in sorted(scan, key=lambda e: e.name.casefold()):
                item = {"name": entry.name, "path": Path(entry.path).relative_to(root).as_posix()}
                if entry.is_dir():
                    folders.append(item)
                elif entry.is_file() and Path(entry.name).suffix.lower() == ".ini":
                    files.append(item)
        return {"folders": folders, "files": files}

    def config_files(self, params):
        root, path = self.checked_handle(params)
        return [{"name": str(ini.relative_to(path)) if path.is_dir() else ini.name,
                 "path": ini.relative_to(root).as_posix()} for ini in self.ini_files(path)]

    def open_image(self, params):
        root, path = self.checked_handle(params)
        if not path.is_dir():
            raise ValueError("该资源未提供预览图")
        _, thumbnail = self.direct_metadata(path, self.binding(path))
        if not thumbnail:
            raise ValueError("该资源未提供预览图")
        image = self.resource_path(path / thumbnail, root)
        if not image.is_file() or image.suffix.lower() not in self.mm._IMAGE_EXTS:
            raise ValueError("预览图已不存在，请刷新后重试")
        os.startfile(str(image))
        return {}

    def open_path(self, params):
        root = self.root()
        path = self.resource_path(root / params.get("path", ""), root)
        if params.get("config"):
            if path.suffix.lower() != ".ini" or not path.is_file():
                raise ValueError("配置文件已不存在")
            os.startfile(str(path))
        elif path.is_dir():
            subprocess.Popen(["explorer.exe", str(path)])
        else:
            subprocess.Popen(["explorer.exe", "/select,", str(path)])
        return {}

    def move(self, params, worker):
        # Copy completely before touching sources. Keep source recovery names
        # until every destination is committed; never overwrite existing data.
        from resource_service import safe_tree
        root = self.root()
        target = self.resource_path(root / params.get("path", ""), root)
        target_token = self.token(target)
        sources = [Path(os.path.abspath(p)) for p in params.get("sources", [])]
        if not sources or not target.is_dir():
            raise ValueError("请选择要移动的文件或文件夹")
        names, tokens = set(), []
        for source in sources:
            safe_tree(source, source)
            token = Path(self.token(source))
            destination = target / source.name
            if source.name.casefold() in names or destination.exists():
                raise ValueError(f"目标已存在同名文件：{source.name}")
            if Path(target_token) == token or token in Path(target_token).parents:
                raise ValueError("不能移动到自身或自身的子目录")
            if any(token == other or token in other.parents or other in token.parents for other in tokens):
                raise ValueError("拖放内容包含重复或互相嵌套的路径")
            names.add(source.name.casefold())
            tokens.append(token)
        stage = target / (".omg-move-" + uuid.uuid4().hex)
        stage.mkdir()
        backups, committed = [], []
        def signature(source):
            safe_tree(source, source)
            paths = [source, *source.rglob("*")] if source.is_dir() else [source]
            result = {}
            for path in paths:
                self.cancelled(worker)
                info = path.stat()
                result[str(path.relative_to(source))] = ("directory",) if path.is_dir() else (info.st_size, info.st_mtime_ns)
            return result
        try:
            signatures = [signature(source) for source in sources]
            for source in sources:
                self.cancelled(worker)
                if source.is_dir():
                    shutil.copytree(source, stage / source.name)
                else:
                    shutil.copy2(source, stage / source.name)
            self.cancelled(worker)
            if self.token(target) != target_token:
                raise ValueError("目标目录已变化")
            for source, before in zip(sources, signatures):
                if signature(source) != before:
                    raise ValueError(f"复制期间原文件发生变化：{source}")
                recovery = source.with_name(".omg-recovery-" + uuid.uuid4().hex)
                source.rename(recovery)
                backups.append((source, recovery))
                if signature(recovery) != before:
                    raise ValueError(f"移动期间原文件发生变化：{source}")
            for source in sources:
                destination = target / source.name
                # Windows rename fails if a concurrent writer created the name.
                (stage / source.name).rename(destination)
                committed.append(destination)
        except Exception as exc:
            failures = []
            for destination in reversed(committed):
                try:
                    destination.rename(stage / destination.name)
                except OSError as rollback:
                    failures.append(f"目标保留于 {destination}：{rollback}")
            for source, recovery in reversed(backups):
                try:
                    recovery.rename(source)
                except OSError as rollback:
                    failures.append(f"原文件保留于 {recovery}：{rollback}")
            logging.exception("resources.move failed target=%s backups=%s rollback=%s", target, backups, failures)
            if failures:
                raise ValueError(f"移动失败：{exc}；恢复详情：{'；'.join(failures)}") from exc
            raise ValueError(f"移动失败，原文件已恢复：{exc}") from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)
        retained = []
        for source, recovery in backups:
            try:
                if recovery.is_dir():
                    shutil.rmtree(recovery)
                else:
                    recovery.unlink()
            except OSError:
                retained.append(str(recovery))
        result = self.refresh(params, worker=None)
        result["message"] = f"已移动 {len(sources)} 项"
        if retained:
            result["message"] += "；恢复副本未能清理：" + "；".join(retained)
        try:
            self.open_path({"path": params.get("path", "")})
        except OSError:
            logging.exception("resources.move explorer failed target=%s", target)
        return result
