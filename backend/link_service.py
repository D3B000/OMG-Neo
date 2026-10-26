"""Directory associations with additive Include configuration updates."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import hashlib
import tempfile


def include_content(target, relative):
    if not os.path.lexists(target):
        return (f"[Include]\r\ninclude_recursive = {relative}\r\n"
                "exclude_recursive = DISABLED*\r\n", "utf-8", None, False)
    if target.is_symlink() or not target.is_file() or target.resolve() != target:
        raise ValueError("modFolder.ini 必须是普通配置文件")
    original = target.read_bytes()
    encoding = "utf-16" if original.startswith((b'\xff\xfe', b'\xfe\xff')) else "utf-8-sig" if original.startswith(b'\xef\xbb\xbf') else "utf-8"
    try:
        content = original.decode(encoding)
    except UnicodeDecodeError:
        encoding = "gb18030"
        content = original.decode(encoding)
    lines = content.splitlines(keepends=True)
    in_include = False
    insert_at = None
    duplicate = False
    for index, line in enumerate(lines):
        section = re.fullmatch(r"\s*\[([^\]]+)\]\s*(?:;.*)?", line.strip())
        if section:
            in_include = section[1].strip().casefold() == "include"
        if not in_include:
            continue
        entry = re.fullmatch(r"\s*(include_recursive|exclude_recursive)\s*=\s*(.*?)\s*", line.rstrip('\r\n'), re.I)
        if not entry:
            continue
        key, value = entry[1].casefold(), entry[2]
        if key == "include_recursive":
            existing = value.replace('\\', os.sep).replace('/', os.sep)
            if os.path.normcase(os.path.abspath(target.parent / existing)) == os.path.normcase(os.path.abspath(target.parent / relative.replace('\\', os.sep))):
                duplicate = True
        elif value.casefold() == "disabled*" and insert_at is None:
            insert_at = index
    if insert_at is None:
        raise ValueError("已有 modFolder.ini 的 [Include] 中缺少 exclude_recursive = DISABLED*，请检查配置")
    if not duplicate:
        ending = '\r\n' if '\r\n' in content else '\n'
        lines.insert(insert_at, f"include_recursive = {relative}{ending}")
    return ''.join(lines), encoding, hashlib.sha256(original).hexdigest(), duplicate


def directory(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"请填写{label}")
    path = Path(value.strip())
    if not path.is_absolute() or not path.is_dir():
        raise ValueError(f"{label}必须是已存在的绝对目录")
    return path.resolve()


def volume_info(path):
    if os.name != "nt":
        raise ValueError("JUNCTION 仅支持 Windows 本地磁盘")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    root = ctypes.create_unicode_buffer(32768)
    kernel.GetVolumePathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetVolumeInformationW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    if not kernel.GetVolumePathNameW(str(path), root, len(root)):
        raise ctypes.WinError(ctypes.get_last_error())
    if kernel.GetDriveTypeW(root.value) == 4 or str(path).startswith("\\\\"):
        raise ValueError("JUNCTION 不支持网络目录，请选择本地磁盘")
    flags = wintypes.DWORD()
    fs = ctypes.create_unicode_buffer(256)
    if not kernel.GetVolumeInformationW(root.value, None, 0, None, None,
                                        ctypes.byref(flags), fs, len(fs)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not flags.value & 0x80:  # FILE_SUPPORTS_REPARSE_POINTS
        raise ValueError(f"磁盘 {root.value}（{fs.value}）不支持目录联接 / 符号链接")
    return f"{root.value} {fs.value}：支持重解析点"


class LinkService:
    def __init__(self, config):
        self.config = config

    def validate(self, params):
        resource = directory(params.get("resource"), "资源目录")
        mode = params.get("mode")
        if mode == "junction":
            destination = directory(params.get("destination"), "符号目录")
            name = params.get("name", "")
            if (not isinstance(name, str) or not name or name != name.strip()
                    or name.endswith((".", " ")) or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
                    or name in (".", "..") or len(name) > 255
                    or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?", name)):
                raise ValueError("符号名称无效：请输入合法的单个文件夹名称，不能含路径或 Windows 保留名称")
            target = destination / name
            if any(entry.name.casefold() == name.casefold() for entry in destination.iterdir()):
                raise ValueError("符号名称已存在，请使用符号目录中唯一的名称")
            if destination == resource or resource in destination.parents:
                raise ValueError("符号目录不能位于资源目录内，以免形成递归关联")
            volumes = [volume_info(resource), volume_info(destination)]
            return {"mode": mode, "resource": str(resource), "path": str(target),
                    "message": "；".join(volumes) + "；名称可用"}
        if mode == "include":
            gimi = directory(self.config.get_gimi_dir(), "设置中的 GIMI 目录")
            if resource == gimi or resource.parent != gimi.parent:
                raise ValueError("INCLUDE 要求资源目录与 GIMI 目录位于同一个父目录下")
            mods = gimi / "Mods"
            if not mods.is_dir() or mods.resolve().parent != gimi:
                raise ValueError("GIMI\\Mods 必须是 GIMI 中已存在的本地目录")
            target = mods / "modFolder.ini"
            relative = os.path.relpath(resource, mods).replace("/", "\\")
            if any(ch in relative for ch in "\r\n"):
                raise ValueError("资源路径不能包含换行")
            content, encoding, fingerprint, duplicate = include_content(target, relative)
            return {"mode": mode, "resource": str(resource), "path": str(target),
                    "content": content, "encoding": encoding, "fingerprint": fingerprint,
                    "alreadyIncluded": duplicate,
                    "message": "该资源目录已包含，无需重复添加" if duplicate else
                    "将在排除规则上方添加包含路径" if fingerprint else "资源目录与 GIMI 同级，配置路径可用"}
        raise ValueError("未知关联方式")

    def create(self, params):
        result = self.validate(params)
        if result["mode"] == "junction":
            import _winapi
            _winapi.CreateJunction(result["resource"], result["path"])
        else:
            if result["alreadyIncluded"]:
                return result
            target = Path(result["path"])
            data = result["content"].encode(result["encoding"])
            if result["fingerprint"] is None:
                with target.open("xb") as stream:
                    stream.write(data)
            else:
                descriptor, temporary = tempfile.mkstemp(prefix='.modFolder-', suffix='.tmp', dir=target.parent)
                try:
                    with os.fdopen(descriptor, 'wb') as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                    if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != result['fingerprint']:
                        raise ValueError("modFolder.ini 已发生变化，请重新添加")
                    os.replace(temporary, target)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
        message = "包含路径已添加" if result.get('fingerprint') else "关联已创建"
        return {**result, "message": f"{message}：{result['path']}"}
