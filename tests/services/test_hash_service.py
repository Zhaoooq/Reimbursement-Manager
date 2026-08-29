from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pytest

from reimbursement_manager.services import HashService


class TrackingReader(BytesIO):
    def __init__(self, content: bytes) -> None:
        super().__init__(content)
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return super().read(size)


def test_same_file_has_same_sha256(tmp_path: Path) -> None:
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"same invoice content")
    service = HashService()

    first = service.calculate_sha256(source)
    second = service.calculate_sha256(source)

    assert first == second
    assert first == hashlib.sha256(b"same invoice content").hexdigest()
    assert len(first) == 64


def test_different_files_have_different_sha256(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    assert HashService().calculate_sha256(first) != HashService().calculate_sha256(
        second
    )


def test_empty_file_hash_matches_sha256_standard(tmp_path: Path) -> None:
    source = tmp_path / "empty.pdf"
    source.write_bytes(b"")

    digest = HashService().calculate_sha256(source)

    assert digest == hashlib.sha256(b"").hexdigest()


def test_supports_unicode_file_paths(tmp_path: Path) -> None:
    source = tmp_path / "树莓派发票.pdf"
    source.write_bytes("中文附件".encode())

    digest = HashService().calculate_sha256(source)

    assert digest == hashlib.sha256("中文附件".encode()).hexdigest()


def test_large_file_is_read_in_fixed_size_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "large.bin"
    source.touch()
    chunk_size = 64 * 1024
    payload = b"large attachment block" * 20_000
    reader = TrackingReader(payload)

    def open_tracking_reader(
        path: Path, mode: str = "r", *args: object, **kwargs: object
    ) -> TrackingReader:
        del args, kwargs
        assert path == source
        assert mode == "rb"
        return reader

    monkeypatch.setattr(Path, "open", open_tracking_reader)

    digest = HashService(chunk_size=chunk_size).calculate_sha256(source)

    assert digest == hashlib.sha256(payload).hexdigest()
    assert len(reader.read_sizes) > 2
    assert set(reader.read_sizes) == {chunk_size}
    assert -1 not in reader.read_sizes


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    missing = tmp_path / "missing.pdf"

    with pytest.raises(FileNotFoundError, match="missing.pdf"):
        HashService().calculate_sha256(missing)


def test_directory_is_not_accepted_as_a_file(tmp_path: Path) -> None:
    with pytest.raises(IsADirectoryError):
        HashService().calculate_sha256(tmp_path)


@pytest.mark.parametrize("chunk_size", [0, -1])
def test_chunk_size_must_be_positive(chunk_size: int) -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        HashService(chunk_size=chunk_size)
