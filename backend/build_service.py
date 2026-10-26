"""Adapter for Lite alchemy; all writable state belongs to Neo, never its bundle."""
import hashlib
import json
import os
import subprocess
from pathlib import Path
import re
import shutil
import time
import uuid

from resource_service import no_links, safe_tree
from file_io import sha256_file


class BuildService:
    defaults = {"source": 0, "ritualType": 0, "copyType": 0, "version": "",
                "project": "", "optimize": True, "ritual": True,
                "autoRitual": False, "autoMove": False, "target": ""}
    groups = {"project": "源码工程", "cloud": "已构建文件", "artifact": "构建产物",
              "output": "仪式产物", "input": "输入暂存", "temp": "临时文件"}

    def __init__(self, root, config, game_stopped):
        from omg.core import paths, ritual_loader
        ritual_root = Path(paths.RITUAL_BIN_DIR)
        ritual_loader.RITUAL_BUNDLE_PYD = str(ritual_root / "ritual_bundle.pyd")
        ritual_loader.CYTHON_ANALYSIS_PYD = str(ritual_root / "_cython_analysis.pyd")
        from omg.core import alchemy
        alchemy.UPX_EXE = str(ritual_root / "upx.exe")
        alchemy.DIVERSIFIER_DLL = str(ritual_root / "pe_diversifier.dll")
        self.a, self.config, self.game_stopped = alchemy, config, game_stopped
        self.root = root / "build-work"
        self.root.mkdir(exist_ok=True)
        self.a.ALCHEMY_DIR = str(self.root)
        for attr, child in (("PROJECT_DIR", "project"), ("ARTIFACT_DIR", "artifact"),
                            ("OUTPUT_DIR", "output"), ("CLOUD_DIR", "cloud"), ("INPUT_DIR", "input")):
            setattr(self.a, attr, str(self.root / child))
        for attr, child in (("ARTIFACT_DLL", "artifact"), ("OUTPUT_DLL", "output"), ("INPUT_DLL", "input")):
            setattr(self.a, attr, str(self.root / child / "d3d11.dll"))
        self.a.ensure_dirs()
        self.a.TEMP_DIR = str(self.root / "temp")
        Path(self.a.TEMP_DIR).mkdir(exist_ok=True)
        self.preferences = root / "build-options.json"
        self.registry = root / "build-products.json"
        self.options = dict(self.defaults)
        try:
            self.options.update({k: v for k, v in json.loads(self.preferences.read_text("utf-8")).items()
                                 if k in self.defaults and type(v) is type(self.defaults[k])})
        except (OSError, ValueError, AttributeError):
            pass
        try:
            self.products = json.loads(self.registry.read_text("utf-8"))
        except (OSError, ValueError):
            self.products = {}
        self.releases = []
        self.environment = {}
        self.plans = {}

    @staticmethod
    def atomic(path, value):
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)

    def select(self, patch):
        for key, value in patch.items():
            if key not in self.defaults or type(value) is not type(self.defaults[key]):
                raise ValueError(f"构建选项无效：{key}")
            if key in ("source", "copyType") and value not in (0, 1):
                raise ValueError("来源选项无效")
            if key == "ritualType" and value not in (0, 1, 2):
                raise ValueError("仪式选项无效")
        if "project" in patch and patch["project"] != self.options["project"]:
            self.environment = {}
        self.options.update(patch)
        self.atomic(self.preferences, self.options)
        return self.state()

    def state(self):
        from omg.core.ritual_loader import load_ritual_bundle
        bundle = load_ritual_bundle()
        return {"options": dict(self.options), "projects": self.a.list_project_versions(),
                "releases": [{"tag": r["tag"], "version": r["version"]} for r in self.releases],
                "environment": self.environment, "workspace": str(self.root),
                "capabilities": {"build": callable(getattr(bundle, "run_build", None)),
                                 "ritual": [bundle is not None and Path(self.a.UPX_EXE).is_file(),
                                            bundle is not None, bundle is not None and Path(self.a.DIVERSIFIER_DLL).is_file()]},
                "products": dict(self.products)}

    def open_workspace(self):
        folder = no_links(self.root, self.root)
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer.exe", str(folder)])
        return {}

    def project(self):
        version = self.options["project"]
        if not version or version not in self.a.list_project_versions():
            raise ValueError("请选择已下载的源码工程")
        safe_tree(Path(self.a.project_dir_for(version)), self.root)
        return version

    def record(self, kind, source):
        path = self.root / kind / "d3d11.dll"
        no_links(path, self.root)
        if not path.is_file():
            raise ValueError("未生成有效产物")
        self.products[kind] = {"path": str(path), "sha256": sha256_file(path),
                               "source": source, "createdAt": int(time.time())}
        self.atomic(self.registry, self.products)

    def invalidate(self, kind):
        self.products.pop(kind, None)
        self.atomic(self.registry, self.products)

    def deploy(self, kind):
        self.game_stopped(dict(self.config.settings))
        gimi = self.config.get_gimi_dir()
        if not gimi or not (Path(gimi) / "d3dx.ini").is_file():
            raise ValueError("请配置包含 d3dx.ini 的 GIMI 目录")
        src = no_links(self.root / kind / "d3d11.dll", self.root)
        product = self.products.get(kind)
        if not product or not src.is_file() or sha256_file(src) != product["sha256"]:
            raise ValueError("产物缺失、已变化或上次执行失败，请重新生成后复制")
        dst = no_links(Path(gimi) / "d3d11.dll", Path(gimi))
        backup = None
        if dst.exists():
            backup = self.root.parent / "dll-backups" / f"{time.time_ns()}-d3d11.dll"
            backup.parent.mkdir(exist_ok=True)
            shutil.copy2(dst, backup)
        temp = dst.with_name(f".neo-{uuid.uuid4().hex}.dll")
        try:
            shutil.copy2(src, temp)
            os.replace(temp, dst)
        finally:
            temp.unlink(missing_ok=True)
        return f"已复制到 {dst}" + (f"；原文件备份：{backup}" if backup else "")

    def execute(self, action, worker, sink_factory):
        a, options = self.a, dict(self.options)
        safe_tree(self.root, self.root)
        def progress(value):
            worker.progress.emit({"progress": max(0., min(1., float(value) / 100))})
        def text(line, percent=-1):
            data = {"message": str(line)}
            if percent >= 0:
                data["progress"] = min(1., percent / 100)
            worker.progress.emit(data)
        def checked(ok, message):
            if not ok:
                raise ValueError(str(message))
        def checkpoint():
            if worker.cancel.is_set():
                raise ValueError("已取消后续步骤；当前阶段已收尾")
        checkpoint()
        message = "完成"
        if action == "releases":
            self.releases = [r for r in a.fetch_releases(should_cancel=worker.cancel.is_set, status_cb=text)
                             if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", r.get("version", ""))]
            if not self.releases:
                raise ValueError("未获取到远端版本，请检查网络后重试")
            if not options["version"] or options["version"] not in [r["tag"] for r in self.releases]:
                self.select({"version": self.releases[0]["tag"]})
            message = f"已获取 {len(self.releases)} 个版本"
        elif action == "download":
            if options["source"] == 1:
                ok, message = a.fetch_prebuilt(progress_cb=progress, status_cb=text, should_cancel=worker.cancel.is_set)
            else:
                release = next((r for r in self.releases if r["tag"] == options["version"]), None)
                if not release:
                    raise ValueError("请先刷新并选择远端版本")
                ok, message = a.download_and_extract(release, sink_factory(worker), should_cancel=worker.cancel.is_set)
                if ok:
                    self.select({"project": release["version"]})
                    self.environment = {}
            checked(ok, message)
        elif action == "environment":
            version = options["project"]
            if version:
                self.project()
            report = a.run_env_check(version, options["optimize"])
            self.environment = {"ready": report.ready, "text": report.to_tip_text(180)}
            message = self.environment["text"]
        elif action in ("compile", "ritual"):
            if action == "compile":
                self.invalidate("artifact")
                if options["autoRitual"]:
                    self.invalidate("output")
                version = self.project()
                report = a.run_env_check(version, options["optimize"])
                self.environment = {"ready": report.ready, "text": report.to_tip_text(180)}
                if not report.ready:
                    raise ValueError(report.to_tip_text(180))
                ok, info = a.build_project(version, options["optimize"], callback=text)
                checked(ok, info)
                self.record("artifact", version)
                self.select({"target": str(Path(a.ARTIFACT_DLL).absolute())})
                message = "构建完成"
                checkpoint()
            if action == "ritual" or options["autoRitual"]:
                self.invalidate("output")
                if not options["ritual"]:
                    raise ValueError("请先开启神秘仪式")
                kind = (a.RITUAL_PACK, a.RITUAL_PAINT_PY, a.RITUAL_PAINT_RS)[options["ritualType"]]
                target = a.ARTIFACT_DLL if action == "compile" else options["target"]
                picked_source = []
                def pick(progress_cb):
                    result = a.pick_random_prebuilt_dll(progress_cb)
                    if result[0]:
                        picked_source.append(result[2])
                    return result
                prepare = pick if not target and options["source"] == 1 else None
                target = target or a.ARTIFACT_DLL
                # An external source is read-only; avoid the legacy output
                # deletion when the user accidentally selects the output itself.
                if Path(target).resolve() == Path(a.OUTPUT_DLL).resolve():
                    raise ValueError("目标不能选择仪式输出文件本身")
                ok, message = a.run_ritual(kind, target, progress_cb=progress, prepare=prepare)
                checked(ok, message)
                self.record("output", picked_source[0] if picked_source else str(target))
                checkpoint()
            if options["autoMove"]:
                message += "；" + self.deploy("output" if action == "ritual" or options["autoRitual"] else "artifact")
        elif action == "copy":
            message = self.deploy("artifact" if options["copyType"] == 0 else "output")
        else:
            raise ValueError("未知构建操作")
        return {"message": str(message), "build": self.state()}

    def cleanup_scan(self):
        safe_tree(self.root, self.root)
        self.plans = {}
        entries = []
        for group, label in self.groups.items():
            folder = self.root / group
            if not folder.exists():
                continue
            for path in folder.iterdir():
                safe_tree(path, self.root)
                identity = uuid.uuid4().hex
                fingerprint, size = self.fingerprint(path)
                self.plans[identity] = (str(path), fingerprint)
                entries.append({"id": identity, "group": label, "name": path.name, "bytes": size})
        return {"items": entries, "message": f"扫描到 {len(entries)} 项"}

    @staticmethod
    def fingerprint(path):
        entries = [path, *path.rglob("*")] if path.is_dir() else [path]
        digest, size = hashlib.sha256(), 0
        for entry in sorted(entries):
            st = entry.stat()
            digest.update(f"{entry}:{st.st_size}:{st.st_mtime_ns}".encode("utf-8"))
            if entry.is_file():
                size += st.st_size
        return digest.hexdigest(), size

    def cleanup(self, ids, worker):
        if not isinstance(ids, list) or not ids:
            raise ValueError("请先选择清理项")
        selected = []
        for identity in ids:
            plan = self.plans.get(identity)
            if not plan:
                raise ValueError("清理计划已失效，请重新扫描")
            path = Path(plan[0])
            safe_tree(path, self.root)
            if self.fingerprint(path)[0] != plan[1]:
                raise ValueError("文件已变化，请重新扫描清理项")
            selected.append(path)
        errors, removed = [], []
        for path in selected:
            if worker.cancel.is_set():
                break
            try:
                shutil.rmtree(path) if path.is_dir() else path.unlink()
                removed.append(str(path))
            except OSError as exc:
                errors.append(f"{path}：{exc}")
        for kind in ("artifact", "output"):
            if not (self.root / kind / "d3d11.dll").is_file():
                self.invalidate(kind)
        if self.options["project"] and self.options["project"] not in self.a.list_project_versions():
            self.select({"project": ""})
        return {"message": f"已清理 {len(removed)} 项；失败 {len(errors)} 项",
                "errors": errors, "removed": removed, "build": self.state(), "cleanup": self.cleanup_scan()}
