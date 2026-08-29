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
    CompletenessService,
    ImageMergeService,
    ItemService,
    PaymentScreenshotMergeService,
    RequiredScreenshotMissingError,
    StoragePathService,
    TemplateService,
    UnsupportedMergeSourceError,
)
from reimbursement_manager.services.batch_service import BatchService


@pytest.fixture
def database() -> Iterator[DatabaseManager]:
    manager = DatabaseManager.in_memory()
    Base.metadata.create_all(manager.engine)
    try:
        yield manager
    finally:
        manager.dispose()


def write_image(path: Path, *, width: int, height: int, color: str) -> Path:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    assert image.save(str(path), "PNG")
    return path


def make_item(database: DatabaseManager) -> tuple[int, dict[str, int]]:
    batch = BatchService(database).create_batch(name="合并测试")
    template = TemplateService(database).ensure_default_template()
    item = ItemService(database).create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W",
    )
    with database.transaction() as session:
        repository = MaterialTypeRepository(session)
        material_ids = {
            code: repository.get_by_code(code).id  # type: ignore[union-attr]
            for code in ("order_screenshot", "payment_screenshot")
        }
    return item.id, material_ids


def add_image(
    attachment_service: AttachmentService,
    *,
    item_id: int,
    material_type_id: int,
    path: Path,
) -> None:
    attachment_service.add_attachment(
        item_id=item_id,
        material_type_id=material_type_id,
        source_path=path,
    )


def test_image_merge_uses_side_by_side_canvas_and_source_pixels(tmp_path: Path) -> None:
    order = write_image(tmp_path / "order.png", width=2, height=3, color="red")
    payment = write_image(
        tmp_path / "payment.png", width=4, height=5, color="blue"
    )
    order_bytes = order.read_bytes()
    payment_bytes = payment.read_bytes()
    output = tmp_path / "merged.png"

    ImageMergeService().merge(
        order_image_path=order,
        payment_image_path=payment,
        output_path=output,
    )

    result = QImage(str(output))
    assert (result.width(), result.height()) == (6, 5)
    assert result.pixelColor(0, 0) == QColor("red")
    assert result.pixelColor(2, 0) == QColor("blue")
    assert result.pixelColor(0, 4) == QColor("white")
    assert order.read_bytes() == order_bytes
    assert payment.read_bytes() == payment_bytes


def test_generation_is_derived_and_does_not_change_completeness(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, material_ids = make_item(database)
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    add_image(
        attachments,
        item_id=item_id,
        material_type_id=material_ids["order_screenshot"],
        path=write_image(tmp_path / "order.png", width=3, height=2, color="red"),
    )
    add_image(
        attachments,
        item_id=item_id,
        material_type_id=material_ids["payment_screenshot"],
        path=write_image(tmp_path / "payment.png", width=2, height=4, color="blue"),
    )
    completeness = CompletenessService(database, storage)
    before = completeness.calculate(item_id)
    merge_service = PaymentScreenshotMergeService(database, storage)
    merged = merge_service.generate(item_id)
    repeated = merge_service.generate(item_id)
    after = completeness.calculate(item_id)

    assert merged.is_derived is True
    assert "支付截图_合并_01.png" in merged.stored_filename
    assert "支付截图_合并_02.png" in repeated.stored_filename
    assert storage.resolve_relative_path(merged.relative_path).is_file()
    assert (after.required_count, after.completed_count) == (
        before.required_count,
        before.completed_count,
    )


@pytest.mark.parametrize(
    ("missing_code", "expected_error"),
    [
        ("order_screenshot", RequiredScreenshotMissingError),
        ("payment_screenshot", RequiredScreenshotMissingError),
    ],
)
def test_generation_requires_both_source_screenshots(
    database: DatabaseManager,
    tmp_path: Path,
    missing_code: str,
    expected_error: type[Exception],
) -> None:
    item_id, material_ids = make_item(database)
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    present_code = (
        "payment_screenshot"
        if missing_code == "order_screenshot"
        else "order_screenshot"
    )
    add_image(
        attachments,
        item_id=item_id,
        material_type_id=material_ids[present_code],
        path=write_image(tmp_path / "present.png", width=2, height=2, color="blue"),
    )

    with pytest.raises(expected_error):
        PaymentScreenshotMergeService(database, storage).generate(item_id)


def test_generation_uses_most_recent_valid_image_attachment(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, material_ids = make_item(database)
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    add_image(
        attachments,
        item_id=item_id,
        material_type_id=material_ids["order_screenshot"],
        path=write_image(tmp_path / "old-order.png", width=2, height=2, color="red"),
    )
    add_image(
        attachments,
        item_id=item_id,
        material_type_id=material_ids["order_screenshot"],
        path=write_image(tmp_path / "new-order.png", width=2, height=2, color="green"),
    )
    add_image(
        attachments,
        item_id=item_id,
        material_type_id=material_ids["payment_screenshot"],
        path=write_image(tmp_path / "payment.png", width=2, height=2, color="blue"),
    )

    merged = PaymentScreenshotMergeService(database, storage).generate(item_id)
    output = QImage(str(storage.resolve_relative_path(merged.relative_path)))

    assert output.pixelColor(0, 0) == QColor("green")


def test_pdf_source_reports_clear_error_without_crashing(
    database: DatabaseManager, tmp_path: Path
) -> None:
    item_id, material_ids = make_item(database)
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    pdf = tmp_path / "order.pdf"
    pdf.write_bytes(b"not an image")
    add_image(
        attachments,
        item_id=item_id,
        material_type_id=material_ids["order_screenshot"],
        path=pdf,
    )
    add_image(
        attachments,
        item_id=item_id,
        material_type_id=material_ids["payment_screenshot"],
        path=write_image(tmp_path / "payment.png", width=2, height=2, color="blue"),
    )

    with pytest.raises(UnsupportedMergeSourceError, match="JPG/PNG"):
        PaymentScreenshotMergeService(database, storage).generate(item_id)
