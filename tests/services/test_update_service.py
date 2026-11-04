"""Unit tests for the release-checking and download service."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import urllib.error
import zipfile

import pytest

from reimbursement_manager.services.update_service import (
    UpdateArchiveError,
    UpdateError,
    UpdateService,
    UpdateUnavailableError,
    is_newer,
    parse_version,
    select_asset,
)


class _FakeResponse:
    """Minimal stand-in for the object returned by ``urlopen``."""

    def __init__(self, payload: bytes) -> None:
        self._buffer = io.BytesIO(payload)

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def read(self, size: int | None = -1) -> bytes:
        return self._buffer.read(-1 if size is None else size)


class _FakeOpener:
    """Serve canned responses and record the requested URLs."""

    def __init__(self, *responses: bytes | Exception) -> None:
        self._responses = list(responses)
        self.requested_urls: list[str] = []

    def __call__(self, request: object, timeout: float | None = None) -> _FakeResponse:
        self.requested_urls.append(getattr(request, "full_url", str(request)))
        if not self._responses:
            raise AssertionError("unexpected extra request")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return _FakeResponse(response)


def _release_payload(
    tag: str = "v0.2.2",
    *,
    body: str = "修复若干问题",
    asset_name: str = "ReimbursementManager-0.2.2-win64.zip",
    digest: str | None = "sha256:" + "a" * 64,
    extra_assets: list[dict[str, object]] | None = None,
) -> bytes:
    asset: dict[str, object] = {
        "name": asset_name,
        "browser_download_url": (
            "https://github.com/Zhaoooq/Reimbursement-Manager/releases/"
            f"download/{tag}/{asset_name}"
        ),
        "size": 0,
    }
    if digest is not None:
        asset["digest"] = digest
    assets = [asset, *(extra_assets or [])]
    return json.dumps(
        {"tag_name": tag, "body": body, "assets": assets}, ensure_ascii=False
    ).encode("utf-8")


def _zip_bytes(*members: tuple[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, data in members:
            bundle.writestr(name, data)
    return buffer.getvalue()


def test_parse_version_orders_final_above_prerelease() -> None:
    assert parse_version("v0.2.2") > parse_version("0.2.1")
    assert parse_version("1.0.0") > parse_version("1.0.0-beta")
    assert parse_version("0.10.0") > parse_version("0.9.9")


def test_parse_version_rejects_unrecognisable_input() -> None:
    with pytest.raises(UpdateError):
        parse_version("latest")


def test_is_newer_compares_against_the_running_build() -> None:
    assert is_newer("v0.2.2", "0.2.1") is True
    assert is_newer("v0.2.1", "0.2.1") is False
    assert is_newer("v0.2.0", "0.2.1") is False


def test_select_asset_prefers_the_archive_for_the_exact_version() -> None:
    assets = [
        {"name": "ReimbursementManager-0.2.1-win64.zip"},
        {"name": "ReimbursementManager-0.2.2-win64.zip"},
        {"name": "source.tar.gz"},
    ]
    selected = select_asset(assets, "0.2.2")
    assert selected is not None
    assert selected["name"] == "ReimbursementManager-0.2.2-win64.zip"


def test_select_asset_falls_back_to_any_windows_zip() -> None:
    assets = [{"name": "ReimbursementManager-win64.zip"}]
    selected = select_asset(assets, "0.2.2")
    assert selected is not None


def test_select_asset_ignores_non_windows_archives() -> None:
    assets = [{"name": "ReimbursementManager-0.2.2-darwin.zip"}]
    assert select_asset(assets, "0.2.2") is None


def test_check_for_update_returns_the_newer_release() -> None:
    opener = _FakeOpener(_release_payload())
    service = UpdateService(opener=opener)

    info = service.check_for_update("0.2.1")

    assert info is not None
    assert info.version == "0.2.2"
    assert info.tag == "v0.2.2"
    assert info.notes == "修复若干问题"
    assert info.sha256 == "a" * 64
    assert opener.requested_urls[0].endswith("/releases/latest")


def test_check_for_update_returns_none_when_already_current() -> None:
    service = UpdateService(
        opener=_FakeOpener(
            _release_payload(
                tag="v0.2.1", asset_name="ReimbursementManager-0.2.1-win64.zip"
            )
        )
    )
    assert service.check_for_update("0.2.1") is None


def test_check_for_update_tolerates_a_release_without_a_digest() -> None:
    service = UpdateService(opener=_FakeOpener(_release_payload(digest=None)))
    info = service.check_for_update("0.2.1")
    assert info is not None
    assert info.sha256 is None


def test_check_for_update_rejects_a_release_without_a_windows_archive() -> None:
    payload = _release_payload(asset_name="ReimbursementManager-0.2.2-darwin.zip")
    service = UpdateService(opener=_FakeOpener(payload))
    with pytest.raises(UpdateError):
        service.check_for_update("0.2.1")


def test_check_for_update_treats_a_missing_release_as_up_to_date() -> None:
    not_found = urllib.error.HTTPError(
        "https://example.invalid", 404, "Not Found", None, None
    )
    service = UpdateService(opener=_FakeOpener(not_found))
    assert service.check_for_update("0.2.1") is None


def test_check_for_update_reports_rate_limiting_clearly() -> None:
    limited = urllib.error.HTTPError(
        "https://example.invalid", 403, "Forbidden", None, None
    )
    service = UpdateService(opener=_FakeOpener(limited))
    with pytest.raises(UpdateUnavailableError) as error:
        service.check_for_update("0.2.1")
    assert "频繁" in str(error.value)


def test_check_for_update_reports_an_unreachable_server() -> None:
    service = UpdateService(opener=_FakeOpener(urllib.error.URLError("no route")))
    with pytest.raises(UpdateUnavailableError):
        service.check_for_update("0.2.1")


def test_check_for_update_explains_a_certificate_failure() -> None:
    import ssl

    certificate_error = ssl.SSLCertVerificationError("certificate verify failed")
    service = UpdateService(
        opener=_FakeOpener(urllib.error.URLError(certificate_error))
    )
    with pytest.raises(UpdateUnavailableError) as error:
        service.check_for_update("0.2.1")
    assert "安全连接" in str(error.value)
    assert "证书校验失败" in str(error.value)


def _info_with_checksum(payload: bytes, digest: str | None = None):
    from reimbursement_manager.services.update_service import UpdateInfo

    return UpdateInfo(
        version="0.2.2",
        tag="v0.2.2",
        notes="",
        asset_name="ReimbursementManager-0.2.2-win64.zip",
        download_url="https://example.invalid/archive.zip",
        size=len(payload),
        sha256=digest if digest is not None else hashlib.sha256(payload).hexdigest(),
    )


def test_download_writes_the_archive_and_verifies_the_checksum(tmp_path: Path) -> None:
    payload = b"x" * 5000
    service = UpdateService(opener=_FakeOpener(payload))
    destination = tmp_path / "updates" / "archive.zip"
    seen: list[tuple[int, int]] = []

    result = service.download(
        _info_with_checksum(payload),
        destination,
        progress=lambda received, total: seen.append((received, total)),
    )

    assert result == destination
    assert destination.read_bytes() == payload
    assert not destination.with_name("archive.zip.part").exists()
    assert seen[-1] == (len(payload), len(payload))


def test_download_rejects_a_checksum_mismatch(tmp_path: Path) -> None:
    payload = b"payload"
    service = UpdateService(opener=_FakeOpener(payload))
    destination = tmp_path / "archive.zip"

    with pytest.raises(UpdateArchiveError):
        service.download(_info_with_checksum(payload, digest="b" * 64), destination)

    assert not destination.exists()
    assert not destination.with_name("archive.zip.part").exists()


def test_download_rejects_a_truncated_payload(tmp_path: Path) -> None:
    payload = b"0123456789"
    service = UpdateService(opener=_FakeOpener(payload[:4]))
    destination = tmp_path / "archive.zip"

    with pytest.raises(UpdateArchiveError):
        service.download(_info_with_checksum(payload), destination)

    assert not destination.exists()


def test_download_reports_a_broken_connection(tmp_path: Path) -> None:
    service = UpdateService(opener=_FakeOpener(urllib.error.URLError("reset")))
    destination = tmp_path / "archive.zip"

    with pytest.raises(UpdateUnavailableError):
        service.download(_info_with_checksum(b"data"), destination)


def test_extract_finds_the_program_inside_a_wrapper_directory(tmp_path: Path) -> None:
    archive = tmp_path / "release.zip"
    archive.write_bytes(
        _zip_bytes(
            ("ReimbursementManager-0.2.2-win64/ReimbursementManager.exe", b"MZ"),
            ("ReimbursementManager-0.2.2-win64/_internal/app.pyc", b"pyc"),
        )
    )
    service = UpdateService(opener=_FakeOpener())

    program_directory = service.extract(archive, tmp_path / "staging")

    assert program_directory.name == "ReimbursementManager-0.2.2-win64"
    assert (program_directory / "ReimbursementManager.exe").is_file()


def test_extract_rejects_archives_that_escape_the_staging_directory(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "malicious.zip"
    archive.write_bytes(_zip_bytes(("../escaped.txt", b"nope")))
    service = UpdateService(opener=_FakeOpener())

    with pytest.raises(UpdateArchiveError):
        service.extract(archive, tmp_path / "staging")

    assert not (tmp_path / "escaped.txt").exists()


def test_extract_reports_a_corrupt_archive(tmp_path: Path) -> None:
    archive = tmp_path / "broken.zip"
    archive.write_bytes(b"not a zip file")
    service = UpdateService(opener=_FakeOpener())

    with pytest.raises(UpdateArchiveError):
        service.extract(archive, tmp_path / "staging")


def test_extract_replaces_a_stale_staging_directory(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "leftover.txt").write_text("old", encoding="utf-8")

    archive = tmp_path / "release.zip"
    archive.write_bytes(_zip_bytes(("ReimbursementManager.exe", b"MZ")))
    service = UpdateService(opener=_FakeOpener())

    program_directory = service.extract(archive, staging)

    assert program_directory == staging
    assert not (staging / "leftover.txt").exists()
