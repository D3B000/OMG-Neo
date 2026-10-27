"""Standalone Windows console TUI for local OMG-Neo portable updates."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import time


def menu_key() -> str:
    print('  操作 > ', end='', flush=True)
    if os.name == 'nt' and sys.stdin.isatty():
        import msvcrt
        while True:
            key = msvcrt.getwch()
            if key == '\x03':
                raise KeyboardInterrupt
            if key in ('\x00', '\xe0'):
                msvcrt.getwch()
                continue
            if key in '01234567':
                print(key, flush=True)
                return key
    # Keep redirected input usable for automation and integration checks.
    return input().strip()

from engine import Updater, inspect_package, preview_payload, write_manifest, validate_payload
from sources import GitHubSource, local_package, same_version


def clean(value) -> str:
    return ''.join(c if c == '\n' or ord(c) >= 32 else '?' for c in str(value))


class TUI:
    def __init__(self, target: str = '', package: str = '', sha256: str = ''):
        self.target, self.package, self.sha256 = target, package, sha256
        self.last_progress = 0.0
        self.last_stage = ''
        self.ansi = False
        if os.name == 'nt' and sys.stdout.isatty():
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GetStdHandle.restype = ctypes.c_void_p
            kernel.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            kernel.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            handle = kernel.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            if kernel.GetConsoleMode(handle, ctypes.byref(mode)):
                self.ansi = bool(kernel.SetConsoleMode(handle, mode.value | 4))
            # Legacy conhost pauses the process when Quick Edit selects output.
            # Enter releases that selection, which looks like a stalled copy.
            input_handle = kernel.GetStdHandle(-10)
            if kernel.GetConsoleMode(input_handle, ctypes.byref(mode)):
                kernel.SetConsoleMode(input_handle, (mode.value | 0x80) & ~0x40)

    def screen(self, title: str):
        if self.ansi:
            print('\x1b[2J\x1b[H\x1b[36m', end='')
        print('═' * 66)
        print('  OMG-NEO  //  PORTABLE UPDATER  v0.0.1')
        print('  ' + title)
        print('═' * 66)
        if self.ansi:
            print('\x1b[0m', end='')

    def progress(self, stage: str, detail: str, done: int = 0, total: int = 0):
        now = time.monotonic()
        if stage == self.last_stage and now - self.last_progress < .1:
            return
        self.last_progress = now
        self.last_stage = stage
        suffix = f' [{done}/{total}]' if total else ''
        # Short enough for the default console; full paths remain in the journal.
        print('\r' + clean(f'  {stage}{suffix}  {detail}')[:100].ljust(100), end='', flush=True)

    def updater(self) -> Updater:
        if not self.target:
            raise ValueError('请先设置安装目录。')
        return Updater(local_package(self.target), self.progress)

    def inspect(self):
        updater = self.updater()
        updater.current()
        updater.idle()
        if not self.package:
            raise ValueError('请先添加本地更新 ZIP。')
        package = inspect_package(local_package(self.package), self.sha256.strip())
        metadata = preview_payload(package)
        self.screen('04 / 更新预览')
        print('  安装目录：' + clean(updater.target))
        print('  更新包：  ' + clean(package.path))
        print('  包版本：  ' + clean(metadata['version']))
        print('  模式：    ' + clean(metadata['configuration']))
        print(f'  解压程序大小：{package.size / 1024**2:.1f} MiB / {len(package.files)} 文件')
        print('  SHA-256： ' + package.sha256)
        print('  哈希核对：' + ('已与提供值／SHA-256 文件匹配' if package.hash_verified else '未提供外部校验值，仅计算本地哈希'))
        print('  备份位置：' + clean(updater.workspace))
        print('\n  保留：AppData、ui-reviews 和其他非程序根目录文件。')
        print('  整体替换：前端 EXE／DLL、data、backend、程序说明与清单。')
        print('  同版本重建与 Debug／Release 互换均允许。')
        print('  请使用可信本地包；普通 SHA-256 不代表发布者签名。')
        return updater, package

    def update(self):
        updater, package = self.inspect()
        print('\n  旧安装目录会完整保存在备份中，不自动清理。')
        if input('  按回车开始更新，输入其他内容后回车返回：') != '':
            return
        self.screen('05 / 正在更新 · 准备阶段可 Ctrl+C 取消')
        work = updater.apply(package.path, self.sha256.strip(), reviewed_sha256=package.sha256)
        print('\n\n  更新完成。安装路径保持不变。')
        print('  旧版完整备份：' + clean(work / 'backup'))
        print('  可直接从原目录启动 OMG-Neo；更新器不会自动启动游戏或应用。')
        input('\n  按回车返回菜单…')

    def github(self):
        updater = self.updater()
        updater.current()
        current = validate_payload(updater.target)
        source = GitHubSource(status=lambda message: print('  ' + clean(message)))
        self.screen('07 / GitHub 最新版本')
        # Official portable releases are Release builds, including for Debug installations.
        release = source.check_latest('Release')
        print('  当前版本：' + clean(current['version']))
        print('  最新版本：' + clean(release.version))
        if same_version(current['version'], release.version):
            print('  版本相同，无需更新。')
            input('\n  按回车返回菜单…')
            return
        package = source.fetch_release(release, updater.workspace / 'downloads')
        self.package, self.sha256 = str(package), release.sha256
        self.update()

    def recovery(self):
        updater = self.updater()
        records = updater.transactions()
        self.screen('06 / 恢复与回退')
        if not records:
            print('  此安装目录没有更新记录。')
            input('  按回车返回…')
            return
        shown = records[:30]
        for index, (path, record) in enumerate(shown, 1):
            print(clean(f'  {index:02}  {path.name}  {record["state"]}  {record.get("version", "")}'))
        answer = input('\n  选择记录编号（直接回车返回）：').strip()
        if not answer:
            return
        path, record = shown[int(answer) - 1] if 1 <= int(answer) <= len(shown) else (None, None)
        if path is None:
            raise ValueError('编号超出范围。')
        if record['state'] == 'installed':
            print('  将回退到该次更新前的程序，保留目前的 AppData 和导出文件。')
            if input('  输入 ROLLBACK 确认：').strip() == 'ROLLBACK':
                work = updater.rollback(path)
                print('\n  回退完成；回退前完整目录保存在：' + clean(work / 'backup'))
        elif record['state'] not in {'rolled_back', 'aborted'}:
            print('  将恢复被中断操作之前的完整安装目录。')
            if input('  输入 RECOVER 确认：').strip() == 'RECOVER':
                updater.recover(path)
                print('\n  中断恢复完成。')
        else:
            print('  该记录已结束，无需恢复。')
        input('\n  按回车返回…')

    def run(self) -> int:
        while True:
            self.screen('GitHub／本地 ZIP 更新 · 请先正常退出 OMG-Neo')
            print('  安装目录：' + clean(self.target or '未选择'))
            print('  更新包：  ' + clean(self.package or '未选择'))
            print('  校验值：  ' + ('已手动设置' if self.sha256 else '自动读取 ZIP 旁的 .sha256（如有）'))
            print('\n  [1] 选择安装目录    [2] 添加本地 ZIP\n  [3] 设置 SHA-256    [4] 检查／预览\n  [5] 执行更新        [6] 恢复／回退\n  [7] GitHub 最新版本 [0] 退出\n')
            try:
                choice = menu_key()
                if choice == '0':
                    return 0
                if choice == '1':
                    self.target = input('  输入或拖入安装目录（包含 omg_neo.exe）：').strip()
                elif choice == '2':
                    self.package = input('  输入或拖入更新 ZIP：').strip()
                    self.sha256 = ''
                elif choice == '3':
                    self.sha256 = input('  输入 SHA-256 或拖入 .sha256 文件（留空自动读取）：').strip()
                elif choice == '4':
                    self.inspect()
                    input('\n  按回车返回…')
                elif choice == '5':
                    self.update()
                elif choice == '6':
                    self.recovery()
                elif choice == '7':
                    self.github()
            except EOFError:
                return 0
            except KeyboardInterrupt:
                print('\n  已取消；若切换曾被中断，请在恢复菜单检查记录。')
                try:
                    input('  按回车返回…')
                except (KeyboardInterrupt, EOFError):
                    return 130
            except Exception as exc:
                print('\n\n  操作未完成：' + clean(exc))
                try:
                    input('\n  按回车返回菜单…')
                except (KeyboardInterrupt, EOFError):
                    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description='OMG-Neo 本地 ZIP TUI 更新器')
    parser.add_argument('--install-dir', default='')
    parser.add_argument('--package', default='')
    parser.add_argument('--sha256', default='', help='SHA-256 值或 .sha256 文件路径')
    parser.add_argument('--create-manifest', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--version', default='0.0.1+1', help=argparse.SUPPRESS)
    parser.add_argument('--configuration', choices=('Debug', 'Release'), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.create_manifest:
        if not args.configuration:
            parser.error('--create-manifest requires --configuration')
        write_manifest(args.create_manifest, args.version, args.configuration)
        print('更新清单已生成。')
        return 0
    if os.name != 'nt':
        parser.error('TUI 更新器仅支持 Windows。')
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    return TUI(args.install_dir, args.package, args.sha256).run()


if __name__ == '__main__':
    raise SystemExit(main())
