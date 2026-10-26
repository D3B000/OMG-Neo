"""
omg.core.gimi_update — GIMI 框架「检查更新 / 下载部署」编排层。

职责（从 OMGDev/main.py 的 fetch_latest_release / download_and_deploy_gimi /
_version_eq 抽取并适配 OMGLite 结构）：
- 查询 GitHub 上 GIMI-Package 最新 release（GitHub API → HTML 抓取兜底）。
- 语义化版本比较（正确处理 GIMI main.ini 的 ``8.90`` → ``8.9.0`` 归一化，
  该归一化在 omg.core.paths.read_gimi_version_from_ini 内完成，故本地版本
  拿到手已是 ``8.9.0`` 形式；本模块只负责把远端 tag 的 ``v`` 前缀与预发布
  后缀剥掉后做整数元组比较）。
- 下载 release zip（复用 omg.core.download 的多代理 failover / 断点续传）并
  部署到 GIMI 目录（复用 omg.core.updates.deploy_gimi_update 的白名单解压）。
- 以 QThread 形态暴露 check / update 两个异步步骤，供 UI 层（home.py）驱动
  两次点击流程（点击检查 → 点击更新）。

所有网络 / 磁盘 IO 均在线程内同步执行，通过信号回传结果，绝不阻塞 UI 线程。
"""

from __future__ import annotations

import os
import re
import time
import tempfile
import logging
import threading

from PySide6.QtCore import QObject, QThread, Signal

from omg.core import download
from omg.core import updates
from omg.core.paths import read_gimi_version_from_ini
from omg.core.logging_setup import logger

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
GIMI_OWNER = "SilentNightSound"
GIMI_REPO = "GIMI-Package"
GIMI_API_URL = f"https://api.github.com/repos/{GIMI_OWNER}/{GIMI_REPO}/releases/latest"
GIMI_RELEASES_URL = f"https://github.com/{GIMI_OWNER}/{GIMI_REPO}/releases/latest"

#: 自动检查的最小间隔（秒）。GitHub 匿名 API 配额只有 60 次/小时/IP，
#: 而 OMGLite 每次开窗口都会自动检查一次（auto_check_update 默认开），
#: 一天开关几十次窗口就足以把自己限流。故对齐 XXMI-Launcher 的做法做节流。
CHECK_THROTTLE_SEC = 3600

#: 持久化键：上次**成功**检查的 Unix 时间戳（0 = 从未检查）。
KEY_CHECKED_AT = "gimi_update_checked_at"


def should_throttle_check(config, interval_sec: int = CHECK_THROTTLE_SEC) -> bool:
    """距上次成功检查不足 ``interval_sec`` 则跳过本次自动检查。

    只对**自动**检查生效；用户手动点「检查更新」必须永远真正发起请求
    （否则用户明明点了却看到「已是最新」，会以为是 bug）。
    """
    try:
        last = int(config.get(KEY_CHECKED_AT, 0) or 0)
    except (TypeError, ValueError):
        last = 0
    if last <= 0:
        return False
    return (time.time() - last) < interval_sec


def mark_checked(config) -> None:
    """记录一次成功检查的时间戳（落盘，供下次启动节流判断）。"""
    try:
        config.set(KEY_CHECKED_AT, int(time.time()))
        config.save()
    except Exception as exc:  # 节流信息写盘失败不应影响检查结果
        logger.debug(f"记录更新检查时间失败: {exc}")


# ---------------------------------------------------------------------------
# 进度 / 状态信号（与 omg.core.download 的 DownloadSignals 对齐）
# ---------------------------------------------------------------------------
class DownloadSignals(QObject):
    """下载进度 / 状态 / 完成信号。

    与 omg.core.download.download_file_smart 期望的 signals 形状一致：
      - progress(float 0~100)
      - status(str, str)   # (message, role)
      - finished(bool, str)
    """

    status = Signal(str, str)
    progress = Signal(float)
    finished = Signal(bool, str)


# ---------------------------------------------------------------------------
# 版本比较（鲁棒 + 语义化）
# ---------------------------------------------------------------------------
def _parse_version(ver: str):
    """把版本字符串解析为可比较的整数元组（最多 3 段，缺省补 0）。

    处理：去除 ``v``/``V`` 前缀、剥离预发布（``-beta``）与构建元数据（``+build``）。
    例： ``v8.9.0`` → (8,9,0)，``8.9`` → (8,9,0)，``8.10.1-beta`` → (8,10,1)，```` → ()。
    """
    ver = (ver or "").strip().lstrip("vV")
    # 去掉预发布 / 构建元数据
    ver = ver.split("-")[0].split("+")[0]
    if not ver:
        return ()
    parts = []
    for p in ver.split(".")[:3]:
        try:
            parts.append(int(p))
        except (ValueError, TypeError):
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _has_version_number(ver: str) -> bool:
    """版本串里是否**至少有一个可解析的数字段**。

    与 :func:`_parse_version` 配套：后者对无法解析的段一律补 0 并补齐到 3 段，
    于是 ``"nightly"`` 也会得到 ``(0, 0, 0)``——直接拿来比较会把「无法确认」
    伪装成「版本相同」。本函数专门用于区分这两种情况。

    注意不要改 ``_parse_version`` 的返回形状：``core.alchemy`` 拿它当
    ``sort(key=...)`` 的排序键，元组长度不一致会在混合排序时抛 TypeError。
    """
    ver = (ver or "").strip().lstrip("vV").split("-")[0].split("+")[0]
    if not ver:
        return False
    for p in ver.split(".")[:3]:
        try:
            int(p)
            return True
        except (ValueError, TypeError):
            continue
    return False


def compare_versions(a: str, b: str) -> int:
    """返回 -1 / 0 / 1，表示 a 小于 / 等于 / 大于 b。

    **无法解析出数字段时一律返回 -1**（视为「需要更新」），除非两边都是空串。

    原因：``CheckThread`` 用 ``compare_versions(local, remote) > 0`` 来判
    「本地比远端新 → 已是最新」。若远端 tag 是个没有数字段的非常规字符串
    （如 ``nightly``），而我们返回 1，就会把一个**无法确认**的状态报成
    「已是最新」——这正是原实现静默补 0 造成的隐患。宁可多提示一次更新，
    也不能让用户永远看不到可用更新。
    """
    a_s, b_s = (a or "").strip(), (b or "").strip()
    if not a_s and not b_s:
        return 0                      # 两边都无版本信息，确实无从比较
    if not _has_version_number(a) or not _has_version_number(b):
        return -1                     # 任一边不可解析 → 保守判「需要更新」
    pa, pb = _parse_version(a), _parse_version(b)
    if pa < pb:
        return -1
    if pa > pb:
        return 1
    return 0


def version_eq(a: str, b: str) -> bool:
    """两个版本是否**确认**相等。

    只有两边都能解析出数字段、且数值完全一致时才为 True。不可解析时返回
    False —— 否则远端换成非常规 tag 就会永远提示「已是最新」。
    两边都是空串视为相等（确实没有任何版本信息）。
    """
    a_s, b_s = (a or "").strip(), (b or "").strip()
    if not a_s and not b_s:
        return True
    if not _has_version_number(a) or not _has_version_number(b):
        return False
    return _parse_version(a) == _parse_version(b)


# ---------------------------------------------------------------------------
# 查询最新 release
# ---------------------------------------------------------------------------
def fetch_latest_release(connect_status_cb=None) -> dict | None:
    """查询 GIMI-Package 最新 release。

    策略：GitHub API（1 次请求）→ HTML 抓取兜底（2 次请求）。
    多代理 failover / SSL 回退由 omg.core.download 内部处理。

    Args:
        connect_status_cb: 可选回调 fn(inner_0_1: float, label: str)，把「连接
            GitHub」阶段的真实进度反馈给 UI（inner 范围 0~1）。

    Returns:
        {"tag_name", "zip_url", "body"} 或 None（失败）。
    """
    def _emit(inner, label=""):
        if connect_status_cb:
            try:
                connect_status_cb(float(inner), label)
            except Exception:
                pass

    # --- 快速路径：GitHub API ---
    def _api_status(proxy_label, idx, total):
        local = 0.35 * ((idx + 1) / max(total, 1))
        _emit(local, f"通过 {proxy_label} · API")

    data = download.fetch_json_api_smart(GIMI_API_URL, status_cb=_api_status)
    if data and data.get("tag_name"):
        tag_name = data["tag_name"]
        body = data.get("body", "")
        for asset in data.get("assets", []):
            if asset.get("name", "").endswith(".zip"):
                zip_url = asset.get("browser_download_url", "")
                if zip_url:
                    logger.info("GIMI API 获取成功: %s", tag_name)
                    _emit(1.0)
                    return {"tag_name": tag_name, "zip_url": zip_url, "body": body}
        logger.info("GIMI API 无 .zip asset，回退 HTML 抓取")
        _emit(0.4)
    else:
        logger.info("GIMI API 不可用，回退 HTML 抓取")
        _emit(0.4)

    # --- 兜底：releases/latest HTML → expanded_assets HTML ---
    def _rel_status(proxy_label, idx, total):
        local = 0.4 + 0.32 * ((idx + 1) / max(total, 1))
        _emit(local, f"通过 {proxy_label} · releases")

    html = download.fetch_url_smart(GIMI_RELEASES_URL, status_cb=_rel_status)
    if not html:
        _emit(1.0)
        return None

    try:
        tag_matches = re.findall(r'/releases/tag/([^"\'&\s]+)', html)
        tag_name = ""
        for candidate in tag_matches:
            candidate = candidate.strip()
            if candidate and not candidate.startswith("*") and len(candidate) > 1:
                tag_name = candidate
                break
        if not tag_name:
            _emit(1.0)
            return None

        assets_url = (
            f"https://github.com/{GIMI_OWNER}/{GIMI_REPO}"
            f"/releases/expanded_assets/{tag_name}"
        )

        def _assets_status(proxy_label, idx, total):
            local = 0.72 + 0.28 * ((idx + 1) / max(total, 1))
            _emit(local, f"通过 {proxy_label} · assets")

        assets_html = download.fetch_url_smart(assets_url, status_cb=_assets_status)
        if not assets_html:
            _emit(1.0)
            return None

        zip_match = re.search(
            r'href="([^"]*?/releases/download/[^"]*?\.zip)"', assets_html
        )
        if not zip_match:
            _emit(1.0)
            return None
        zip_url = zip_match.group(1).strip()
        if zip_url.startswith("/"):
            zip_url = "https://github.com" + zip_url

        body = ""
        body_match = re.search(
            r'<div[^>]*class="[^"]*markdown-body[^"]*"[^>]*>(.*?)</div>',
            html, re.DOTALL,
        )
        if body_match:
            import html as _html_mod
            body = _html_mod.unescape(
                re.sub(r'<[^>]+>', '', body_match.group(1))
            ).strip()

        _emit(1.0)
        return {"tag_name": tag_name, "zip_url": zip_url, "body": body}
    except Exception as e:
        logger.warning("解析 releases 页面失败: %s", e)
        _emit(1.0)
        return None


def _clean_release_body(body: str) -> str:
    """剥离 release notes 中的 Warning / Signature 区块（轻量实现）。"""
    if not body:
        return body
    lines = body.split("\n")
    out, skip = [], False
    for line in lines:
        s = line.strip()
        is_header = bool(re.match(r'^#{1,3}\s+\w+', s)) or \
                    (re.match(r'^[A-Z][a-zA-Z]+$', s) and len(s) > 1)
        if is_header:
            header_text = re.sub(r'^#{0,3}\s*', '', s).lower()
            if header_text in ("warning", "signature"):
                skip = True
                continue
            skip = False
        if not skip:
            out.append(line)
    return "\n".join(out).strip()


def deploy_gimi_update(config, signals: DownloadSignals,
                       release_data: dict | None = None,
                       should_cancel=None, progress_cb=None) -> tuple[bool, str]:
    """下载并部署 GIMI 更新（同步，需在子线程调用）。

    Args:
        config: ConfigManager 实例（读 gimi 目录 / 白名单 / 刷新版本）。
        signals: DownloadSignals，回传进度与状态。
        release_data: 预取的 release 数据，避免重复请求。
        should_cancel: 可选无参可调用；返回 True 时中断下载 / 解压。
        progress_cb: 可选可调用 ``fraction(0~1)``；透传给解压阶段，供 UI 细分进度。

    Returns:
        (success, message)
    """
    logger.info("开始下载 GIMI")
    zip_path = os.path.join(tempfile.gettempdir(), "omg_gimi_latest.zip")

    data = release_data if release_data else fetch_latest_release()
    if not data:
        return False, "无法获取版本信息"
    zip_url = data.get("zip_url", "")
    release_tag = data.get("tag_name", "")
    if not zip_url:
        return False, "未找到下载链接"

    # 保存 release body 供 tooltip（持久化键 gimi_release_body / gimi_release_version）
    release_body = data.get("body", "")
    if release_body:
        config.set("gimi_release_body", _clean_release_body(release_body))
        config.set("gimi_release_version", release_tag)

    signals.status.emit("正在下载…", "info")
    ok, err = download.download_file_smart(
        zip_url, zip_path, signals=signals, should_cancel=should_cancel
    )
    if not ok:
        # 清理残留的临时 zip（下载阶段中断/失败：尚未触及 GIMI 目录）
        try:
            if os.path.exists(zip_path):
                os.remove(zip_path)
        except OSError:
            pass
        if err == "已取消":
            return False, "已取消"   # 下载阶段中断：无回退
        return False, f"下载失败: {err}"

    try:
        signals.status.emit("正在解压…", "info")
        deploy_dir = config.get_gimi_dir()
        whitelist = config.get("gimi_update_whitelist", []) or []
        ok, err = updates.deploy_gimi_update(
            zip_path, deploy_dir, whitelist, should_cancel=should_cancel,
            progress_cb=progress_cb,
        )
        if not ok:
            # err ∈ {"已取消，已回退", "解压失败: ..."}；回退由 updates 内部完成
            return False, err
        # 重新探测本地版本（一次 ini 读取，非轮询）
        config.refresh_versions()
        config.save()
        msg = f"GIMI 部署完成 ({release_tag})" if release_tag else "GIMI 部署完成"
        return True, msg
    except Exception as e:
        logger.error("GIMI 部署失败: %s", e, exc_info=True)
        return False, f"解压失败: {e}"


# ---------------------------------------------------------------------------
# 异步线程封装
# ---------------------------------------------------------------------------
# 注意：GimiUpdateSignals 已迁到轻量的 omg.core.gimi_signals（只依赖 QtCore）。
# 本模块顶层仍会 import urllib/ssl 这条重链，调用方应**惰性导入**本模块，
# 只在真正要检查/更新时才触达。这里保留同名导出以兼容既有引用。
from omg.core.gimi_signals import GimiUpdateSignals  # noqa: E402  (向后兼容重导出)


class CheckThread(QThread):
    """仅检查：查远端版本 + 与本地比较，emit check_result。

    Args:
        auto: True 表示「打开 OMG 时自动检查」（受 :data:`CHECK_THROTTLE_SEC`
            节流）；False 表示用户手动点击，必须真正发起请求。
    """

    def __init__(self, config, signals: GimiUpdateSignals, parent=None,
                 auto: bool = False):
        super().__init__(parent)
        self._config = config
        self._sig = signals
        self._cancel_event = threading.Event()
        self._auto = bool(auto)

    def request_cancel(self) -> None:
        """请求中断检查（网络往返结束后丢弃结果）。"""
        self._cancel_event.set()

    def run(self):
        # 重新读取本地 main.ini（一次磁盘读取，避免轮询）
        gimi_dir = self._config.get_gimi_dir()
        local = read_gimi_version_from_ini(gimi_dir) or self._config.get("gimi_version", "")

        # 自动检查才节流；被节流时按「无法确认」处理（不弹错误，静默保持现状）
        if self._auto and should_throttle_check(self._config):
            logger.info("距上次检查不足 1 小时，跳过本次自动检查")
            self._sig.check_result.emit("throttled", local, "", "检查已节流")
            return

        try:
            data = fetch_latest_release()
        except download.RateLimitedError as exc:
            # 限流要给出可执行提示，而不是笼统的「网络错误」
            self._sig.check_result.emit("error", local, "", str(exc))
            return

        # 检查可被用户中断：结果在往返结束后丢弃，不进入状态机
        if self._cancel_event.is_set():
            self._sig.check_result.emit("cancelled", local, "", "已取消")
            return
        if not data:
            self._sig.check_result.emit("error", local, "", "网络错误")
            return
        remote = (data.get("tag_name") or "").lstrip("vV")
        if not remote:
            self._sig.check_result.emit("error", local, "", "解析失败")
            return
        # 成功拿到远端版本才记节流时间戳：失败不该把下次自动检查也挡掉
        mark_checked(self._config)
        if version_eq(local, remote):
            self._sig.check_result.emit("up_to_date", local, remote, "已是最新版本")
        elif compare_versions(local, remote) > 0:
            # 本地比远端新 —— 无需更新
            self._sig.check_result.emit("up_to_date", local, remote, "已是最新版本")
        else:
            self._sig.check_result.emit("update_available", local, remote, "发现新版本")


class UpdateThread(QThread):
    """执行下载 + 部署，转发进度到 GimiUpdateSignals。"""

    def __init__(self, config, signals: GimiUpdateSignals,
                 release_data: dict | None, parent=None):
        super().__init__(parent)
        self._config = config
        self._sig = signals
        self._release = release_data
        self._cancel_event = threading.Event()

    def request_cancel(self) -> None:
        """请求中断更新：下载/解压循环会检测该事件并触发回退。"""
        self._cancel_event.set()

    def run(self):
        dl = DownloadSignals()
        # 阶段占比细分（避免进度圈在解压时静止后突然跳满）：
        #   下载   : 0   ~ 85%
        #   备份   : 85  ~ 86%（deploy 入口处一帧过渡）
        #   解压   : 86  ~ 99%（按成员数细分，见 progress_cb）
        #   完成   : 100%
        DL_END = 85.0
        EX_START = 86.0
        EX_END = 99.0
        dl.progress.connect(
            lambda p: self._sig.progress.emit(max(0.0, min(DL_END, float(p) * (DL_END / 100.0))))
        )
        dl.status.connect(lambda m, r: self._sig.status.emit(m, r))

        self._sig.progress.emit(2.0)
        ok, msg = deploy_gimi_update(
            self._config, dl, release_data=self._release,
            should_cancel=lambda: self._cancel_event.is_set(),
            # 解压阶段：把 0~1 的细分进度映射到 [EX_START, EX_END]
            progress_cb=lambda f: self._sig.progress.emit(
                EX_START + max(0.0, min(1.0, float(f))) * (EX_END - EX_START)
            ),
        )
        if ok:
            self._sig.progress.emit(100.0)
        self._sig.finished.emit(ok, msg)
