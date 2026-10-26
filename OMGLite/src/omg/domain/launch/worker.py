"""
launch.worker — 注入执行线程（QThread）。

职责：
  1. patch GIMI 目录下的 d3dx.ini（在引擎启动前就位，否则 d3d11 的
     verify_intended_target() 可能失败）；
  2. 构造并执行 MigotoInjector.run()（方案 B：hook → 启动进程 → 早/晚期注入校验
     → 等窗口）。

所有 UI 刷新都通过 Signal 发出，worker 不直触任何控件。未捕获异常会被捕获并
转为 finished(False, ...) ，主线程不会因此崩溃。

注：按设计 v2，INJECTING 态按钮是禁用的，故本 worker 不实现取消逻辑
（无 UI 触发点）。若后续需要可中断注入，再扩展 stop_event 接入
MigotoInjector 的中断点。
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from omg.domain.inject.errors import InjectorError
from omg.domain.inject.launcher import MigotoInjector
from omg.domain.inject.loader import patch_d3dx_ini

from .types import LaunchState, LaunchTask

logger = logging.getLogger("OMG")


class LaunchWorker(QThread):
    """在独立线程中执行一次启动 / 注入编排。"""

    state_changed = Signal(str, str)   # (state, detail)
    log_line = Signal(str)             # 引擎日志行（可选）
    finished = Signal(bool, str)       # (ok, message)

    def __init__(self, task: LaunchTask, *, verify_injection: bool = True) -> None:
        super().__init__()
        self._task = task
        self._verify_injection = verify_injection
        self.verification_state = "not_checked"

    # ------------------------------------------------------------------
    # 主执行体
    # ------------------------------------------------------------------
    def run(self) -> None:  # noqa: D401 - QThread.run override
        task = self._task

        # (1) patch d3dx.ini（在方案 B 之前）
        ini_path = Path(task.gimi_dir) / "d3dx.ini"
        if not ini_path.is_file():
            self.finished.emit(False, f"找不到 d3dx.ini: {ini_path}")
            return
        try:
            # 幂等：所有目标值与现值一致时不会写盘，返回值用于区分「已更新 / 无需改动」
            changed = patch_d3dx_ini(
                ini_path,
                task.d3dx_target,
                task.d3dx_hunting,
                task.d3dx_warning,
                launch=task.d3dx_launch,
                loader=task.d3dx_loader,
            )
            if changed:
                logger.info(
                    "d3dx.ini 已更新: target=%s, hunting=%s, show_warnings=%s, "
                    "launch=%s, loader=%s",
                    task.d3dx_target, task.d3dx_hunting, task.d3dx_warning,
                    task.d3dx_launch if task.d3dx_launch is not None else "(保持原样)",
                    task.d3dx_loader,
                )
            else:
                logger.info(
                    "d3dx.ini 无需改动（目标值与现值一致）: target=%s, hunting=%s, "
                    "show_warnings=%s, launch=%s, loader=%s",
                    task.d3dx_target, task.d3dx_hunting, task.d3dx_warning,
                    task.d3dx_launch if task.d3dx_launch is not None else "(保持原样)",
                    task.d3dx_loader,
                )
        except Exception as e:  # patch 失败不致命，仍尝试注入
            logger.error("修改 d3dx.ini 失败: %s", e)

        # (2) 执行引擎（方案 B）
        self.state_changed.emit(LaunchState.INJECTING.value, "正在注入…")
        try:
            injector = MigotoInjector(task.request, Path(task.injector_path))
            if not self._verify_injection:
                injector.run(verify_injection=False)
                self.verification_state = "skipped" if task.request.use_xxmi_dll else "bypassed"
                message = ("游戏已启动，注入流程已执行" if task.request.use_xxmi_dll
                           else "游戏已启动（已跳过 d3d11.dll 注入）")
                self.finished.emit(True, message)
                return
            injector.run()
            if task.request.use_hook and task.request.use_xxmi_dll:
                engine = injector.injector
                verified = engine.last_check.get("native") is True or engine.last_check_verified_by_probe()
                if not verified:
                    inconclusive = engine.last_check_inconclusive()
                    self.verification_state = "inconclusive" if inconclusive else "failed"
                    reason = ("无法确认（模块表不可读取）" if inconclusive
                              else "未通过")
                    detail = engine.describe_last_check()
                    logger.warning("游戏已启动，但注入校验%s：%s", reason, detail)
                    self.finished.emit(inconclusive, f"游戏已启动，但注入校验{reason}：{detail}")
                    return
            self.verification_state = "verified" if task.request.use_xxmi_dll else "bypassed"
            message = ("游戏已启动，注入完成" if task.request.use_xxmi_dll
                       else "游戏已启动（已跳过 d3d11.dll 注入）")
            self.finished.emit(True, message)
        except InjectorError as e:
            logger.error("注入失败: %s", e)
            self.finished.emit(False, str(e))
        except Exception as e:
            logger.exception("启动过程发生未捕获异常")
            self.finished.emit(False, f"内部异常: {type(e).__name__}: {e}")
