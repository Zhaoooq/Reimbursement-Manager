from __future__ import annotations

from PySide6.QtGui import QColor, QImage

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Base
from reimbursement_manager.database.repositories import MaterialTypeRepository
from reimbursement_manager.services import (
    AttachmentService,
    BatchService,
    CompletenessService,
    ItemService,
    PaymentScreenshotMergeService,
    PendingMaterialsService,
    StoragePathService,
    SubmissionReadinessService,
    TemplateService,
)


def _create_pending_service(tmp_path):
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch = BatchService(database).create_batch(name="8月实验耗材")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W",
    )
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    completeness = CompletenessService(database, storage)
    submission = SubmissionReadinessService(database, storage)
    pending = PendingMaterialsService(item_service, completeness, submission)
    return database, item, attachments, pending


def _add_all_original_materials(tmp_path, database, item, attachments) -> None:
    with database.transaction() as session:
        materials = MaterialTypeRepository(session)
        material_type_ids = {
            code: materials.get_by_code(code).id  # type: ignore[union-attr]
            for code in (
                "physical_photo",
                "payment_screenshot",
                "invoice",
                "order_screenshot",
            )
        }
    for code, material_type_id in material_type_ids.items():
        source = tmp_path / f"{code}.png"
        if code == "invoice":
            source = tmp_path / "invoice.pdf"
            source.write_bytes(b"invoice")
        else:
            image = QImage(2, 2, QImage.Format.Format_RGB32)
            image.fill(
                QColor(
                    {
                        "physical_photo": "red",
                        "payment_screenshot": "blue",
                        "order_screenshot": "green",
                    }[code]
                )
            )
            assert image.save(str(source), "PNG")
        attachments.add_attachment(
            item_id=item.id,
            material_type_id=material_type_id,
            source_path=source,
        )


def test_pending_items_include_original_and_submission_gaps_and_refresh(tmp_path) -> None:
    database, item, attachments, pending = _create_pending_service(tmp_path)
    try:
        initial = pending.list_pending_items()
        assert [entry.item_id for entry in initial] == [item.id]
        assert initial[0].collection_completed_count == 0

        _add_all_original_materials(tmp_path, database, item, attachments)
        before_merge = pending.list_pending_items()
        assert len(before_merge) == 1
        assert before_merge[0].collection_completed_count == 4
        assert before_merge[0].collection_required_count == 4
        assert before_merge[0].missing_collection_materials == ()
        assert before_merge[0].missing_submission_materials == ("合并支付截图",)

        PaymentScreenshotMergeService(
            database, StoragePathService(tmp_path / "archive")
        ).generate(item.id)
        assert pending.list_pending_items() == []

        merged = next(
            attachment
            for attachment in attachments.list_attachments(item.id)
            if attachment.is_derived
        )
        attachments.remove_attachment(merged.id)
        after_remove = pending.list_pending_items()
        assert [entry.item_id for entry in after_remove] == [item.id]
        assert after_remove[0].missing_submission_materials == ("合并支付截图",)
    finally:
        database.dispose()
