from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path, PurePosixPath

import pytest
from sqlalchemy import func, select

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import (
    Attachment,
    Base,
    ReimbursementBatch,
)
from reimbursement_manager.database.repositories import (
    AttachmentRepository,
    BatchRepository,
    MaterialTypeRepository,
)
from reimbursement_manager.domain import AttachmentHealth
from reimbursement_manager.services import (
    AttachmentCopyVerificationError,
    AttachmentNotFoundError,
    AttachmentService,
    DuplicateAttachmentError,
    HashService,
    ItemNotFoundError,
    ItemService,
    MaterialRequirementNotFoundError,
    StoragePathService,
    TemplateService,
    UnsupportedAttachmentTypeError,
)


@pytest.fixture
def database() -> Iterator[DatabaseManager]:
    manager = DatabaseManager.in_memory()
    Base.metadata.create_all(manager.engine)
    try:
        yield manager
    finally:
        manager.dispose()


def prepare_item(
    database: DatabaseManager,
    *,
    sequence_number: int = 1,
    name: str = "树莓派Zero2W",
    batch_id: int | None = None,
) -> tuple[int, int]:
    template = TemplateService(database).ensure_default_template()
    if batch_id is None:
        with database.transaction() as session:
            batch = BatchRepository(session).create(
                ReimbursementBatch(name="实验耗材报销")
            )
            batch_id = batch.id
    item = ItemService(database).create_item(
        batch_id=batch_id,
        template_id=template.id,
        sequence_number=sequence_number,
        name=name,
        total_amount_cents=100,
    )
    return item.id, batch_id


def material_type_id(database: DatabaseManager, code: str) -> int:
    with database.transaction() as session:
        material_type = MaterialTypeRepository(session).get_by_code(code)
        assert material_type is not None
        return material_type.id


def make_service(
    database: DatabaseManager, archive_root: Path, **dependencies: object
) -> AttachmentService:
    return AttachmentService(
        database,
        StoragePathService(archive_root),
        **dependencies,  # type: ignore[arg-type]
    )


def test_add_attachment_copies_file_and_persists_relative_metadata(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, _ = prepare_item(database)
    invoice_id = material_type_id(database, "invoice")
    source_directory = tmp_path / "微信下载"
    source_directory.mkdir()
    source = source_directory / "原始发票.PDF"
    source.write_bytes(b"invoice content")
    archive_root = tmp_path / "报销归档"
    storage = StoragePathService(archive_root)

    attachment = AttachmentService(database, storage).add_attachment(
        item_id=item_id,
        material_type_id=invoice_id,
        source_path=source,
    )

    assert attachment.id is not None
    assert attachment.item_id == item_id
    assert attachment.material_type_id == invoice_id
    assert attachment.original_filename == "原始发票.PDF"
    assert attachment.stored_filename == "001_树莓派Zero2W_发票_01.pdf"
    assert attachment.file_extension == ".pdf"
    assert attachment.file_size == len(b"invoice content")
    assert attachment.health is AttachmentHealth.OK
    assert len(attachment.sha256) == 64
    assert not PurePosixPath(attachment.relative_path).is_absolute()
    assert attachment.relative_path.endswith(
        "001_树莓派Zero2W/001_树莓派Zero2W_发票_01.pdf"
    )
    target = storage.resolve_relative_path(attachment.relative_path)
    assert source.read_bytes() == b"invoice content"
    assert target.read_bytes() == b"invoice content"

    with database.transaction() as session:
        stored = AttachmentRepository(session).get_by_id(attachment.id)
        assert stored is not None
        assert stored.relative_path == attachment.relative_path


def test_multiple_attachments_for_one_material_receive_next_indexes(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, _ = prepare_item(database)
    invoice_id = material_type_id(database, "invoice")
    first_source = tmp_path / "first.pdf"
    second_source = tmp_path / "second.pdf"
    first_source.write_bytes(b"first invoice")
    second_source.write_bytes(b"second invoice")
    service = make_service(database, tmp_path / "archive")

    first = service.add_attachment(
        item_id=item_id,
        material_type_id=invoice_id,
        source_path=first_source,
    )
    second = service.add_attachment(
        item_id=item_id,
        material_type_id=invoice_id,
        source_path=second_source,
    )

    assert first.stored_filename.endswith("_01.pdf")
    assert second.stored_filename.endswith("_02.pdf")


def test_list_attachments_returns_an_items_attachments(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, _ = prepare_item(database)
    invoice_id = material_type_id(database, "invoice")
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"invoice")
    service = make_service(database, tmp_path / "archive")
    attachment = service.add_attachment(
        item_id=item_id,
        material_type_id=invoice_id,
        source_path=source,
    )

    assert [value.id for value in service.list_attachments(item_id)] == [
        attachment.id
    ]
    with pytest.raises(ItemNotFoundError):
        service.list_attachments(999_999)


def test_duplicate_is_rejected_within_item_before_another_copy(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, _ = prepare_item(database)
    invoice_id = material_type_id(database, "invoice")
    first_source = tmp_path / "first.pdf"
    duplicate_source = tmp_path / "renamed-copy.pdf"
    first_source.write_bytes(b"identical invoice")
    duplicate_source.write_bytes(b"identical invoice")
    archive_root = tmp_path / "archive"
    service = make_service(database, archive_root)
    first = service.add_attachment(
        item_id=item_id,
        material_type_id=invoice_id,
        source_path=first_source,
    )

    with pytest.raises(DuplicateAttachmentError) as error:
        service.add_attachment(
            item_id=item_id,
            material_type_id=invoice_id,
            source_path=duplicate_source,
        )

    assert error.value.existing_attachment_id == first.id
    with database.transaction() as session:
        count = session.scalar(select(func.count()).select_from(Attachment))
    assert count == 1
    assert len([path for path in archive_root.rglob("*") if path.is_file()]) == 1


def test_same_hash_is_allowed_for_different_items(
    database: DatabaseManager, tmp_path: Path
) -> None:
    first_item_id, batch_id = prepare_item(database)
    second_item_id, _ = prepare_item(
        database,
        sequence_number=2,
        name="HDMI转接头",
        batch_id=batch_id,
    )
    invoice_id = material_type_id(database, "invoice")
    source = tmp_path / "shared-invoice.pdf"
    source.write_bytes(b"shared invoice")
    service = make_service(database, tmp_path / "archive")

    first = service.add_attachment(
        item_id=first_item_id,
        material_type_id=invoice_id,
        source_path=source,
    )
    second = service.add_attachment(
        item_id=second_item_id,
        material_type_id=invoice_id,
        source_path=source,
    )

    assert first.sha256 == second.sha256
    assert first.item_id != second.item_id
    assert first.relative_path != second.relative_path


def test_rejects_material_not_required_by_item_and_unsupported_type(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, _ = prepare_item(database)
    order_detail_id = material_type_id(database, "order_detail")
    invoice_id = material_type_id(database, "invoice")
    source = tmp_path / "detail.pdf"
    unsupported = tmp_path / "invoice.exe"
    source.write_bytes(b"detail")
    unsupported.write_bytes(b"program")
    service = make_service(database, tmp_path / "archive")

    with pytest.raises(MaterialRequirementNotFoundError):
        service.add_attachment(
            item_id=item_id,
            material_type_id=order_detail_id,
            source_path=source,
        )
    with pytest.raises(UnsupportedAttachmentTypeError, match=".exe"):
        service.add_attachment(
            item_id=item_id,
            material_type_id=invoice_id,
            source_path=unsupported,
        )

    assert not (tmp_path / "archive").exists()


def test_rejects_missing_item_and_missing_source_before_storage_changes(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, _ = prepare_item(database)
    invoice_id = material_type_id(database, "invoice")
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"invoice")
    archive_root = tmp_path / "archive"
    service = make_service(database, archive_root)

    with pytest.raises(ItemNotFoundError):
        service.add_attachment(
            item_id=999_999,
            material_type_id=invoice_id,
            source_path=source,
        )
    with pytest.raises(FileNotFoundError, match="missing.pdf"):
        service.add_attachment(
            item_id=item_id,
            material_type_id=invoice_id,
            source_path=tmp_path / "missing.pdf",
        )

    assert not archive_root.exists()


def test_target_hash_mismatch_removes_file_and_database_record(
    database: DatabaseManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item_id, _ = prepare_item(database)
    invoice_id = material_type_id(database, "invoice")
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"invoice")
    hash_service = HashService()
    original_hash = hash_service.calculate_sha256
    calls = 0

    def mismatched_target_hash(path: Path) -> str:
        nonlocal calls
        calls += 1
        if calls == 2:
            return "f" * 64
        return original_hash(path)

    monkeypatch.setattr(hash_service, "calculate_sha256", mismatched_target_hash)
    archive_root = tmp_path / "archive"
    service = make_service(
        database, archive_root, hash_service=hash_service
    )

    with pytest.raises(AttachmentCopyVerificationError):
        service.add_attachment(
            item_id=item_id,
            material_type_id=invoice_id,
            source_path=source,
        )

    with database.transaction() as session:
        count = session.scalar(select(func.count()).select_from(Attachment))
    assert count == 0
    assert [path for path in archive_root.rglob("*") if path.is_file()] == []


def test_database_write_failure_removes_copied_file(
    database: DatabaseManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item_id, _ = prepare_item(database)
    invoice_id = material_type_id(database, "invoice")
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"invoice")

    def fail_database_write(
        repository: AttachmentRepository, attachment: Attachment
    ) -> Attachment:
        del repository, attachment
        raise RuntimeError("simulated database write failure")

    monkeypatch.setattr(AttachmentRepository, "create", fail_database_write)
    archive_root = tmp_path / "archive"
    service = make_service(database, archive_root)

    with pytest.raises(RuntimeError, match="simulated database write failure"):
        service.add_attachment(
            item_id=item_id,
            material_type_id=invoice_id,
            source_path=source,
        )

    assert source.exists()
    with database.transaction() as session:
        count = session.scalar(select(func.count()).select_from(Attachment))
    assert count == 0
    assert [path for path in archive_root.rglob("*") if path.is_file()] == []


def test_remove_attachment_moves_file_to_trash_and_deletes_record(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, _ = prepare_item(database)
    invoice_id = material_type_id(database, "invoice")
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"invoice")
    archive_root = tmp_path / "archive"
    storage = StoragePathService(archive_root)
    service = AttachmentService(database, storage)
    attachment = service.add_attachment(
        item_id=item_id,
        material_type_id=invoice_id,
        source_path=source,
    )
    original_path = storage.resolve_relative_path(attachment.relative_path)
    trash_path = storage.get_attachment_trash_path(
        attachment_id=attachment.id,
        relative_path=attachment.relative_path,
    )

    service.remove_attachment(attachment.id)

    assert not original_path.exists()
    assert trash_path.read_bytes() == b"invoice"
    with database.transaction() as session:
        assert AttachmentRepository(session).get_by_id(attachment.id) is None


def test_remove_missing_file_still_deletes_stale_database_record(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, _ = prepare_item(database)
    invoice_id = material_type_id(database, "invoice")
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"invoice")
    archive_root = tmp_path / "archive"
    storage = StoragePathService(archive_root)
    service = AttachmentService(database, storage)
    attachment = service.add_attachment(
        item_id=item_id,
        material_type_id=invoice_id,
        source_path=source,
    )
    original_path = storage.resolve_relative_path(attachment.relative_path)
    original_path.unlink()

    service.remove_attachment(attachment.id)

    with database.transaction() as session:
        assert AttachmentRepository(session).get_by_id(attachment.id) is None
    assert not storage.get_attachment_trash_path(
        attachment_id=attachment.id,
        relative_path=attachment.relative_path,
    ).exists()


def test_remove_attachment_restores_file_when_database_delete_fails(
    database: DatabaseManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item_id, _ = prepare_item(database)
    invoice_id = material_type_id(database, "invoice")
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"invoice")
    archive_root = tmp_path / "archive"
    storage = StoragePathService(archive_root)
    service = AttachmentService(database, storage)
    attachment = service.add_attachment(
        item_id=item_id,
        material_type_id=invoice_id,
        source_path=source,
    )
    original_path = storage.resolve_relative_path(attachment.relative_path)
    trash_path = storage.get_attachment_trash_path(
        attachment_id=attachment.id,
        relative_path=attachment.relative_path,
    )

    def fail_delete(
        repository: AttachmentRepository, entity: Attachment
    ) -> None:
        del repository, entity
        raise RuntimeError("simulated database delete failure")

    monkeypatch.setattr(AttachmentRepository, "delete", fail_delete)

    with pytest.raises(RuntimeError, match="simulated database delete failure"):
        service.remove_attachment(attachment.id)

    assert original_path.read_bytes() == b"invoice"
    assert not trash_path.exists()
    with database.transaction() as session:
        assert AttachmentRepository(session).get_by_id(attachment.id) is not None


def test_remove_missing_attachment_raises_clear_error(
    database: DatabaseManager, tmp_path: Path
) -> None:
    service = make_service(database, tmp_path / "archive")

    with pytest.raises(AttachmentNotFoundError):
        service.remove_attachment(999_999)
