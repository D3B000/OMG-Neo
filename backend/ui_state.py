"""Small per-install UI state, independent of business configuration revisions."""
import json
import os
import re
import time
from urllib.parse import quote

MAX_AGE = 24 * 3600


class UiState:
    def __init__(self, root):
        self.path = root / "ui-state.json"
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.data = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            self.data = {}

    @property
    def scope(self):
        return "global" if self.data.get("searchScope") == "global" else "directory"

    def commit(self, **patch):
        data = {**self.data, **patch}
        temp = self.path.with_suffix(".tmp")
        try:
            temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(temp, self.path)
        finally:
            temp.unlink(missing_ok=True)
        self.data = data

    def notes(self, version):
        entry = self._entries().get(version)
        if (not isinstance(entry, dict) or not isinstance(entry.get("body"), str)
                or not isinstance(entry.get("fetchedAt"), (int, float))):
            return {}
        age = time.time() - entry["fetchedAt"]
        return {**entry, "stale": not 0 <= age < MAX_AGE}

    def save_release(self, release):
        tag, body = release.get("tag_name"), release.get("body")
        if not isinstance(tag, str) or not isinstance(body, str):
            return
        version = tag.lstrip("vV")
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version):
            return
        notes = dict(self._entries())
        notes.pop(version, None)
        notes[version] = {"tag": tag, "body": body, "fetchedAt": int(time.time())}
        self.commit(gimiNotes=dict(list(notes.items())[-16:]))

    def _entries(self):
        entries = self.data.get("gimiNotes")
        return entries if isinstance(entries, dict) else {}


def fetch_installed_release(version, should_cancel=None):
    from omg.core import download, gimi_update

    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version):
        raise ValueError("未检测到 GIMI 版本，请先配置 GIMI 目录")
    endpoint = gimi_update.GIMI_API_URL.removesuffix("/latest")
    for tag in (f"v{version}", version):
        if should_cancel and should_cancel():
            break
        release = download.fetch_json_api_smart(
            f"{endpoint}/tags/{quote(tag, safe='')}", should_cancel=should_cancel)
        if (isinstance(release, dict) and release.get("tag_name") == tag
                and isinstance(release.get("body"), (str, type(None)))):
            return {**release, "body": release.get("body") or ""}
    raise ValueError(f"未能获取 GIMI {version} 的更新说明，请检查网络或稍后重试")
