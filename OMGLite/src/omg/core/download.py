"""GitHub resources: actual requests, staggered fallback and per-network route cache.

Original URLs (following the system proxy), explicit direct connections and public
mirror URLs compete using real GET requests. Only the winning download writes to
disk. TLS certificates are verified on all automatically selected routes.
"""

import os
import ssl
import json
import time
import errno
import socket
import logging
import threading
import queue
import re
from urllib.parse import urlsplit
import urllib.request
import urllib.error
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)


# ============================================================
# 配置常量
# ============================================================

# GitHub HTTPS 加速代理列表 (按优先级排序)
# 这些代理通过 "代理前缀 + 原始 GitHub URL" 的形式转发请求
# 代理可能随时失效,优先级排序 + 自动 failover 保证可用性
#
# 优先级依据: speedTest.py 3 轮实测平均速度排序 (2026-08-19)
#   #1 gh-proxy.com      0.96 MB/s  100% 成功率 (最快且稳定)
#   #2 ghproxy.net       0.26 MB/s  100% 成功率 (稳定备选)
#   #3 githubproxy.cc    0.01 MB/s   67% 成功率 (可用但慢)
#   #4-6 以下为备选,本次测试失败但可能是临时问题 (DNS/SSL/超时),保留兜底
#
# 已移除 (实测确认不可用):
#   - ghproxy.homeboyc.cn  HTTP 403 Forbidden (服务限制访问)
#   - gitclone.com         HTTP 404 Not Found (不支持 release zip 下载,仅支持 git clone)
GITHUB_PROXIES: List[str] = [
    "https://gh-proxy.com/",          # 实测最快 0.96 MB/s, 100% 成功率
    "https://ghproxy.net/",           # 实测 0.26 MB/s, 100% 成功率 (稳定备选)
    "https://githubproxy.cc/",        # 实测 0.01 MB/s, 67% 成功率
    "https://hub.gitmirror.com/",    # 实测 DNS 失败 (可能临时,保留备选)
    "https://gh.llkk.cc/",            # 实测超时 (可能临时,保留备选)
    "https://gh.api.99988866.xyz/",   # 实测 SSL 失败 (可能临时,保留备选)
]

# PyPI 国内镜像 (仅用于 pip install -i 场景,当前 GIMI/d3d11 不涉及)
PYPI_MIRRORS: List[str] = [
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://mirrors.aliyun.com/pypi/simple/",
    "https://pypi.mirrors.ustc.edu.cn/simple/",
]

# User-Agent
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 下载参数
DEFAULT_TIMEOUT = 30              # 连接/读取超时 (秒)
DEFAULT_CHUNK_SIZE = 524288       # 512KB
MAX_RETRIES_PER_URL = 2           # 每个 URL 最多重试次数 (不含首次尝试)
RETRY_BACKOFF_BASE = 1.5          # 指数退避基数 (秒)


#: GitHub 限流时返回的状态码。403 在 GitHub 上既可能是限流也可能是普通拒绝，
#: 需结合 ``X-RateLimit-Remaining: 0`` 判定（见 :func:`is_rate_limited`）。
RATE_LIMIT_CODES = frozenset({403, 429})


def is_rate_limited(err: BaseException) -> bool:
    """判断一个 HTTPError 是否为 GitHub 限流（而非普通 4xx 拒绝）。

    GitHub 的限流有两种表现：
      * ``403`` + ``X-RateLimit-Remaining: 0``（次级限流，配 ``Retry-After``）；
      * ``429``（``Too Many Requests``）。
    匿名 API 配额只有 60 次/小时/IP，故未做节流时很容易踩到——而旧实现把 403
    一律当作「换通道重试」，白跑完16 路通道后才报「网络错误」，用户看到的
    文案完全指不到问题上。

    Returns:
        True 表示确认为限流。
    """
    if not isinstance(err, urllib.error.HTTPError):
        return False
    if err.code == 429:
        return True
    if err.code == 403:
        headers = getattr(err, "headers", None)
        if headers is not None:
            try:
                remaining = headers.get("X-RateLimit-Remaining")
            except Exception:
                remaining = None
            if remaining is not None and str(remaining).strip() == "0":
                return True
            body = ""
            try:
                body = (err.read() or b"").decode("utf-8", "ignore").lower()
            except Exception:
                pass
            if "rate limit" in body or "secondary rate" in body:
                return True
    return False


def rate_limit_hint(err: BaseException) -> str:
    """限流时给用户的一句话处置建议（可直接显示在 tooltip / 状态栏）。"""
    retry_after = ""
    headers = getattr(err, "headers", None)
    if headers is not None:
        try:
            retry_after = (headers.get("Retry-After") or "").strip()
        except Exception:
            retry_after = ""
    base = "GitHub API 限流（匿名配额 60 次/小时）"
    if retry_after:
        return f"{base}，建议 {retry_after} 后重试"
    return f"{base}，请稍后重试或配置网络代理"


class RateLimitedError(RuntimeError):
    """GitHub API 限流。

    单独一个异常类型，是为了让调用方能把「限流」与「网络不通」区分开：
    前者是**等一会就好**（配额按小时重置），后者要换网络 / 代理。
    :func:`fetch_json_api_smart` 遇到限流会抛本异常而非返回 None。
    """

# Start another actual request after this delay; never block on a probe.
FALLBACK_DELAY = 0.8
MAX_ROUTE_WORKERS = 3
ROUTE_CACHE_TTL = 300.0
_route_cache = {}
_route_lock = threading.Lock()


# ============================================================
# SSL 上下文辅助
# ============================================================

def _ssl_ctx() -> ssl.SSLContext:
    """默认 SSL 上下文 (验证证书)"""
    return ssl.create_default_context()


def _ssl_ctx_noverify() -> ssl.SSLContext:
    """不验证证书的 SSL 上下文 (兜底回退)"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# ============================================================
# 传输通道: 系统代理 / 直连 × SSL 验证 / 不验证
# ============================================================

def get_system_proxies() -> dict:
    """当前生效的系统代理配置。

    Windows 上来自注册表 (Internet Settings/ProxyServer), 其它平台来自环境变量。
    返回空 dict 表示系统未配置代理。
    """
    try:
        return dict(urllib.request.getproxies())
    except Exception:
        return {}


def has_system_proxy() -> bool:
    """系统是否配置了 HTTP(S) 代理。"""
    return bool(get_system_proxies())


# 通道缓存: key=(系统代理快照, 是否直连优先), value=(通道名, opener) 列表。
# 构造 SSLContext 需要读取系统证书库, 有实际开销, 故按快照缓存;
# 用户开关代理客户端后快照变化会自动重建。
_openers_cache: dict = {}


def get_openers(prefer_direct: bool = False) -> List[Tuple[str, urllib.request.OpenerDirector]]:
    """Verified TLS routes: system proxy first, explicit direct access as fallback.

    urllib follows Windows/environment proxy settings by default. ProxyHandler({})
    explicitly bypasses those settings. Contexts/openers are cached by snapshot.
    """
    key = (tuple(sorted(get_system_proxies().items())), prefer_direct)
    cached = _openers_cache.get(key)
    if cached:
        return cached

    # None = 跟随系统代理 (ProxyHandler 无参构造会自行读取 getproxies)
    # {}   = 显式绕过系统代理 (真·直连)
    channels: List[Tuple[str, Optional[dict]]] = [("系统代理", None)]
    if key[0]:
        channels.append(("直连", {}))
    if prefer_direct:
        channels.reverse()

    openers: List[Tuple[str, urllib.request.OpenerDirector]] = []
    ctx = _ssl_ctx()
    for chan_name, proxy_map in channels:
        handler = urllib.request.ProxyHandler(dict(key[0]) if proxy_map is None else proxy_map)
        opener = urllib.request.build_opener(handler, urllib.request.HTTPSHandler(context=ctx))
        openers.append((f"{chan_name}/SSL", opener))

    _openers_cache[key] = openers
    return openers


def reset_openers_cache() -> None:
    """清空通道缓存 (用户切换代理客户端后调用, 下次请求会重新探测)。"""
    _openers_cache.clear()


def reset_route_cache() -> None:
    """Forget successful routes after a VPN/network change."""
    with _route_lock:
        _route_cache.clear()
    reset_openers_cache()


def reset_youtube_cache() -> None:
    """Compatibility alias; no YouTube requests are made."""
    reset_route_cache()


def should_use_proxy(url: str = "") -> bool:
    """Compatibility: GitHub URLs are eligible for mirror fallback, without I/O."""
    return not url or is_github_url(url)


# ============================================================
# URL 构建与场景识别
# ============================================================

def is_github_url(url: str) -> bool:
    """判断是否为 GitHub 域名 URL"""
    return (urlsplit(url).hostname or "").lower() in {
        "github.com", "api.github.com", "raw.githubusercontent.com",
        "codeload.github.com", "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }


def build_proxy_urls(original_url: str,
                     proxies: Optional[List[str]] = None) -> List[str]:
    """为 GitHub URL 构建代理 URL 候选列表 (不含原 URL)

    Args:
        original_url: 原 GitHub URL
        proxies: 代理前缀列表, None 表示使用默认 GITHUB_PROXIES

    Returns:
        代理 URL 列表,按优先级排序
    """
    if not is_github_url(original_url):
        return []
    proxies = proxies if proxies is not None else GITHUB_PROXIES
    urls: List[str] = []
    for prefix in proxies:
        if not prefix.endswith("/"):
            prefix += "/"
        urls.append(prefix + original_url)
    return urls


def build_download_candidates(original_url: str) -> List[str]:
    """为下载构建候选 URL 列表: 原 URL 在前,代理作为回退

    智能 failover: 按优先级尝试,失败自动切换下一个。
    """
    return [original_url] + build_proxy_urls(original_url)


# ============================================================
# 智能测速 (可选,选择当前可用的最快代理)
# ============================================================

def _probe_proxy(proxy_prefix: str, test_url: str,
                 timeout: float = 4.0) -> Optional[float]:
    """快速测速单个代理 (HEAD 请求)

    Returns:
        响应时间 (秒),失败返回 None
    """
    if not proxy_prefix.endswith("/"):
        proxy_prefix += "/"
    test_full = proxy_prefix + test_url
    req = urllib.request.Request(
        test_full, method="HEAD", headers={"User-Agent": DEFAULT_UA}
    )
    for ctx in [_ssl_ctx(), _ssl_ctx_noverify()]:
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                if resp.status < 400:
                    return time.time() - t0
        except Exception:
            continue
    return None


def select_fastest_proxy(test_url: str,
                        proxies: Optional[List[str]] = None,
                        timeout: float = 4.0) -> Optional[str]:
    """测速选择最快的可用代理

    Args:
        test_url: 用于测速的 GitHub URL (建议选小文件)
        proxies: 代理列表, None 表示使用默认

    Returns:
        最快的代理前缀 (含尾随 /),全部不可用返回 None
    """
    proxies = proxies if proxies is not None else GITHUB_PROXIES
    results = []
    for prefix in proxies:
        t = _probe_proxy(prefix, test_url, timeout=timeout)
        if t is not None:
            results.append((t, prefix))
            logger.info(f"代理测速 {prefix}: {t*1000:.0f}ms")
        else:
            logger.info(f"代理测速 {prefix}: 不可用")
    if not results:
        return None
    results.sort()
    return results[0][1]


# ============================================================
# Shared actual-request routing
# ============================================================


class _Cancelled(Exception):
    pass


def _cache_key(url, use_proxies):
    host = (urlsplit(url).hostname or "").lower()
    kind = ("api" if host == "api.github.com" else
            "raw" if host == "raw.githubusercontent.com" else
            "release" if "/releases/download/" in url or host in {
                "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
            else "content")
    return host, kind, bool(use_proxies), tuple(sorted(get_system_proxies().items()))


def _routes(url, use_proxies):
    channels = get_openers()
    prefixes = GITHUB_PROXIES if use_proxies and is_github_url(url) else []
    routes = [("", channels[0][0], channels[0][1])]
    routes += [(prefix.rstrip("/") + "/", channels[0][0], channels[0][1])
               for prefix in prefixes]
    # Try explicit direct access alongside the first mirror when a system proxy exists.
    if len(channels) > 1:
        routes.insert(2, ("", channels[1][0], channels[1][1]))
        routes += [(prefix.rstrip("/") + "/", channels[1][0], channels[1][1])
                   for prefix in prefixes]
    key = _cache_key(url, use_proxies)
    with _route_lock:
        cached = _route_cache.get(key)
        if cached and time.monotonic() - cached[1] < ROUTE_CACHE_TTL:
            routes.sort(key=lambda route: route[:2] != cached[0])
        else:
            _route_cache.pop(key, None)
    return key, routes


def _remember(key, route):
    with _route_lock:
        _route_cache[key] = (route[:2], time.monotonic())


def _forget(key, route):
    with _route_lock:
        cached = _route_cache.get(key)
        if cached and cached[0] == route[:2]:
            _route_cache.pop(key, None)


def _race(url, routes, operation, key, should_cancel=None, status_cb=None,
          cleanup=lambda value: None):
    """Bounded daemon workers; losers never write files or publish callbacks.

    urllib cannot interrupt DNS/connect in another thread. Late responses are
    closed by their worker, without delaying the winner or cancellation.
    """
    results = queue.Queue()
    gate = threading.Lock()
    stopped = False
    active = 0
    index = 0
    next_start = 0.0
    last_error = RuntimeError("没有可用下载通道")

    def worker(route):
        try:
            value, error = operation(route), None
        except Exception as exc:
            value, error = None, exc
        with gate:
            if stopped:
                if error is None:
                    cleanup(value)
            else:
                results.put((route, value, error))

    try:
        while index < len(routes) or active:
            if should_cancel and should_cancel():
                raise _Cancelled()
            now = time.monotonic()
            if index < len(routes) and active < MAX_ROUTE_WORKERS and (
                    active == 0 or now >= next_start):
                route = routes[index]
                if status_cb:
                    try:
                        label = (urlsplit(route[0]).netloc if route[0] else
                                 urlsplit(url).netloc) + " · " + route[1]
                        status_cb(label, index, len(routes))
                    except Exception:
                        pass
                threading.Thread(target=worker, args=(route,), daemon=True).start()
                index += 1
                active += 1
                next_start = time.monotonic() + FALLBACK_DELAY
            try:
                route, value, error = results.get(timeout=0.05)
            except queue.Empty:
                continue
            active -= 1
            if error is None:
                return value, route
            _forget(key, route)
            if isinstance(error, RateLimitedError):
                raise error
            last_error = error
            logger.debug("请求通道失败 (%s · %s): %s", route[0] or "原始地址", route[1], error)
            next_start = 0.0
        raise last_error
    finally:
        with gate:
            stopped = True
            while not results.empty():
                _, value, error = results.get_nowait()
                if error is None:
                    cleanup(value)


def _open(route, url, headers, timeout):
    req = urllib.request.Request(route[0] + url, headers=headers)
    try:
        return route[2].open(req, timeout=timeout)
    except urllib.error.HTTPError as error:
        try:
            if is_rate_limited(error):
                raise RateLimitedError(rate_limit_hint(error)) from error
            raise
        finally:
            error.close()


def _fetch(url, timeout, use_proxies, status_cb, headers, should_cancel, as_json):
    key, routes = _routes(url, use_proxies)

    def operation(route):
        with _open(route, url, headers, timeout) as response:
            if response.status != 200:
                raise ValueError(f"HTTP {response.status}")
            content = response.read().decode("utf-8")
            return json.loads(content) if as_json else content

    try:
        value, route = _race(url, routes, operation, key, should_cancel, status_cb)
        _remember(key, route)
        return value
    except RateLimitedError:
        raise
    except _Cancelled:
        return None
    except Exception as error:
        logger.warning("请求失败 (%s): %s", url, error)
        return None


def fetch_url_smart(url: str, timeout: int = 15, use_proxies: bool = True,
                    status_cb=None, headers: Optional[dict] = None,
                    should_cancel=None) -> Optional[str]:
    request_headers = {"User-Agent": DEFAULT_UA,
                       "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    request_headers.update(headers or {})
    return _fetch(url, timeout, use_proxies, status_cb, request_headers, should_cancel, False)


def fetch_json_api_smart(url: str, timeout: int = 15, use_proxies: bool = True,
                        status_cb=None, should_cancel=None) -> Optional[dict]:
    return _fetch(url, timeout, use_proxies, status_cb,
                  {"User-Agent": "OMG-GIMI-Manager/1.0",
                   "Accept": "application/vnd.github+json"}, should_cancel, True)


def download_file_smart(url: str, dest_path: str, signals=None,
                        progress_range: Tuple[int, int] = (0, 100),
                        timeout: int = DEFAULT_TIMEOUT,
                        chunk_size: int = DEFAULT_CHUNK_SIZE,
                        use_proxies: bool = True,
                        should_cancel=None) -> Tuple[bool, str]:
    """Race response headers/first bytes, then stream on the caller only.

    Range is sent on the actual GET, without a separate resume probe. A server
    ignoring Range causes a safe overwrite; malformed ranges never get appended.
    """
    key, all_routes = _routes(url, use_proxies)
    last_error = "下载失败"
    for round_index in range(MAX_RETRIES_PER_URL + 1):
        routes = list(all_routes)
        while routes:
            if should_cancel and should_cancel():
                return False, "已取消"
            response = None
            route = None
            try:
                offset = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
                headers = {"User-Agent": DEFAULT_UA, "Accept-Encoding": "identity"}
                if offset:
                    headers["Range"] = f"bytes={offset}-"

                def operation(candidate, headers=headers, offset=offset):
                    try:
                        resp = _open(candidate, url, headers, timeout)
                    except urllib.error.HTTPError as error:
                        # Accept 416 only when the server confirms the exact local length.
                        if (error.code == 416 and offset > 0 and
                                error.headers.get("Content-Range") == f"bytes */{offset}"):
                            return None, b"", offset
                        raise
                    try:
                        if resp.status not in (200, 206):
                            raise ValueError(f"HTTP {resp.status}")
                        total = int(resp.headers.get("Content-Length", 0) or 0)
                        if resp.status == 206:
                            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)",
                                                 resp.headers.get("Content-Range", ""))
                            if not match or int(match[1]) != offset:
                                raise ValueError("服务器返回了不匹配的续传范围")
                            start, end, size = map(int, match.groups())
                            if not start <= end < size or end != size - 1:
                                raise ValueError("服务器返回了无效的续传范围")
                            if total and total != end - start + 1:
                                raise ValueError("续传长度与响应范围不一致")
                            total = size
                        content_type = resp.headers.get("Content-Type", "").lower()
                        if is_github_url(url) and "text/html" in content_type:
                            raise ValueError("下载通道返回了 HTML 页面")
                        # read1 avoids waiting for a whole 512KB buffer before choosing.
                        first = getattr(resp, "read1", resp.read)(min(chunk_size, 8192))
                        if not first and total:
                            raise ValueError("下载响应为空")
                        return resp, first, total
                    except Exception:
                        resp.close()
                        raise

                def status(label, index, total):
                    if signals:
                        signals.status.emit(f"连接下载源：{label}", "info")

                (response, first, total), route = _race(
                    url, routes, operation, key, should_cancel, status,
                    cleanup=lambda value: value[0].close() if value[0] is not None else None)
                if response is None:
                    _remember(key, route)
                    return True, ""
                downloaded = offset if response.status == 206 else 0
                with response, open(dest_path, "ab" if response.status == 206 else "wb") as target:
                    chunk = first
                    while chunk:
                        if should_cancel and should_cancel():
                            raise _Cancelled()
                        target.write(chunk)
                        downloaded += len(chunk)
                        if signals and total:
                            try:
                                lo, hi = progress_range
                                signals.progress.emit(float(lo + min(1, downloaded / total) * (hi - lo)))
                                if hasattr(signals, 'download_bytes'):
                                    signals.download_bytes.emit(downloaded, total)
                                else:
                                    signals.status.emit(f"下载中... {downloaded / 1048576:.1f} / {total / 1048576:.1f} MB", "info")
                            except Exception:
                                pass
                        if total and downloaded == total:
                            break  # Content-Length reached; no extra blocking EOF read.
                        chunk = response.read(chunk_size)
                if total and downloaded != total:
                    raise ValueError("下载未完成 (中断或长度不匹配)")
                _remember(key, route)
                return True, ""
            except _Cancelled:
                return False, "已取消"
            except RateLimitedError as error:
                return False, str(error)
            except OSError as error:
                if error.errno in (errno.ENOSPC, errno.EACCES, errno.EROFS):
                    return False, ("磁盘空间不足，请清理后重试" if error.errno == errno.ENOSPC
                                   else f"无写入权限: {dest_path}")
                last_error = f"网络错误: {error}"
            except Exception as error:
                last_error = f"下载失败: {error}"
            finally:
                if response is not None:
                    response.close()
            if route is None:
                break
            _forget(key, route)
            routes = [candidate for candidate in routes if candidate[:2] != route[:2]]
        if round_index < MAX_RETRIES_PER_URL:
            # Cancel remains responsive during retry backoff.
            until = time.monotonic() + RETRY_BACKOFF_BASE ** (round_index + 1)
            while time.monotonic() < until:
                if should_cancel and should_cancel():
                    return False, "已取消"
                time.sleep(0.05)
    return False, last_error


# ============================================================
# PyPI 镜像接口 (预留,当前 GIMI/d3d11 场景不涉及)
# ============================================================

def get_pypi_mirror(index: int = 0) -> str:
    """获取 PyPI 镜像 URL (用于 pip install -i 参数)

    注意: 当前 GIMI-PACKAGE 和 XXMI-Libs-Package 下载场景均为
          GitHub release zip,不涉及 pip 安装,此函数为预留接口。
    """
    if 0 <= index < len(PYPI_MIRRORS):
        return PYPI_MIRRORS[index]
    return PYPI_MIRRORS[0]


# ============================================================
# 模块自检
# ============================================================

if __name__ == "__main__":
    import sys as _sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    print("=== GitHub 代理列表 ===")
    for p in GITHUB_PROXIES:
        print(f"  {p}")
    print("\n=== PyPI 镜像列表 (当前场景不适用) ===")
    for m in PYPI_MIRRORS:
        print(f"  {m}")
    print("\n=== URL 构建测试 ===")
    test = "https://github.com/SilentNightSound/GIMI-Package/releases/latest"
    print(f"原始: {test}")
    for c in build_download_candidates(test):
        print(f"  候选: {c}")

    # 可选: 代理测速 (传入 --probe 参数触发,默认不运行以免每次耗时)
    if "--probe" in _sys.argv:
        print("\n=== 代理测速 (GitHub releases 页面) ===")
        fastest = select_fastest_proxy(test, timeout=4.0)
        if fastest:
            print(f"\n最快代理: {fastest}")
        else:
            print("\n所有代理当前均不可用")
    else:
        print("\n(传入 --probe 参数可触发代理测速)")
