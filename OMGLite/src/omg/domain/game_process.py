"""Game executable discovery and read-only Windows process queries."""

import ctypes
from pathlib import Path
from typing import List, Optional, Tuple

TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value  # -1


class _PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("cntUsage", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", ctypes.c_ulong),
        ("cntThreads", ctypes.c_ulong),
        ("th32ParentProcessID", ctypes.c_ulong),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _kernel32():
    return ctypes.windll.kernel32


def find_game_exe(game: Path):
    """Return (game_exe: Path, target: str) for the game in *game*."""
    exe_files = [f for f in game.iterdir() if f.suffix.lower() == ".exe"]
    if not exe_files:
        return None, None

    game_exe = exe_files[0]
    for f in exe_files:
        name_lower = f.name.lower()
        if "genshinimpact" in name_lower or "yuanshen" in name_lower:
            game_exe = f
            break

    return game_exe, game_exe.name


def enum_processes() -> List[Tuple[int, str]]:
    """返回 [(pid, exe_name), ...]，等价于 psutil.process_iter 的最小实现。"""
    kernel32 = _kernel32()
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE or snap is None:
        return []

    pe = _PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(pe)
    out: List[Tuple[int, str]] = []
    try:
        if kernel32.Process32FirstW(snap, ctypes.byref(pe)):
            while True:
                out.append((int(pe.th32ProcessID), pe.szExeFile))
                if not kernel32.Process32NextW(snap, ctypes.byref(pe)):
                    break
    finally:
        kernel32.CloseHandle(snap)
    return out


def get_process(process_id: Optional[int] = None,
                process_name: Optional[str] = None) -> Optional[Tuple[int, str]]:
    """按名或 PID 查找进程，返回 (pid, name)；找不到返回 None。

    等价于 XXMI 的 get_process()，但用 ctypes 实现。
    """
    want_name = process_name.lower() if process_name else None
    for pid, name in enum_processes():
        if process_id is not None and pid == process_id:
            return pid, name
        if want_name is not None and name.lower() == want_name:
            return pid, name
    return None


def is_process_running(name: str) -> bool:
    """单次快照判断进程是否存在（心跳 / 安全网检查用）。"""
    return get_process(process_name=name) is not None
