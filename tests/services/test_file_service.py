from pathlib import Path
import os
import shutil

import pytest

from reimbursement_manager.domain import FileOperationMode
from reimbursement_manager.services import FileService


def test_ensure_directory_is_recursive_and_idempotent(tmp_path: Path) -> None:
    directory = tmp_path / "报销归档" / "2026-08_实验耗材"
    service = FileService()

    first = service.ensure_directory(directory)
    second = service.ensure_directory(directory)

    assert first == directory
    assert second == directory
    assert directory.is_dir()


def test_file_exists_only_reports_regular_files(tmp_path: Path) -> None:
    source = tmp_path / "发票.pdf"
    source.write_bytes(b"invoice")
    service = FileService()

    assert service.file_exists(source) is True
    assert service.file_exists(tmp_path / "missing.pdf") is False
    assert service.file_exists(tmp_path) is False


def test_reads_file_size_and_lists_directory_files(tmp_path: Path) -> None:
    directory = tmp_path / "archive"
    directory.mkdir()
    (directory / "B.pdf").write_bytes(b"second")
    (directory / "a.pdf").write_bytes(b"first")
    (directory / "nested").mkdir()
    service = FileService()

    assert service.get_file_size(directory / "a.pdf") == 5
    assert service.list_file_names(directory) == ["a.pdf", "B.pdf"]
    assert service.list_file_names(tmp_path / "missing") == []
    with pytest.raises(NotADirectoryError):
        service.list_file_names(directory / "a.pdf")


def test_copy_file_publishes_atomically_and_preserves_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "原始发票.pdf"
    destination_directory = tmp_path / "归档"
    destination = destination_directory / "001_物品_发票_01.pdf"
    source.write_bytes(b"invoice content")
    destination_directory.mkdir()
    rename_calls: list[tuple[Path, Path]] = []
    fsync_calls: list[int] = []
    original_rename = os.rename
    original_fsync = os.fsync

    def tracking_rename(source_path: Path, target_path: Path) -> None:
        temporary_path = Path(source_path)
        final_path = Path(target_path)
        assert temporary_path.exists()
        assert temporary_path.parent == destination.parent
        assert temporary_path.suffix == ".tmp"
        assert not final_path.exists()
        rename_calls.append((temporary_path, final_path))
        original_rename(source_path, target_path)

    def tracking_fsync(file_descriptor: int) -> None:
        fsync_calls.append(file_descriptor)
        original_fsync(file_descriptor)

    monkeypatch.setattr(os, "rename", tracking_rename)
    monkeypatch.setattr(os, "fsync", tracking_fsync)

    result = FileService(copy_chunk_size=4).copy_file(source, destination)

    assert result == destination
    assert source.read_bytes() == b"invoice content"
    assert destination.read_bytes() == b"invoice content"
    assert len(rename_calls) == 1
    assert len(fsync_calls) == 1
    assert list(destination_directory.glob("*.tmp")) == []


def test_transfer_file_defaults_to_copy_and_supports_move(tmp_path: Path) -> None:
    source_copy = tmp_path / "copy-source.pdf"
    copy_target = tmp_path / "copy-target.pdf"
    source_move = tmp_path / "move-source.pdf"
    move_target = tmp_path / "move-target.pdf"
    source_copy.write_bytes(b"copy")
    source_move.write_bytes(b"move")
    service = FileService()

    service.transfer_file(source_copy, copy_target)
    service.transfer_file(
        source_move, move_target, mode=FileOperationMode.MOVE
    )

    assert source_copy.read_bytes() == b"copy"
    assert copy_target.read_bytes() == b"copy"
    assert not source_move.exists()
    assert move_target.read_bytes() == b"move"


def test_delete_file_removes_only_regular_file(tmp_path: Path) -> None:
    source = tmp_path / "delete-me.pdf"
    source.write_bytes(b"delete")
    service = FileService()

    service.delete_file(source)

    assert not source.exists()
    with pytest.raises(FileNotFoundError):
        service.delete_file(source)
    with pytest.raises(IsADirectoryError):
        service.delete_file(tmp_path)


def test_existing_destination_is_never_overwritten(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "destination.pdf"
    source.write_bytes(b"new")
    destination.write_bytes(b"existing")
    service = FileService()

    with pytest.raises(FileExistsError):
        service.copy_file(source, destination)
    with pytest.raises(FileExistsError):
        service.move_file(source, destination)

    assert source.read_bytes() == b"new"
    assert destination.read_bytes() == b"existing"


def test_copy_failure_removes_temporary_and_final_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.pdf"
    destination_directory = tmp_path / "archive"
    destination = destination_directory / "destination.pdf"
    source.write_bytes(b"content")
    destination_directory.mkdir()

    def fail_copy(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError("simulated copy failure")

    monkeypatch.setattr(shutil, "copyfileobj", fail_copy)

    with pytest.raises(OSError, match="simulated copy failure"):
        FileService().copy_file(source, destination)

    assert source.exists()
    assert not destination.exists()
    assert list(destination_directory.iterdir()) == []


def test_rejects_missing_sources_directories_and_missing_parent(
    tmp_path: Path,
) -> None:
    service = FileService()
    missing = tmp_path / "missing.pdf"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"content")

    with pytest.raises(FileNotFoundError, match="missing.pdf"):
        service.copy_file(missing, tmp_path / "target.pdf")
    with pytest.raises(IsADirectoryError):
        service.copy_file(tmp_path, tmp_path / "target.pdf")
    with pytest.raises(FileNotFoundError, match="missing-parent"):
        service.copy_file(
            source, tmp_path / "missing-parent" / "target.pdf"
        )


@pytest.mark.parametrize("copy_chunk_size", [0, -1])
def test_copy_chunk_size_must_be_positive(copy_chunk_size: int) -> None:
    with pytest.raises(ValueError, match="copy_chunk_size"):
        FileService(copy_chunk_size=copy_chunk_size)
