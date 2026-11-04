from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Attachment, Base
from reimbursement_manager.database.repositories import MaterialTypeRepository
from reimbursement_manager.services import (
    AttachmentService,
    BatchService,
    CompletenessService,
    ItemService,
    PaymentScreenshotMergeService,
    StoragePathService,
    SubmissionReadinessService,
    TemplateService,
)
from reimbursement_manager.services.payment_screenshot_merge_service import (
    MERGED_PAYMENT_ORIGINAL_FILENAME,
    is_merged_payment_screenshot,
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
    image = QImage(2, 2, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    assert image.save(str(path), "PNG")
    return path


def test_only_the_known_payment_merge_derivation_is_a_submission_file() -> None:
    common = dict(
        item_id=1,
        material_type_id=7,
        stored_filename="derived.png",
        relative_path="batch/item/derived.png",
        file_extension=".png",
        file_size=1,
        sha256="a" * 64,
        is_derived=True,
    )
    merged = Attachment(
        original_filename=MERGED_PAYMENT_ORIGINAL_FILENAME,
        **common,
    )
    unrelated_derivation = Attachment(
        original_filename="future derived attachment",
        **common,
    )

    assert is_merged_payment_screenshot(merged, payment_material_type_id=7)
    assert not is_merged_payment_screenshot(
        unrelated_derivation, payment_material_type_id=7
    )


def create_collected_item(
    database: DatabaseManager, tmp_path: Path
) -> tuple[int, AttachmentService, StoragePathService]:
    batch = BatchService(database).create_batch(name="提交就绪测试")
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
    source_paths["invoice"].write_bytes(b"invoice")
    for code, source_path in source_paths.items():
        attachments.add_attachment(
            item_id=item.id,
            material_type_id=material_type_ids[code],
            source_path=source_path,
        )
    return item.id, attachments, storage


def test_submission_readiness_is_independent_of_collection_completeness(
    database: DatabaseManager,
    tmp_path: Path,
) -> None:
    item_id, attachments, storage = create_collected_item(database, tmp_path)
    collection = CompletenessService(database, storage)
    submission = SubmissionReadinessService(database, storage)

    # A: source materials are collected, but the final merge is absent.
    assert (
        collection.calculate(item_id).completed_count,
        collection.calculate(item_id).required_count,
    ) == (4, 4)
    before_merge = submission.calculate(item_id)
    assert (before_merge.completed_count, before_merge.required_count) == (2, 3)
    assert before_merge.is_ready is False
    assert [material.name for material in before_merge.missing] == ["合并支付截图"]

    # B: the derived merge completes the final submission set only.
    merged = PaymentScreenshotMergeService(database, storage).generate(item_id)
    assert (
        collection.calculate(item_id).completed_count,
        collection.calculate(item_id).required_count,
    ) == (4, 4)
    after_merge = submission.calculate(item_id)
    assert (after_merge.completed_count, after_merge.required_count) == (3, 3)
    assert after_merge.is_ready is True

    # C: removing the merge does not remove original collection material.
    attachments.remove_attachment(merged.id)
    assert (
        collection.calculate(item_id).completed_count,
        collection.calculate(item_id).required_count,
    ) == (4, 4)
    after_merge_removal = submission.calculate(item_id)
    assert (after_merge_removal.completed_count, after_merge_removal.required_count) == (2, 3)
    assert after_merge_removal.is_ready is False

    # D: removing an original source makes collection incomplete even if a merge exists.
    replacement_merge = PaymentScreenshotMergeService(database, storage).generate(item_id)
    with database.transaction() as session:
        order_type = MaterialTypeRepository(session).get_by_code("order_screenshot")
        assert order_type is not None
        order_material_type_id = order_type.id
    order_attachment = next(
        attachment
        for attachment in attachments.list_attachments(item_id)
        if not attachment.is_derived
        and attachment.material_type_id == order_material_type_id
    )
    attachments.remove_attachment(order_attachment.id)
    assert replacement_merge.id > 0
    after_order_removal = collection.calculate(item_id)
    assert (
        after_order_removal.completed_count,
        after_order_removal.required_count,
    ) == (3, 4)
    assert after_order_removal.is_complete is False


def create_print_shop_item(
    database: DatabaseManager, tmp_path: Path
) -> tuple[int, AttachmentService, StoragePathService]:
    """Item whose template asks for a checklist but no order screenshot."""
    batch = BatchService(database).create_batch(name="打印店报销")
    templates = TemplateService(database)
    templates.ensure_default_template()
    template = templates.create_template("打印店")
    checklist = templates.create_material_type("清单")
    for sort_order, code in enumerate(
        ("physical_photo", "payment_screenshot", "invoice", checklist.code), start=1
    ):
        templates.add_material(template.id, code, sort_order=sort_order)

    item = ItemService(database).create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="墙报",
    )
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    sources = {
        "physical_photo": write_image(tmp_path / "photo.png", color="red"),
        "invoice": tmp_path / "invoice.pdf",
        "custom": write_image(tmp_path / "checklist.png", color="yellow"),
    }
    sources["invoice"].write_bytes(b"invoice")
    for code, source_path in sources.items():
        attachments.add_attachment(
            item_id=item.id,
            material_type_id=material_type_id(database, code),
            source_path=source_path,
        )
    return item.id, attachments, storage


def material_type_id(database: DatabaseManager, code: str) -> int:
    with database.transaction() as session:
        material_type = MaterialTypeRepository(session).get_by_code(code)
        assert material_type is not None
        return material_type.id


def test_template_without_order_screenshot_does_not_require_a_merge(
    database: DatabaseManager,
    tmp_path: Path,
) -> None:
    item_id, attachments, storage = create_print_shop_item(database, tmp_path)
    submission = SubmissionReadinessService(database, storage)

    # 实物照片 + 发票 + 清单 are collected; only the payment screenshot is absent.
    missing_payment = submission.calculate(item_id)
    assert (
        missing_payment.completed_count,
        missing_payment.required_count,
    ) == (3, 4)
    assert [material.name for material in missing_payment.missing] == ["支付截图"]

    attachments.add_attachment(
        item_id=item_id,
        material_type_id=material_type_id(database, "payment_screenshot"),
        source_path=write_image(tmp_path / "payment.png", color="blue"),
    )

    ready = submission.calculate(item_id)
    assert (ready.completed_count, ready.required_count) == (4, 4)
    assert ready.is_ready is True
    assert ready.missing == ()
