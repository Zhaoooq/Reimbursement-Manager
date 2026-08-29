from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Base, ReimbursementBatch
from reimbursement_manager.database.repositories import (
    AttachmentRepository,
    BatchRepository,
    MaterialTypeRepository,
)
from reimbursement_manager.domain import AttachmentHealth
from reimbursement_manager.services import (
    AttachmentService,
    CompletenessService,
    ItemNotFoundError,
    ItemService,
    StoragePathService,
    TemplateService,
)


@pytest.fixture
def database() -> Iterator[DatabaseManager]:
    manager = DatabaseManager.in_memory()
    Base.metadata.create_all(manager.engine)
    try:
        yield manager
    finally:
        manager.dispose()


def prepare_default_item(database: DatabaseManager) -> tuple[int, dict[str, int]]:
    template = TemplateService(database).ensure_default_template()
    with database.transaction() as session:
        batch = BatchRepository(session).create(
            ReimbursementBatch(name="实验耗材报销")
        )
        material_repository = MaterialTypeRepository(session)
        material_ids = {
            code: material_repository.get_by_code(code).id  # type: ignore[union-attr]
            for code in (
                "physical_photo",
                "payment_screenshot",
                "invoice",
                "order_screenshot",
            )
        }
    item = ItemService(database).create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派Zero2W",
        total_amount_cents=100,
    )
    return item.id, material_ids


def import_attachment(
    database: DatabaseManager,
    archive_root: Path,
    *,
    item_id: int,
    material_type_id: int,
    filename: str,
    content: bytes,
) -> tuple[Path, object]:
    source = archive_root.parent / "sources" / filename
    source.parent.mkdir(exist_ok=True)
    source.write_bytes(content)
    service = AttachmentService(
        database, StoragePathService(archive_root)
    )
    attachment = service.add_attachment(
        item_id=item_id,
        material_type_id=material_type_id,
        source_path=source,
    )
    return source, attachment


def test_calculates_three_of_four_and_reports_missing_invoice(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, material_ids = prepare_default_item(database)
    archive_root = tmp_path / "archive"
    for code, filename in (
        ("physical_photo", "photo.jpg"),
        ("payment_screenshot", "payment.png"),
        ("order_screenshot", "order.png"),
    ):
        import_attachment(
            database,
            archive_root,
            item_id=item_id,
            material_type_id=material_ids[code],
            filename=filename,
            content=code.encode(),
        )

    result = CompletenessService(
        database, StoragePathService(archive_root)
    ).calculate(item_id)

    assert result.required_count == 4
    assert result.completed_count == 3
    assert result.percentage == 75
    assert result.is_complete is False
    assert [(value.code, value.name) for value in result.missing] == [
        ("invoice", "发票")
    ]


def test_external_deletion_changes_completeness_and_attachment_health(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, material_ids = prepare_default_item(database)
    archive_root = tmp_path / "archive"
    for code, filename in (
        ("physical_photo", "photo.jpg"),
        ("payment_screenshot", "payment.png"),
        ("order_screenshot", "order.png"),
    ):
        import_attachment(
            database,
            archive_root,
            item_id=item_id,
            material_type_id=material_ids[code],
            filename=filename,
            content=code.encode(),
        )
    source, invoice = import_attachment(
        database,
        archive_root,
        item_id=item_id,
        material_type_id=material_ids["invoice"],
        filename="invoice.pdf",
        content=b"invoice",
    )
    storage = StoragePathService(archive_root)
    target = storage.resolve_relative_path(invoice.relative_path)  # type: ignore[attr-defined]
    target.unlink()
    service = CompletenessService(database, storage)

    result = service.calculate(item_id)

    assert result.completed_count == 3
    assert result.percentage == 75
    assert [value.code for value in result.missing] == ["invoice"]
    with database.transaction() as session:
        stored = AttachmentRepository(session).get_by_id(invoice.id)  # type: ignore[attr-defined]
        assert stored is not None
        assert stored.health is AttachmentHealth.MISSING

    target.write_bytes(source.read_bytes())
    recovered = service.calculate(item_id)
    assert recovered.is_complete is True
    with database.transaction() as session:
        stored = AttachmentRepository(session).get_by_id(invoice.id)  # type: ignore[attr-defined]
        assert stored is not None
        assert stored.health is AttachmentHealth.OK


def test_one_valid_attachment_satisfies_material_when_another_is_missing(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, material_ids = prepare_default_item(database)
    archive_root = tmp_path / "archive"
    for code, filename in (
        ("physical_photo", "photo.jpg"),
        ("payment_screenshot", "payment.png"),
        ("order_screenshot", "order.png"),
    ):
        import_attachment(
            database,
            archive_root,
            item_id=item_id,
            material_type_id=material_ids[code],
            filename=filename,
            content=code.encode(),
        )
    _, first_invoice = import_attachment(
        database,
        archive_root,
        item_id=item_id,
        material_type_id=material_ids["invoice"],
        filename="invoice-first.pdf",
        content=b"first invoice",
    )
    _, second_invoice = import_attachment(
        database,
        archive_root,
        item_id=item_id,
        material_type_id=material_ids["invoice"],
        filename="invoice-second.pdf",
        content=b"second invoice",
    )
    storage = StoragePathService(archive_root)
    storage.resolve_relative_path(first_invoice.relative_path).unlink()  # type: ignore[attr-defined]

    result = CompletenessService(database, storage).calculate(item_id)

    assert result.is_complete is True
    with database.transaction() as session:
        first = AttachmentRepository(session).get_by_id(first_invoice.id)  # type: ignore[attr-defined]
        second = AttachmentRepository(session).get_by_id(second_invoice.id)  # type: ignore[attr-defined]
        assert first is not None and first.health is AttachmentHealth.MISSING
        assert second is not None and second.health is AttachmentHealth.OK


def test_item_with_no_required_materials_is_complete(
    database: DatabaseManager, tmp_path: Path
) -> None:
    template = TemplateService(database).create_template("空模板")
    with database.transaction() as session:
        batch = BatchRepository(session).create(ReimbursementBatch(name="批次"))
    item = ItemService(database).create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="无需材料物品",
        total_amount_cents=100,
    )

    result = CompletenessService(
        database, StoragePathService(tmp_path / "archive")
    ).calculate(item.id)

    assert result.required_count == 0
    assert result.completed_count == 0
    assert result.percentage == 100
    assert result.is_complete is True
    assert result.missing == ()


def test_missing_item_raises_clear_error(
    database: DatabaseManager, tmp_path: Path
) -> None:
    service = CompletenessService(
        database, StoragePathService(tmp_path / "archive")
    )

    with pytest.raises(ItemNotFoundError):
        service.calculate(999_999)
