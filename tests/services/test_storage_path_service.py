from datetime import date
from pathlib import Path, PurePosixPath

import pytest

from reimbursement_manager.services import StoragePathService


def utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def test_builds_required_batch_item_and_attachment_paths(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "报销归档"
    service = StoragePathService(archive_root)
    stored_filename = "001_树莓派Zero2W_发票_01.pdf"

    batch_directory = service.get_batch_directory(
        batch_name="实验耗材报销", batch_date=date(2026, 8, 28)
    )
    item_directory = service.get_item_directory(
        batch_name="实验耗材报销",
        batch_date=date(2026, 8, 28),
        sequence_number=1,
        item_name="树莓派Zero2W",
    )
    relative_path = service.get_attachment_relative_path(
        batch_name="实验耗材报销",
        batch_date=date(2026, 8, 28),
        sequence_number=1,
        item_name="树莓派Zero2W",
        stored_filename=stored_filename,
    )
    attachment_path = service.get_attachment_path(
        batch_name="实验耗材报销",
        batch_date=date(2026, 8, 28),
        sequence_number=1,
        item_name="树莓派Zero2W",
        stored_filename=stored_filename,
    )

    assert service.archive_root == archive_root.resolve()
    assert batch_directory == archive_root.resolve() / "2026-08_实验耗材报销"
    assert item_directory == batch_directory / "001_树莓派Zero2W"
    assert relative_path == PurePosixPath(
        "2026-08_实验耗材报销/001_树莓派Zero2W/"
        "001_树莓派Zero2W_发票_01.pdf"
    )
    assert relative_path.as_posix() == (
        "2026-08_实验耗材报销/001_树莓派Zero2W/"
        "001_树莓派Zero2W_发票_01.pdf"
    )
    assert attachment_path == item_directory / stored_filename
    assert service.resolve_relative_path(relative_path) == attachment_path


def test_sanitizes_directory_names_and_uses_empty_fallbacks(
    tmp_path: Path,
) -> None:
    service = StoragePathService(tmp_path / "archive")

    sanitized = service.get_item_directory(
        batch_name="  报销:八月. ",
        batch_date=date(2026, 8, 1),
        sequence_number=1,
        item_name="CON",
    )
    fallback = service.get_item_directory(
        batch_name="***",
        batch_date=date(2026, 8, 1),
        sequence_number=2,
        item_name=" . ",
    )

    assert sanitized.parts[-2:] == (
        "2026-08_报销_八月",
        "001__CON",
    )
    assert fallback.parts[-2:] == (
        "2026-08_未命名批次",
        "002_未命名物品",
    )


def test_relative_path_survives_archive_root_migration(tmp_path: Path) -> None:
    first = StoragePathService(tmp_path / "first_archive")
    second = StoragePathService(tmp_path / "second_archive")
    relative_path = first.get_attachment_relative_path(
        batch_name="实验耗材报销",
        batch_date=date(2026, 8, 28),
        sequence_number=1,
        item_name="树莓派Zero2W",
        stored_filename="001_树莓派Zero2W_发票_01.pdf",
    )

    assert first.resolve_relative_path(relative_path) == (
        tmp_path.resolve()
        / "first_archive"
        / Path(*relative_path.parts)
    )
    assert second.resolve_relative_path(relative_path) == (
        tmp_path.resolve()
        / "second_archive"
        / Path(*relative_path.parts)
    )


def test_limits_directory_components_by_utf16_length(tmp_path: Path) -> None:
    service = StoragePathService(tmp_path / "archive")

    item_directory = service.get_item_directory(
        batch_name="😀超长批次" * 100,
        batch_date=date(2026, 8, 28),
        sequence_number=1,
        item_name="😀超长物品" * 100,
    )

    assert utf16_length(item_directory.parts[-2]) <= 120
    assert utf16_length(item_directory.parts[-1]) <= 120
    assert item_directory.parts[-2].startswith("2026-08_")
    assert item_directory.parts[-1].startswith("001_")


def test_path_calculation_does_not_create_directories(tmp_path: Path) -> None:
    archive_root = tmp_path / "not_created"
    service = StoragePathService(archive_root)

    service.get_item_directory(
        batch_name="报销",
        batch_date=date(2026, 8, 28),
        sequence_number=1,
        item_name="物品",
    )

    assert not archive_root.exists()


def test_builds_attachment_id_scoped_trash_path(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    service = StoragePathService(archive_root)
    relative_path = PurePosixPath(
        "2026-08_实验耗材报销/001_树莓派Zero2W/"
        "001_树莓派Zero2W_发票_01.pdf"
    )

    trash_path = service.get_attachment_trash_path(
        attachment_id=42, relative_path=relative_path
    )

    assert trash_path == archive_root.resolve() / ".trash" / "00000042" / Path(
        *relative_path.parts
    )
    assert not archive_root.exists()


@pytest.mark.parametrize(
    "stored_filename",
    [
        "../invoice.pdf",
        "subdir/invoice.pdf",
        "subdir\\invoice.pdf",
        "C:\\invoice.pdf",
        "invoice?.pdf",
        "CON.pdf",
        "invoice.pdf.",
        "",
    ],
)
def test_rejects_unsafe_stored_filenames(
    tmp_path: Path, stored_filename: str
) -> None:
    service = StoragePathService(tmp_path / "archive")

    with pytest.raises(ValueError, match="stored_filename"):
        service.get_attachment_relative_path(
            batch_name="报销",
            batch_date=date(2026, 8, 28),
            sequence_number=1,
            item_name="物品",
            stored_filename=stored_filename,
        )


@pytest.mark.parametrize(
    "relative_path",
    [
        "../outside.pdf",
        "batch/../outside.pdf",
        "/absolute/path.pdf",
        "C:/Windows/path.pdf",
        "C:\\Windows\\path.pdf",
        "\\\\server\\share\\path.pdf",
        "batch//path.pdf",
        "batch/./path.pdf",
        "",
    ],
)
def test_rejects_unsafe_relative_paths(
    tmp_path: Path, relative_path: str
) -> None:
    service = StoragePathService(tmp_path / "archive")

    with pytest.raises(ValueError, match="relative_path"):
        service.resolve_relative_path(relative_path)
