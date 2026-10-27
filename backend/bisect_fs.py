"""Exact same-parent renames. Windows pins the entry and its ancestor chain.

No overwrite, name uniquification, copying, unlinking, or permission changes.
"""
from contextlib import ExitStack, contextmanager
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import stat


def identity(path, follow=True):
    s = Path(path).stat() if follow else Path(path).lstat()
    if not s.st_ino and os.name == 'nt':
        class FileInfo(ctypes.Structure):
            _fields_ = [('attributes', wintypes.DWORD), ('created', wintypes.FILETIME),
                        ('accessed', wintypes.FILETIME), ('written', wintypes.FILETIME),
                        ('volume', wintypes.DWORD), ('sizeHigh', wintypes.DWORD),
                        ('sizeLow', wintypes.DWORD), ('links', wintypes.DWORD),
                        ('indexHigh', wintypes.DWORD), ('indexLow', wintypes.DWORD)]
        with _handle(path, 0x80, reparse=not follow) as handle:
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            read = kernel.GetFileInformationByHandle
            read.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInfo)]
            info = FileInfo()
            if not read(handle, ctypes.byref(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            return [str(info.volume), str((info.indexHigh << 32) | info.indexLow), stat.S_IFMT(s.st_mode)]
    if not s.st_ino:
        raise ValueError(f"文件系统无法提供稳定身份：{path}")
    return [str(s.st_dev), str(s.st_ino), stat.S_IFMT(s.st_mode)]


def is_link(path):
    s = Path(path).lstat()
    return bool(getattr(s, 'st_file_attributes', 0) & 1024) or Path(path).is_symlink()


def supported(path):
    if os.name != 'nt':
        return
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    volume = ctypes.create_unicode_buffer(32768)
    if not kernel.GetVolumePathNameW(str(Path(path).resolve()), volume, len(volume)):
        raise ctypes.WinError(ctypes.get_last_error())
    if kernel.GetDriveTypeW(volume.value) != 3:
        raise ValueError('二分启停只支持本地固定磁盘，不支持网络盘或可移动磁盘')
    fs = ctypes.create_unicode_buffer(256)
    if not kernel.GetVolumeInformationW(volume.value, None, 0, None, None, None, fs, len(fs)):
        raise ctypes.WinError(ctypes.get_last_error())
    if fs.value.upper() != 'NTFS':
        raise ValueError('二分精确启停当前仅支持 NTFS')
    s = Path(path).lstat()
    if getattr(s, 'st_file_attributes', 0) & (0x1000 | 0x40000 | 0x400000):
        raise ValueError(f'不支持离线或云占位资源：{path}')
    if is_link(path):
        tag = getattr(s, 'st_reparse_tag', 0)
        if tag != 0xA0000003:  # directory junction; file symlinks/cloud tags aren't writable here
            raise ValueError(f'不支持的重解析点类型：{path}')


@contextmanager
def _handle(path, access, reparse=True):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    # Deliberately do NOT share DELETE: a competing rename/replacement must fail.
    value = create(str(path), access, 3, None, 3,
                   0x02000000 | (0x00200000 if reparse else 0), None)
    if value == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield value
    finally:
        close(value)


def rename_exact(source, destination, validate):
    source, destination = Path(source), Path(destination)
    if source.parent != destination.parent or source == destination:
        raise ValueError('只允许同一父目录内的精确改名')
    if os.name != 'nt':
        validate()
        if os.path.lexists(destination):
            raise FileExistsError(f'目标已存在，未覆盖：{destination}')
        # Non-Windows is used by isolated unit fixtures only; production is Windows.
        os.rename(source, destination)
        return
    supported(source)
    with ExitStack() as stack:
        # Pin both the logical path (including junction entries) and its resolved
        # ancestors. A check followed by a plain path-based rename is insufficient.
        pinned = set()
        for parent in (source.parent, source.parent.resolve(strict=True)):
            for directory in reversed([parent, *parent.parents]):
                key = os.path.normcase(str(directory))
                if key not in pinned:
                    stack.enter_context(_handle(directory, 0x80))
                    pinned.add(key)
        entry = stack.enter_context(_handle(source, 0x10000 | 0x80))
        validate()
        if os.path.lexists(destination):
            raise FileExistsError(f'目标已存在，未覆盖：{destination}')
        name = str(destination.absolute())
        encoded = name.encode('utf-16-le')
        class RenameInfo(ctypes.Structure):
            _fields_ = [('ReplaceIfExists', wintypes.BOOLEAN),
                        ('RootDirectory', wintypes.HANDLE), ('FileNameLength', wintypes.DWORD),
                        ('FileName', ctypes.c_ubyte * (len(encoded) + 2))]
        info = RenameInfo()
        info.ReplaceIfExists, info.RootDirectory, info.FileNameLength = False, None, len(encoded)
        ctypes.memmove(ctypes.addressof(info) + RenameInfo.FileName.offset, encoded, len(encoded))
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        rename = kernel.SetFileInformationByHandle
        rename.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        rename.restype = wintypes.BOOL
        if not rename(entry, 3, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
