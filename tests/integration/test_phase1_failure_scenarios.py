from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import func, select

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Attachment, Base, ReimbursementBatch
from reimbursement_manager.database.repositories import AttachmentRepository, MaterialTypeRepository
from reimbursement_manager.domain import ReimbursementStatus
from reimbursement_manager.services import AttachmentService, ItemService, StoragePathService, TemplateService
from reimbursement_manager.services.file_service import FileService


@pytest.fixture
def database() -> Iterator[DatabaseManager]:
    manager = DatabaseManager.in_memory()
    Base.metadata.create_all(manager.engine)
    try:
        yield manager
    finally:
        manager.dispose()


def _create_item(database: DatabaseManager, *, batch_name: str, item_name: str) -> tuple[int, int]:
    template = TemplateService(database).ensure_default_template()
    with database.transaction() as session:
        batch = ReimbursementBatch(name=batch_name, status=ReimbursementStatus.COLLECTING)
        session.add(batch)
        session.flush()
        batch_id = batch.id

    item = ItemService(database).create_item(
        batch_id=batch_id,
        name=item_name,
        template_id=template.id,
        sequence_number=1,
    )
    with database.transaction() as session:
        material_type = MaterialTypeRepository(session).get_by_code("invoice")
        assert material_type is not None
        return item.id, material_type.id


def _attachment_count(database: DatabaseManager) -> int:
    with database.transaction() as session:
        return session.scalar(select(func.count()).select_from(Attachment)) or 0


def test_missing_source_and_unwritable_target_leave_no_attachment_record(
    database: DatabaseManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item_id, invoice_type_id = _create_item(
        database, batch_name="2026-08 报销", item_name="测试物品"
    )
    archive_root = tmp_path / "archive"
    file_service = FileService()
    service = AttachmentService(
        database,
        StoragePathService(archive_root),
        file_service=file_service,
    )

    with pytest.raises(FileNotFoundError):
        service.add_attachment(
            item_id=item_id,
            material_type_id=invoice_type_id,
            source_path=tmp_path / "missing.pdf",
        )
    assert _attachment_count(database) == 0

    source_path = tmp_path / "invoice.pdf"
    source_path.write_bytes(b"invoice")

    def deny_copy(source: Path, destination: Path) -> Path:
        raise PermissionError("simulated target directory permission denied")

    monkeypatch.setattr(file_service, "copy_file", deny_copy)
    with pytest.raises(PermissionError, match="permission denied"):
        service.add_attachment(
            item_id=item_id,
            material_type_id=invoice_type_id,
            source_path=source_path,
        )

    assert _attachment_count(database) == 0
    assert not [path for path in archive_root.rglob("*") if path.is_file()]


def test_chinese_paths_illegal_characters_and_name_collision_are_handled(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, invoice_type_id = _create_item(
        database,
        batch_name="2026/08:实验耗材报销",
        item_name="树莓派:Zero?2W",
    )
    storage = StoragePathService(tmp_path / "报销归档")
    service = AttachmentService(database, storage)
    source_directory = tmp_path / "中文来源"
    source_directory.mkdir()
    source_path = source_directory / "发票.pdf"
    source_path.write_bytes(b"invoice")

    item = ItemService(database).get_item(item_id)
    item_directory = storage.get_item_directory(
        batch_name=item.batch.name,
        batch_date=item.batch.created_at.date(),
        sequence_number=item.sequence_number,
        item_name=item.name,
    )
    item_directory.mkdir(parents=True)
    (item_directory / "001_树莓派_Zero_2W_发票_01.pdf").write_bytes(b"existing")

    attachment = service.add_attachment(
        item_id=item_id,
        material_type_id=invoice_type_id,
        source_path=source_path,
    )

    assert attachment.stored_filename == "001_树莓派_Zero_2W_发票_02.pdf"
    assert storage.resolve_relative_path(attachment.relative_path).is_file()
    assert "树莓派" in attachment.relative_path
    for component in Path(attachment.relative_path).parts:
        assert not set('<>:"/\\|?*').intersection(component)


def test_database_write_failure_removes_copied_file(
    database: DatabaseManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item_id, invoice_type_id = _create_item(
        database, batch_name="2026-08 报销", item_name="测试物品"
    )
    archive_root = tmp_path / "archive"
    service = AttachmentService(database, StoragePathService(archive_root))
    source_path = tmp_path / "invoice.pdf"
    source_path.write_bytes(b"invoice")

    def fail_create(
        self: AttachmentRepository, attachment: Attachment
    ) -> Attachment:
        del self, attachment
        raise RuntimeError("simulated database write failure")

    monkeypatch.setattr(AttachmentRepository, "create", fail_create)
    with pytest.raises(RuntimeError, match="database write failure"):
        service.add_attachment(
            item_id=item_id,
            material_type_id=invoice_type_id,
            source_path=source_path,
        )

    assert _attachment_count(database) == 0
    assert not [path for path in archive_root.rglob("*") if path.is_file()]
