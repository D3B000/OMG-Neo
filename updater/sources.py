"""Package acquisition boundary. GitHub deliberately performs no network calls yet."""
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Release:
    version: str
    configuration: str
    asset_name: str
    sha256: str = ''


class UpdateSource(Protocol):
    def check_latest(self, configuration: str) -> Release: ...
    def fetch_release(self, release: Release, destination: Path) -> Path: ...


class GitHubSource:
    """Future public-repository adapter; no guessed repository or unchecked downloads."""
    def __init__(self, repository: str = ''):
        self.repository = repository

    def check_latest(self, configuration: str) -> Release:
        raise NotImplementedError('GitHub 更新尚未启用，请手动添加本地 ZIP。')

    def fetch_release(self, release: Release, destination: Path) -> Path:
        raise NotImplementedError('GitHub 下载尚未启用。下载完成后仍须走同一校验／事务流程。')


def local_package(value: str) -> Path:
    # Windows drag-and-drop paths are typically quoted; do not expand shell expressions.
    return Path(value.strip().strip('"').strip("'"))
