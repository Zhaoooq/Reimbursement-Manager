"""R5 材料区与支付凭证区：层级、状态、扁平化与术语统一。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QWidget, QWidget

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Base
from reimbursement_manager.services import (
    AttachmentService,
    BatchService,
    CompletenessService,
    ItemService,
    StoragePathService,
    SubmissionReadinessService,
    TemplateService,
)
from reimbursement_manager.ui.theme import IOS_LIGHT_TOKENS
from reimbursement_manager.ui.windows import MainWindow
from reimbursement_manager.ui.windows.main_window import ITEM_DETAIL_PAGE_INDEX


def _photo(tmp_path: Path, name: str, tone: str) -> Path:
    path = tmp_path / name
    image = QImage(320, 200, QImage.Format.Format_RGB32)
    image.fill(QColor(tone))
    image.save(str(path), "PNG")
    return path


def _detail_window(
    tmp_path: Path, *, with_attachments: bool
) -> tuple[MainWindow, DatabaseManager, object]:
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    storage = StoragePathService(tmp_path / "archive")
    template = TemplateService(database).ensure_default_template()
    batch = BatchService(database).create_batch(name="2026年8月实验耗材")
    item_service = ItemService(database)
    attachment = AttachmentService(database, storage)
    item = item_service.create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W",
        total_amount_cents=18000,
    )
    if with_attachments:
        requirements = list(item.requirements)
        attachment.add_attachment(
            item_id=item.id,
            material_type_id=requirements[0].material_type_id,
            source_path=_photo(tmp_path, "a.png", "#8FA8C8"),
        )
        attachment.add_attachment(
            item_id=item.id,
            material_type_id=requirements[1].material_type_id,
            source_path=_photo(tmp_path, "b.png", "#A8C8A0"),
        )
    completeness = CompletenessService(database, storage)
    submission = SubmissionReadinessService(database, storage)
    window = MainWindow(
        batch_service=BatchService(database),
        item_service=item_service,
        completeness_service=completeness,
        attachment_service=attachment,
        submission_readiness_service=submission,
    )
    window._populate_item_detail(item.id)
    window.pages.setCurrentIndex(ITEM_DETAIL_PAGE_INDEX)
    QApplication.processEvents()
    return window, database, item


def _sections(window: MainWindow) -> list[QFrame]:
    return window.item_detail_materials.findChildren(QFrame, "materialSection")


def test_material_section_title_sits_one_step_below_the_page_section() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        stylesheet = application.styleSheet()
        material_rule = stylesheet.split("QLabel#materialSectionTitle {", 1)[1].split("}", 1)[0]
        page_rule = stylesheet.split("QLabel#sectionTitle,", 1)[1].split("}", 1)[0]

        assert f"font-size: {IOS_LIGHT_TOKENS.body_size}px" in material_rule
        assert f"font-size: {IOS_LIGHT_TOKENS.section_title_size}px" in page_rule
    finally:
        window.close()


def test_material_section_states_replace_the_zero_attachment_count(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    window, database, _item = _detail_window(tmp_path, with_attachments=False)
    try:
        section = _sections(window)[0]
        count = section.findChild(QLabel, "materialAttachmentCount")
        state = section.findChild(QLabel, "materialMissingState")

        assert count is not None and count.text() == "0 个附件"
        assert count.isVisibleTo(section) is False
        assert state is not None and state.text() == "缺少材料"
        assert state.isVisibleTo(section) is True
    finally:
        window.close()
        database.dispose()


def test_material_section_counts_attachments_and_marks_them_uploaded(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    window, database, _item = _detail_window(tmp_path, with_attachments=True)
    try:
        section = _sections(window)[0]
        count = section.findChild(QLabel, "materialAttachmentCount")

        assert count is not None
        assert count.text() == "1 个附件"
        assert count.property("uploaded") is True
        assert count.isVisibleTo(section) is True
        assert section.findChild(QLabel, "materialMissingState") is None
        assert section.findChild(QWidget, "attachmentGrid") is not None
    finally:
        window.close()
        database.dispose()


def test_attachment_actions_rank_open_folder_and_delete(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    window, database, _item = _detail_window(tmp_path, with_attachments=True)
    try:
        card = window.item_detail_materials.findChild(QFrame, "attachmentCard")
        assert card is not None
        actions = card.findChild(QWidget, "attachmentActions")
        assert actions is not None
        buttons = {button.text(): button for button in actions.findChildren(QPushButton)}

        assert buttons["打开"].objectName() == "attachmentTextAction"
        assert buttons["文件夹"].objectName() == "attachmentMutedAction"
        assert buttons["删除"].objectName() == "attachmentDangerAction"
    finally:
        window.close()
        database.dispose()


def test_payment_section_is_flat_and_uses_the_merged_term(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    window, database, _item = _detail_window(tmp_path, with_attachments=True)
    try:
        section = window.merged_payment_section
        labels = [label.text() for label in section.findChildren(QLabel)]

        # 术语统一：不再出现「最终支付截图」，结果槽位只保留一个名称。
        assert not [text for text in labels if "最终支付截图" in text]
        assert labels.count("合并支付截图") == 1
        assert section.findChild(QLabel, "mergedPaymentResultTitle").text() == "合并支付截图"

        # 三个槽位直接落在分区白底上，来源槽位里不再套附件卡。
        for object_name in ("mergeOrderSource", "mergePaymentSource", "mergedPaymentResult"):
            slot = section.findChild(QFrame, object_name)
            assert slot is not None
            assert slot.parentWidget() is section
        assert section.findChild(QFrame, "mergeOrderSource").findChild(
            QFrame, "attachmentCard"
        ) is None
    finally:
        window.close()
        database.dispose()


def test_payment_section_placeholders_cover_empty_and_partial_states(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    window, database, _item = _detail_window(tmp_path, with_attachments=False)
    try:
        section = window.merged_payment_section
        placeholders = section.findChildren(QLabel, "mergedPaymentPlaceholder")
        assert len(placeholders) == 3
        assert all(placeholder.text() == "待上传" for placeholder in placeholders)

        labels = [label.text() for label in section.findChildren(QLabel)]
        assert "缺少订单截图" in labels
        assert "缺少支付截图" in labels
        assert "尚未生成合并支付截图" in labels
        assert window.generate_merged_payment_screenshot_button.isEnabled() is False
    finally:
        window.close()
        database.dispose()
