"""合并支付截图：凭证区只做预览，材料卡片是唯一的删除入口。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Base
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
from reimbursement_manager.ui.windows import MainWindow
from reimbursement_manager.ui.windows import main_window


def _detail_window(
    tmp_path: Path,
) -> tuple[MainWindow, DatabaseManager, AttachmentService, PaymentScreenshotMergeService, int]:
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch = BatchService(database).create_batch(name="合并支付截图")
    template = TemplateService(database).ensure_default_template()
    item_service = ItemService(database)
    item = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=1, name="树莓派"
    )
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    with database.transaction() as session:
        material_types = MaterialTypeRepository(session)
        ids = {
            code: material_types.get_by_code(code).id  # type: ignore[union-attr]
            for code in ("order_screenshot", "payment_screenshot")
        }

    for code, tone in (("order_screenshot", "#8FA8C8"), ("payment_screenshot", "#A8C8A0")):
        source = tmp_path / f"{code}.png"
        image = QImage(40, 24, QImage.Format.Format_RGB32)
        image.fill(QColor(tone))
        assert image.save(str(source), "PNG")
        attachments.add_attachment(
            item_id=item.id, material_type_id=ids[code], source_path=source
        )

    merge_service = PaymentScreenshotMergeService(database, storage)
    window = MainWindow(
        batch_service=BatchService(database),
        item_service=item_service,
        completeness_service=CompletenessService(database, storage),
        attachment_service=attachments,
        payment_screenshot_merge_service=merge_service,
        submission_readiness_service=SubmissionReadinessService(database, storage),
    )
    window._populate_item_detail(item.id)
    window.pages.setCurrentIndex(7)
    QApplication.processEvents()
    return window, database, attachments, merge_service, item.id


def _derived_card(window: MainWindow) -> QFrame:
    return next(
        card
        for card in window.item_detail_materials.findChildren(QFrame, "attachmentCard")
        if "合并提交文件"
        in card.findChild(QLabel, "attachmentFilename").toolTip()
    )


def _button_texts(widget: QWidget) -> list[str]:
    actions = widget.findChild(QWidget, "attachmentActions")
    assert actions is not None
    return [button.text() for button in actions.findChildren(QPushButton)]


def test_merged_preview_offers_open_and_folder_but_no_delete(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    window, database, attachments, _merge, item_id = _detail_window(tmp_path)
    try:
        window.generate_merged_payment_screenshot_button.click()
        application.processEvents()

        preview = window.merged_payment_section.findChild(QFrame, "attachmentCard")
        assert preview is not None
        assert _button_texts(preview) == ["打开", "文件夹"]
        assert not [
            button
            for button in window.merged_payment_section.findChildren(QPushButton)
            if button.text() == "删除"
        ]

        derived = [entry for entry in attachments.list_attachments(item_id) if entry.is_derived]
        assert len(derived) == 1
        # 预览与材料卡指向同一条附件记录。
        material_card = _derived_card(window)
        assert preview.findChild(QLabel, "attachmentFilename").toolTip() == (
            material_card.findChild(QLabel, "attachmentFilename").toolTip()
        )
    finally:
        window.close()
        database.dispose()


def test_material_card_keeps_delete_as_the_only_entry(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    window, database, _attachments, _merge, _item_id = _detail_window(tmp_path)
    try:
        window.generate_merged_payment_screenshot_button.click()
        application.processEvents()

        assert _button_texts(_derived_card(window)) == ["打开", "文件夹", "删除"]
    finally:
        window.close()
        database.dispose()


def test_deleting_from_the_material_card_clears_the_preview(tmp_path: Path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    window, database, attachments, _merge, item_id = _detail_window(tmp_path)
    monkeypatch.setattr(
        main_window.QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )
    try:
        window.generate_merged_payment_screenshot_button.click()
        application.processEvents()
        assert window.merged_payment_section.findChild(QFrame, "attachmentCard") is not None

        card = _derived_card(window)
        next(
            button
            for button in card.findChild(QWidget, "attachmentActions").findChildren(QPushButton)
            if button.text() == "删除"
        ).click()
        application.processEvents()

        assert not [entry for entry in attachments.list_attachments(item_id) if entry.is_derived]
        # 凭证区不留失效引用：预览消失，回到"尚未生成"。
        assert window.merged_payment_section.findChild(QFrame, "attachmentCard") is None
        empty = window.merged_payment_section.findChild(QLabel, "mergedPaymentEmpty")
        assert empty is not None and empty.text() == "尚未生成合并支付截图"
        assert window.generate_merged_payment_screenshot_button.text() == "生成支付截图"
        assert window.generate_merged_payment_screenshot_button.isEnabled() is True
    finally:
        window.close()
        database.dispose()


def test_open_folder_and_regenerate_keep_working(tmp_path: Path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    window, database, attachments, _merge, item_id = _detail_window(tmp_path)
    opened: list[int] = []
    folders: list[int] = []
    monkeypatch.setattr(window, "_open_attachment", lambda attachment_id: opened.append(attachment_id))
    monkeypatch.setattr(
        window, "_open_attachment_folder", lambda attachment_id: folders.append(attachment_id)
    )
    try:
        window.generate_merged_payment_screenshot_button.click()
        application.processEvents()
        preview = window.merged_payment_section.findChild(QFrame, "attachmentCard")
        buttons = {
            button.text(): button
            for button in preview.findChild(QWidget, "attachmentActions").findChildren(QPushButton)
        }
        buttons["打开"].click()
        buttons["文件夹"].click()
        assert len(opened) == 1 and len(folders) == 1

        derived = [
            entry
            for entry in attachments.list_attachments(item_id)
            if entry.is_derived and entry.id == opened[0]
        ]
        assert len(derived) == 1

        assert window.generate_merged_payment_screenshot_button.text() == "重新生成"
        window.generate_merged_payment_screenshot_button.click()
        application.processEvents()
        assert len([e for e in attachments.list_attachments(item_id) if e.is_derived]) == 2
    finally:
        window.close()
        database.dispose()
