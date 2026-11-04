"""Check for and download a newer release of the portable Windows build.

The application ships as a PyInstaller ``onedir`` bundle, so an update is a zip
asset attached to a GitHub release.  GitHub publishes a ``digest`` for every
asset, which means the download can be verified without maintaining a separate
checksum file.

Everything here is plain Python: the service layer stays free of Qt so it can be
unit tested without an event loop or a display.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import urllib.error
import urllib.request
import zipfile

from reimbursement_manager.utils.filesystem import remove_directory


logger = logging.getLogger(__name__)

GITHUB_OWNER = "Zhaoooq"
GITHUB_REPOSITORY = "Reimbursement-Manager"
LATEST_RELEASE_URL = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPOSITORY}/releases/latest"
)
PLATFORM_SUFFIX = "win64"
EXECUTABLE_NAME = "ReimbursementManager.exe"
USER_AGENT = "ReimbursementManager-Updater"
DOWNLOAD_CHUNK_SIZE = 256 * 1024
DEFAULT_TIMEOUT_SECONDS = 20.0

_VERSION_PATTERN = re.compile(
    r"^[vV]?(\d+)(?:\.(\d+))?(?:\.(\d+))?([-+][0-9A-Za-z.\-]+)?$"
)


class UpdateError(RuntimeError):
    """Raised when update metadata or a downloaded archive cannot be used."""


class UpdateUnavailableError(UpdateError):
    """Raised when the release feed or the download cannot be reached."""


class UpdateArchiveError(UpdateError):
    """Raised when a downloaded archive is incomplete or unsafe to unpack."""


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    """One downloadable release that is newer than the running build."""

    version: str
    tag: str
    notes: str
    asset_name: str
    download_url: str
    size: int
    sha256: str | None

    @property
    def size_megabytes(self) -> float:
        return self.size / (1024 * 1024)


def parse_version(value: str) -> tuple[int, int, int, int]:
    """Return a sortable key for ``value``.

    The fourth element ranks a final release above its own pre-releases, so
    ``1.0.0`` is newer than ``1.0.0-beta`` while both stay above ``0.9.9``.
    """
    match = _VERSION_PATTERN.match(value.strip())
    if match is None:
        raise UpdateError(f"无法识别的版本号：{value}")
    major, minor, patch = (int(part) if part else 0 for part in match.group(1, 2, 3))
    is_final = 0 if match.group(4) else 1
    return major, minor, patch, is_final


def is_newer(candidate: str, current: str) -> bool:
    """Return whether ``candidate`` is a strict upgrade over ``current``."""
    return parse_version(candidate) > parse_version(current)


def normalize_tag(tag: str) -> str:
    """Strip the conventional ``v`` prefix so the value matches asset names."""
    return tag.strip().lstrip("vV")


def select_asset(
    assets: Sequence[dict[str, object]], version: str
) -> dict[str, object] | None:
    """Pick the Windows portable archive that belongs to ``version``."""
    preferred_name = f"ReimbursementManager-{version}-{PLATFORM_SUFFIX}.zip"
    for asset in assets:
        if asset.get("name") == preferred_name:
            return asset
    for asset in assets:
        name = str(asset.get("name") or "").lower()
        if name.endswith(".zip") and PLATFORM_SUFFIX in name:
            return asset
    return None


def _asset_sha256(asset: dict[str, object]) -> str | None:
    """Read the ``sha256:...`` digest GitHub attaches to an asset."""
    digest = asset.get("digest")
    if not isinstance(digest, str):
        return None
    algorithm, _separator, value = digest.partition(":")
    if algorithm.lower() != "sha256" or len(value) != 64:
        return None
    return value.lower()


def locate_program_directory(root: Path) -> Path:
    """Return the directory inside an unpacked archive that holds the program."""
    if (root / EXECUTABLE_NAME).is_file():
        return root
    for candidate in sorted(root.rglob(EXECUTABLE_NAME)):
        return candidate.parent
    raise UpdateArchiveError("更新包中没有找到主程序。")


class UpdateService:
    """Query the release feed and fetch the matching archive."""

    def __init__(
        self,
        *,
        opener: Callable[..., object] | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        release_url: str = LATEST_RELEASE_URL,
    ) -> None:
        # ``opener`` is injected so tests never touch the network.
        self._opener = opener or urllib.request.urlopen
        self._timeout = timeout
        self._release_url = release_url

    def check_for_update(self, current_version: str) -> UpdateInfo | None:
        """Return the available upgrade, or ``None`` when already current."""
        release = self._fetch_latest_release()
        if not release:
            return None

        tag = str(release.get("tag_name") or "").strip()
        if not tag:
            raise UpdateError("更新信息缺少版本号。")
        if not is_newer(tag, current_version):
            return None

        version = normalize_tag(tag)
        assets = release.get("assets")
        asset_list = [item for item in assets if isinstance(item, dict)] if isinstance(assets, list) else []
        asset = select_asset(asset_list, version)
        if asset is None:
            raise UpdateError(f"版本 {version} 没有提供 Windows 程序包。")

        download_url = str(asset.get("browser_download_url") or "")
        if not download_url:
            raise UpdateError("更新包的下载地址缺失。")

        return UpdateInfo(
            version=version,
            tag=tag,
            notes=str(release.get("body") or "").strip(),
            asset_name=str(asset.get("name") or ""),
            download_url=download_url,
            size=int(asset.get("size") or 0),
            sha256=_asset_sha256(asset),
        )

    def download(
        self,
        info: UpdateInfo,
        destination: Path,
        *,
        progress: Callable[[int, int], None] | None = None,
    ) -> Path:
        """Download ``info`` to ``destination`` and verify its checksum."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(f"{destination.name}.part")
        digest = hashlib.sha256()
        received = 0

        request = urllib.request.Request(
            info.download_url, headers={"User-Agent": USER_AGENT}
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                with partial.open("wb") as handle:
                    while True:
                        chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                        if not chunk:
                            break
                        handle.write(chunk)
                        digest.update(chunk)
                        received += len(chunk)
                        if progress is not None:
                            progress(received, info.size or received)
        except (urllib.error.URLError, OSError) as error:
            partial.unlink(missing_ok=True)
            raise UpdateUnavailableError(f"下载更新包失败：{error}") from error

        if info.size and received != info.size:
            partial.unlink(missing_ok=True)
            raise UpdateArchiveError("下载的更新包不完整，请重试。")

        actual = digest.hexdigest()
        if info.sha256 is None:
            logger.warning("Release asset %s has no digest to verify", info.asset_name)
        elif actual != info.sha256:
            partial.unlink(missing_ok=True)
            raise UpdateArchiveError("更新包校验失败，已放弃安装。")

        os.replace(partial, destination)
        return destination

    def extract(self, archive: Path, destination: Path) -> Path:
        """Unpack ``archive`` into ``destination`` and return the program root."""
        if destination.exists() and not remove_directory(destination):
            raise UpdateArchiveError(
                f"无法清理上次的临时目录：{destination}"
            )
        destination.mkdir(parents=True, exist_ok=True)

        try:
            with zipfile.ZipFile(archive) as bundle:
                self._reject_unsafe_members(bundle, destination)
                bundle.extractall(destination)
        except zipfile.BadZipFile as error:
            raise UpdateArchiveError("更新包已损坏，无法解压。") from error

        return locate_program_directory(destination)

    @staticmethod
    def _reject_unsafe_members(bundle: zipfile.ZipFile, destination: Path) -> None:
        """Refuse archives that try to escape the staging directory."""
        root = destination.resolve()
        for member in bundle.infolist():
            target = (root / member.filename).resolve()
            if not target.is_relative_to(root):
                raise UpdateArchiveError("更新包中包含非法路径，已拒绝解压。")

    def _fetch_latest_release(self) -> dict[str, object]:
        request = urllib.request.Request(
            self._release_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/vnd.github+json",
            },
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            if error.code == 404:
                # No release published yet is not an error condition.
                return {}
            if error.code in (403, 429):
                raise UpdateUnavailableError(
                    "更新服务请求过于频繁，请稍后再试。"
                ) from error
            raise UpdateUnavailableError(
                f"更新服务器返回错误（HTTP {error.code}）。"
            ) from error
        except (urllib.error.URLError, OSError) as error:
            raise UpdateUnavailableError(f"无法连接更新服务器：{error}") from error

        try:
            release = json.loads(payload)
        except ValueError as error:
            raise UpdateUnavailableError("更新服务器返回了无法解析的数据。") from error
        if not isinstance(release, dict):
            raise UpdateUnavailableError("更新服务器返回了无法解析的数据。")
        return release
