from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Base
from reimbursement_manager.database.repositories import MaterialTypeRepository
from reimbursement_manager.services import (
    AttachmentService,
    BatchService,
    CompletenessService,
    ExportService,
    ExportTargetExistsError,
    ItemService,
    PaymentScreenshotMergeService,
    StoragePathService,
    SubmissionMaterialsIncompleteError,
    SubmissionReadinessService,
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


def write_image(path: Path, *, color: str) -> Path:
    image = QImage(3, 2, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    assert image.save(str(path), "PNG")
    return path


def create_collected_item(
    database: DatabaseManager, tmp_path: Path
) -> tuple[int, AttachmentService, StoragePathService]:
    batch = BatchService(database).create_batch(name="实验耗材报销")
    template = TemplateService(database).ensure_default_template()
    item = ItemService(database).create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W",
    )
    with database.transaction() as session:
        material_types = MaterialTypeRepository(session)
        material_type_ids = {
            code: material_types.get_by_code(code).id  # type: ignore[union-attr]
            for code in (
                "physical_photo",
                "invoice",
                "order_screenshot",
                "payment_screenshot",
            )
        }

    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    source_paths = {
        "physical_photo": write_image(tmp_path / "photo.png", color="red"),
        "invoice": tmp_path / "invoice.pdf",
        "order_screenshot": write_image(tmp_path / "order.png", color="green"),
        "payment_screenshot": write_image(
            tmp_path / "payment.png", color="blue"
        ),
    }
    source_paths["invoice"].write_bytes(b"invoice one")
    for code, source_path in source_paths.items():
        attachments.add_attachment(
            item_id=item.id,
            material_type_id=material_type_ids[code],
            source_path=source_path,
        )
    return item.id, attachments, storage


def material_type_id(database: DatabaseManager, code: str) -> int:
    with database.transaction() as session:
        material_type = MaterialTypeRepository(session).get_by_code(code)
        assert material_type is not None
        return material_type.id


def make_ready_export_service(
    database: DatabaseManager, tmp_path: Path
) -> tuple[int, AttachmentService, StoragePathService, ExportService]:
    item_id, attachments, storage = create_collected_item(database, tmp_path)
    PaymentScreenshotMergeService(database, storage).generate(item_id)
    return item_id, attachments, storage, ExportService(database, storage)


def test_exports_only_final_submission_materials_and_renames_merge(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, _, _, exporter = make_ready_export_service(database, tmp_path)

    result = exporter.export_item(item_id, tmp_path / "export")

    names = sorted(path.name for path in result.exported_files)
    assert len(names) == 3
    assert any("实物图_01.png" in name for name in names)
    assert any("发票_01.pdf" in name for name in names)
    assert any("支付截图_01.png" in name for name in names)
    assert not any("订单截图" in name for name in names)
    assert not any("合并" in name for name in names)
    assert all(path.is_file() for path in result.exported_files)


def test_exports_all_physical_photos_in_deterministic_order(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, attachments, _, exporter = make_ready_export_service(database, tmp_path)
    attachments.add_attachment(
        item_id=item_id,
        material_type_id=material_type_id(database, "physical_photo"),
        source_path=write_image(tmp_path / "photo-two.png", color="yellow"),
    )

    result = exporter.export_item(item_id, tmp_path / "export")

    physical_names = [
        path.name for path in result.exported_files if "实物图" in path.name
    ]
    assert [name[-6:] for name in physical_names] == ["01.png", "02.png"]


def test_exports_all_invoices_in_deterministic_order(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, attachments, _, exporter = make_ready_export_service(database, tmp_path)
    second_invoice = tmp_path / "invoice-two.pdf"
    second_invoice.write_bytes(b"invoice two")
    attachments.add_attachment(
        item_id=item_id,
        material_type_id=material_type_id(database, "invoice"),
        source_path=second_invoice,
    )

    result = exporter.export_item(item_id, tmp_path / "export")

    invoice_names = [
        path.name for path in result.exported_files if "发票" in path.name
    ]
    assert [name[-6:] for name in invoice_names] == ["01.pdf", "02.pdf"]


def test_exports_only_the_latest_merged_payment_screenshot(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, _, storage, exporter = make_ready_export_service(database, tmp_path)
    latest = PaymentScreenshotMergeService(database, storage).generate(item_id)

    result = exporter.export_item(item_id, tmp_path / "export")

    payment_file = next(
        path for path in result.exported_files if "支付截图" in path.name
    )
    assert payment_file.name.endswith("支付截图_01.png")
    assert payment_file.read_bytes() == storage.resolve_relative_path(
        latest.relative_path
    ).read_bytes()


def test_incomplete_submission_is_rejected_before_creating_export_directory(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, _, storage = create_collected_item(database, tmp_path)
    destination = tmp_path / "export"

    with pytest.raises(
        SubmissionMaterialsIncompleteError,
        match="当前提交材料不完整：缺少合并支付截图",
    ):
        ExportService(database, storage).export_item(item_id, destination)

    assert not destination.exists()


def test_missing_export_source_fails_without_leaving_final_directory(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, _, storage, exporter = make_ready_export_service(database, tmp_path)
    merged = next(
        attachment
        for attachment in AttachmentService(database, storage).list_attachments(item_id)
        if attachment.is_derived
    )
    storage.resolve_relative_path(merged.relative_path).unlink()
    destination = tmp_path / "export"

    with pytest.raises(SubmissionMaterialsIncompleteError):
        exporter.export_item(item_id, destination)

    assert not destination.joinpath("001_树莓派 Zero 2 W").exists()
    assert list(destination.glob(".tmp_*")) == [] if destination.exists() else True


def test_existing_item_export_directory_is_not_overwritten(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, _, _, exporter = make_ready_export_service(database, tmp_path)
    destination = tmp_path / "export"
    first = exporter.export_item(item_id, destination)

    with pytest.raises(ExportTargetExistsError):
        exporter.export_item(item_id, destination)

    assert all(path.is_file() for path in first.exported_files)


def test_export_does_not_change_business_state_or_attachment_records(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, attachments, storage, exporter = make_ready_export_service(database, tmp_path)
    completeness = CompletenessService(database, storage).calculate(item_id)
    readiness = SubmissionReadinessService(database, storage).calculate(item_id)
    before_attachments = [
        (attachment.id, attachment.relative_path, attachment.stored_filename)
        for attachment in attachments.list_attachments(item_id)
    ]

    exporter.export_item(item_id, tmp_path / "export")

    assert CompletenessService(database, storage).calculate(item_id) == completeness
    assert SubmissionReadinessService(database, storage).calculate(item_id) == readiness
    assert [
        (attachment.id, attachment.relative_path, attachment.stored_filename)
        for attachment in attachments.list_attachments(item_id)
    ] == before_attachments
