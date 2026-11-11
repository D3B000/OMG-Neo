"""Shared d3dx.ini settings and atomic writes."""

import os
import re
import threading
import time
from pathlib import Path


# 写入纪律：串行化 + 原子替换
# ---------------------------------------------------------------------------
# 进程内所有 d3dx.ini 写者共用这一把锁。d3dx.ini 的改写是典型的
# read-modify-write：「读全文 → 改几行 → 整份写回」。若两个写者交错，后写的
# 会用自己读到的旧快照覆盖掉前一个写者的全部改动。
#
# 现存的写者：
#   - UI 线程：设置页改 hunting / show_warnings（去抖后调用）
#   - 启动 worker（QThread）：启动前写 target / launch / loader
# 因此 read 也必须放进锁内的最后一刻，不能提前到临界区之外。
D3DX_WRITE_LOCK = threading.RLock()

# os.replace 在目标文件被别的进程以 FILE_SHARE_READ 打开时会 PermissionError
# ——3DMigoto 的 Injector 正是这样读 d3dx.ini 的。它的读取窗口只有几毫秒，
# 短暂重试即可跨过去；反复失败则说明文件被长期占用（编辑器/杀软），放弃。
_REPLACE_ATTEMPTS = 4
_REPLACE_DELAY = 0.03


def _atomic_replace_text(ini_path: Path, text: str) -> None:
    """把 *text* 原子地写入 *ini_path*：同目录写 ``.tmp`` 后 ``os.replace``。

    与 ``Path.write_text``（先 truncate 再写）的关键差别：目标文件在任意时刻
    要么是完整的旧内容、要么是完整的新内容，不存在「空文件 / 半截文件」的中间
    态。写一半失败只会留下一个 ``.tmp``，目标文件一个字节都不会变。

    失败时抛出最后一次的 OSError（并由 ``finally`` 清理 ``.tmp`` 残留）。
    """
    tmp_path = ini_path.with_name(ini_path.name + ".tmp")
    last_error: BaseException | None = None
    try:
        tmp_path.write_text(text, encoding="utf-8")
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(tmp_path, ini_path)
                return
            except OSError as e:
                last_error = e
                if attempt < _REPLACE_ATTEMPTS - 1:
                    time.sleep(_REPLACE_DELAY)
        raise last_error
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


# ini 值行：`值` + 可选的行尾注释（`;` 及其后内容，连同前面的间隔一起保留）
_INI_LINE_RE = re.compile(r"^(?P<value>.*?)(?P<comment>[ \t]*;.*)?$")


def patch_d3dx_ini_values(ini_path: Path, values: dict,
                          create_missing: bool = True) -> bool:
    """幂等地把 ``values`` 写入 d3dx.ini。

    Args:
        ini_path: d3dx.ini 路径。
        values: ``{(section_lower, key_lower): 目标值}``。
        create_missing: 键不存在时是否新建（插到所属 section 首行之后）。

    Returns:
        True 表示确有改动并已写盘；False 表示所有键现值都与目标一致，
        文件一字未动（不刷新 mtime，也不会吃掉行尾注释）。
    """
    # 读取必须在锁内：这是「读到的不是最新快照就无法安全写回」的必要条件。
    with D3DX_WRITE_LOCK:
        return _patch_d3dx_ini_values_locked(ini_path, values, create_missing)


def _patch_d3dx_ini_values_locked(ini_path: Path, values: dict,
                                  create_missing: bool) -> bool:
    lines = ini_path.read_text(encoding="utf-8", errors="ignore").splitlines(True)

    patched_keys = set()
    current_section = ""
    changed = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and "]" in stripped:
            current_section = stripped[1:stripped.index("]")].strip().lower()
            continue
        if "=" in stripped and not stripped.startswith(";") and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip().lower()
            lookup = (current_section, key)
            if lookup in values:
                patched_keys.add(lookup)
                raw_value = stripped.split("=", 1)[1]
                # d3dx.ini 支持行尾注释（如 `hunting = 0 ; 保持关闭`）：比较时
                # 只看注释之前的部分，改写时把注释连同前面的间隔原样接回去。
                match = _INI_LINE_RE.match(raw_value)
                current_value = (match.group("value") or "").strip()
                suffix = match.group("comment") or ""

                if values[lookup] is None:
                    # 本次不写入该键。但若盘上是个空值行（历史版本留下的
                    # `launch = `），3DMigoto 读到空值会在游戏内左上角报
                    # 警告，这里顺手注释掉，做一次自愈。
                    if current_value == "":
                        lines[i] = ";" + line
                        changed = True
                    continue

                target_value = str(values[lookup]).strip()
                if current_value == target_value:
                    continue
                lines[i] = f"{key} = {values[lookup]}{suffix}\n"
                changed = True

    if create_missing:
        for lookup, value in values.items():
            if lookup in patched_keys or value is None:
                continue
            section_name, key = lookup
            section_found = False
            for i, line in enumerate(lines):
                s = line.strip()
                if s.startswith("[") and "]" in s:
                    sec = s[1:s.index("]")].strip().lower()
                    if sec == section_name:
                        lines.insert(i + 1, f"{key} = {value}\n")
                        section_found = True
                        break
            if not section_found:
                lines.append(f"\n[{section_name}]\n")
                lines.append(f"{key} = {value}\n")
            changed = True

    if changed:
        _atomic_replace_text(ini_path, "".join(lines))
    return changed


# 可在游戏运行中热更新的键（3DMigoto 支持按键 reload ini）
D3DX_RUNTIME_KEYS = (("hunting", "hunting"), ("logging", "show_warnings"))


def patch_d3dx_runtime_options(ini_path: Path, hunting: int,
                               show_warnings: int) -> bool:
    """只写 [Hunting] hunting 与 [Logging] show_warnings（幂等）。

    这两个键被 3DMigoto 注册为 reloadable，游戏运行中改完 ini 再按 reload
    键即可生效，因此关闭设置时也要落盘（不再等到下次启动）。
    """
    return patch_d3dx_ini_values(ini_path, {
        ("hunting", "hunting"): str(hunting),
        ("logging", "show_warnings"): str(show_warnings),
    })
