"""Neo-owned configuration; never writes the source OMGLite configuration."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import shutil


DEFAULTS = {
    "game_folder": "", "gimi_folder": "", "hunting": 2, "warning": 0,
    "cleanup_on_exit": False, "auto_check_update": False, "gimi_update_whitelist": [],
    "launch_method": "native", "inject_method": "hook",
    "custom_launch_enabled": False, "custom_launch_cmd": "",
    "custom_launch_inject_mode": "hook", "extra_libraries_enabled": False,
    "extra_libraries": "", "theme": "light", "accent_color": "#39C5BB",
}


def validate(patch: dict) -> dict:
    if not isinstance(patch, dict):
        raise ValueError("配置补丁必须为对象")
    result = copy.deepcopy(patch)
    for key, value in result.items():
        if key not in DEFAULTS:
            raise ValueError(f"未知配置项：{key}")
        default = DEFAULTS[key]
        if isinstance(default, bool):
            if value not in (0, 1, False, True):
                raise ValueError(f"{key} 必须为布尔值")
            result[key] = bool(value)
        elif isinstance(default, int):
            if type(value) is not int or value not in (range(3) if key == "hunting" else range(2)):
                raise ValueError(f"{key} 数值无效")
        elif isinstance(default, str) and not isinstance(value, str):
            raise ValueError(f"{key} 必须为字符串")
    for key, options in {
        "launch_method": ("native", "shell", "manual"),
        "inject_method": ("hook", "inject", "bypass"),
        "custom_launch_inject_mode": ("hook", "inject", "bypass"),
        "theme": ("light", "dark"),
    }.items():
        if key in result:
            result[key] = result[key].lower()
            if result[key] not in options:
                raise ValueError(f"{key} 选项无效")
    if "accent_color" in result:
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", result["accent_color"]):
            raise ValueError("强调色必须为六位 HEX 颜色")
        result["accent_color"] = result["accent_color"].upper()
    if "gimi_update_whitelist" in result:
        entries = result["gimi_update_whitelist"]
        if not isinstance(entries, list) or any(not isinstance(x, str) for x in entries):
            raise ValueError("白名单必须为路径数组")
        normalized = []
        for entry in entries:
            entry = entry.strip().replace("\\", "/")
            if not entry or entry.startswith("/") or ":" in entry or ".." in entry.split("/"):
                raise ValueError("白名单必须为 GIMI 内的相对路径")
            if entry.casefold() not in {p.casefold() for p in normalized}:
                normalized.append(entry)
        result["gimi_update_whitelist"] = normalized
    return result


class SettingsStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "config.json"
        self.revision = 0
        self.settings = copy.deepcopy(DEFAULTS)
        self.metadata = {}
        self.recovered = False
        if self.path.exists():
            try:
                self._load(self.path)
            except (ValueError, OSError, TypeError):
                self._load(self.path.with_suffix(".json.bak"))
                self.recovered = True

    def _load(self, path):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schemaVersion") != 1:
            raise ValueError("不支持的配置版本")
        self.settings.update(validate(data["settings"]))
        self.revision = int(data["revision"])
        self.metadata = data.get("metadata", {})

    def commit(self, patch, *, metadata=None, revision=None):
        if revision is not None and revision != self.revision:
            raise ValueError("配置版本已变更，请重新读取")
        settings = {**self.settings, **validate(patch)}
        meta = {**self.metadata, **(metadata or {})}
        data = {"schemaVersion": 1, "revision": self.revision + 1,
                "settings": settings, "metadata": meta}
        temp = self.path.with_suffix(".json.tmp")
        try:
            with temp.open("w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            # Preserve the last known-good backup after recovery.
            if self.path.exists() and not self.recovered:
                shutil.copy2(self.path, self.path.with_suffix(".json.bak"))
            os.replace(temp, self.path)
        finally:
            temp.unlink(missing_ok=True)
        self.settings, self.metadata = settings, meta
        self.revision += 1
        self.recovered = False

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def get_gimi_dir(self):
        return self.get("gimi_folder", "")

    def snapshot(self):
        return {"settings": copy.deepcopy(self.settings), "revision": self.revision,
                "dataRoot": str(self.root), "recovered": self.recovered}

    def import_lite(self, path: Path):
        old = json.loads(path.read_text(encoding="utf-8-sig"))
        patch = {k: v for k, v in old.items() if k in DEFAULTS}
        for key in ("hunting", "warning"):
            if key in patch:
                patch[key] = int(patch[key])
        if "gimi_update_whitelist" in patch:
            root = Path(old.get("gimi_folder", "")).resolve()
            entries = []
            for item in patch["gimi_update_whitelist"]:
                folder = item.endswith(("/", "\\"))
                candidate = Path(item)
                if candidate.is_absolute():
                    candidate = candidate.resolve().relative_to(root)
                entries.append(candidate.as_posix().rstrip("/") + ("/" if folder else ""))
            patch["gimi_update_whitelist"] = entries
        self.commit(patch)

