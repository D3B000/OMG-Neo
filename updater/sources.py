"""Release acquisition using OMG-Neo's shared GitHub transport."""
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, unquote, urlsplit
import hashlib
import html
import re
import sys

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'OMGLite/src'))
from omg.core import download
from engine import UpdateError, inspect_package, preview_payload, safe_path

REPOSITORY = 'D3B000/OMG-Neo'


def same_version(left: str, right: str) -> bool:
    # Tags may omit Flutter's build number; compare it when both include it.
    pattern = r'[vV]?(\d+(?:\.\d+)*)(?:\+(\d+))?'
    a, b = re.fullmatch(pattern, left.strip()), re.fullmatch(pattern, right.strip())
    if not a or not b:
        return bool(left.strip()) and left.strip() == right.strip()
    return (tuple(map(int, a[1].split('.'))) == tuple(map(int, b[1].split('.')))
            and (not a[2] or not b[2] or int(a[2]) == int(b[2])))


@dataclass(frozen=True)
class Release:
    version: str
    configuration: str
    asset_name: str
    sha256: str = ''
    url: str = ''
    size: int = 0


class UpdateSource(Protocol):
    def check_latest(self, configuration: str) -> Release: ...
    def fetch_release(self, release: Release, destination: Path) -> Path: ...


class GitHubSource:
    def __init__(self, repository: str = REPOSITORY, status=print, progress=None):
        if not re.fullmatch(r'[\w.-]+/[\w.-]+', repository):
            raise ValueError('GitHub 仓库名称无效。')
        self.repository, self.status = repository, status
        self.progress = progress or (lambda stage, detail, done=0, total=0: None)
        self.package = None

    def _status(self, label, *_):
        self.status(f'连接 GitHub：{label}')

    def _asset_url(self, url):
        parsed = urlsplit(url)
        return (parsed.scheme == 'https' and parsed.netloc == 'github.com'
                and parsed.path.startswith(f'/{self.repository}/releases/download/')
                and not parsed.query and not parsed.fragment)

    def check_latest(self, configuration: str = 'Release') -> Release:
        if configuration not in {'Debug', 'Release'}:
            raise UpdateError('未知的前端模式。')
        base = f'https://github.com/{self.repository}'
        try:
            data = download.fetch_json_api_smart(
                f'https://api.github.com/repos/{self.repository}/releases/latest', status_cb=self._status)
        except download.RateLimitedError:
            data = None
        if isinstance(data, dict) and data.get('tag_name'):
            if data.get('draft') or data.get('prerelease'):
                raise UpdateError('最新正式版本查询返回了草稿或预发布。')
            version, assets = data['tag_name'], data.get('assets', [])
        else:
            page = download.fetch_url_smart(base + '/releases/latest', status_cb=self._status)
            tags = re.findall(r'/releases/tag/([^\x22\x27&\s<>]+)', page or '')
            if not tags:
                raise UpdateError('无法查询 OMG-Neo 最新版本，请稍后重试。')
            version = unquote(tags[0])
            page = download.fetch_url_smart(base + '/releases/expanded_assets/' + quote(version, safe=''),
                                           status_cb=self._status)
            assets = []
            for link in re.findall(r'href=[\x22\x27]([^\x22\x27]+)[\x22\x27]', page or ''):
                url = html.unescape(link)
                if url.startswith('/'):
                    url = 'https://github.com' + url
                assets.append({'name': unquote(urlsplit(url).path.rsplit('/', 1)[-1]),
                               'browser_download_url': url})
        candidates = []
        for asset in assets:
            name, url = asset.get('name', ''), asset.get('browser_download_url', '')
            lower = name.lower()
            if not (lower.startswith('omg-neo') and lower.endswith('.zip') and self._asset_url(url)):
                continue
            if 'updater' in lower or ('debug' in lower) != (configuration == 'Debug'):
                continue
            if Path(name).name != name or '/' in name or '\\' in name:
                continue
            checksum = asset.get('digest') or ''
            checksum = checksum[7:] if checksum.startswith('sha256:') else ''
            if checksum and not re.fullmatch('[a-fA-F0-9]{64}', checksum):
                raise UpdateError('Release SHA-256 格式无效。')
            candidates.append(Release(version, configuration, name, checksum.lower(), url, asset.get('size', 0)))
        if len(candidates) != 1:
            raise UpdateError(f'最新 Release 中需要唯一的 OMG-Neo {configuration} ZIP，找到 {len(candidates)} 个。')
        return candidates[0]

    def fetch_release(self, release: Release, destination: Path) -> Path:
        if (not self._asset_url(release.url) or Path(release.asset_name).name != release.asset_name
                or '/' in release.asset_name or '\\' in release.asset_name):
            raise UpdateError('Release 下载地址或包名无效。')
        destination = safe_path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(f'{release.url}|{release.sha256}|{release.size}'.encode()).hexdigest()[:16]
        final = safe_path(destination / f'{key}-{release.asset_name}')
        partial = safe_path(final.with_suffix('.zip.part'))
        class Signal:
            def __init__(self, callback):
                self.emit = callback
        class Signals:
            status = Signal(lambda message, *_: self.status(message))
            progress = Signal(lambda value: None)
            download_bytes = Signal(lambda done, total: self.progress('下载', release.asset_name, done, total))
        self.progress('下载', '连接下载源…')
        success, error = download.download_file_smart(release.url, str(partial), signals=Signals())
        if not success:
            raise UpdateError(error)
        try:
            if release.size and partial.stat().st_size != release.size:
                raise UpdateError('Release 下载大小不匹配。')
            partial.replace(final)
            self.progress('校验下载包', '网络传输完成，正在读取 ZIP…')
            package = inspect_package(final, release.sha256, lambda done, total:
                                      self.progress('校验下载包', release.asset_name, done, total))
            metadata = preview_payload(package)
            if metadata['configuration'] != release.configuration:
                raise UpdateError('下载包的前端模式与 Release 不匹配。')
            if not same_version(metadata['version'], release.version):
                raise UpdateError('下载包版本清单与 Release 标签不匹配。')
            self.package = package
        except Exception:
            partial.unlink(missing_ok=True)
            final.unlink(missing_ok=True)
            raise
        return final


def local_package(value: str) -> Path:
    return Path(value.strip().strip('"').strip("'"))
