from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Attachment, Base, ReimbursementBatch
from reimbursement_manager.database.repositories import AttachmentRepository, MaterialTypeRepository
from reimbursement_manager.domain import AttachmentHealth, ReimbursementStatus
from reimbursement_manager.services import (
    AttachmentService,
    CompletenessService,
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


def _material_type_id(database: DatabaseManager, code: str) -> int:
    with database.transaction() as session:
        material_type = MaterialTypeRepository(session).get_by_code(code)
        assert material_type is not None
        return material_type.id


def test_phase1_business_chain_tracks_missing_materials_and_external_deletion(
    database: DatabaseManager, tmp_path: Path
) -> None:
    template_service = TemplateService(database)
    template = template_service.ensure_default_template()

    with database.transaction() as session:
        batch = ReimbursementBatch(
            name="2026-08 实验耗材报销",
            status=ReimbursementStatus.COLLECTING,
        )
        session.add(batch)
        session.flush()
        batch_id = batch.id

    item_service = ItemService(database)
    item = item_service.create_item(
        batch_id=batch_id,
        name="树莓派 Zero 2 W",
        template_id=template.id,
        sequence_number=1,
    )
    assert len(item.requirements) == 4

    storage = StoragePathService(tmp_path / "archive")
    attachment_service = AttachmentService(database, storage)
    completeness_service = CompletenessService(database, storage)
    source_directory = tmp_path / "sources"
    source_directory.mkdir()

    for material_code, source_name in (
        ("physical_photo", "physical.jpg"),
        ("payment_screenshot", "payment.png"),
        ("order_screenshot", "order.png"),
    ):
        source_path = source_directory / source_name
        source_path.write_bytes(material_code.encode("utf-8"))
        attachment_service.add_attachment(
            item_id=item.id,
            material_type_id=_material_type_id(database, material_code),
            source_path=source_path,
        )

    incomplete = completeness_service.calculate(item.id)
    assert incomplete.required_count == 4
    assert incomplete.completed_count == 3
    assert incomplete.percentage == 75
    assert not incomplete.is_complete
    assert [material.code for material in incomplete.missing] == ["invoice"]

    invoice_source = source_directory / "invoice.pdf"
    invoice_source.write_bytes(b"invoice")
    invoice_attachment = attachment_service.add_attachment(
        item_id=item.id,
        material_type_id=_material_type_id(database, "invoice"),
        source_path=invoice_source,
    )

    complete = completeness_service.calculate(item.id)
    assert complete.required_count == 4
    assert complete.completed_count == 4
    assert complete.percentage == 100
    assert complete.is_complete
    assert complete.missing == ()

    storage.resolve_relative_path(invoice_attachment.relative_path).unlink()

    after_external_deletion = completeness_service.calculate(item.id)
    assert after_external_deletion.required_count == 4
    assert after_external_deletion.completed_count == 3
    assert not after_external_deletion.is_complete
    assert [material.code for material in after_external_deletion.missing] == ["invoice"]

    with database.transaction() as session:
        attachment = AttachmentRepository(session).get_by_id(invoice_attachment.id)
        assert attachment is not None
        assert attachment.health is AttachmentHealth.MISSING
