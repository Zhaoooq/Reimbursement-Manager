"""R4 详情页层级：金额格式、标题行归组、批次详情单一主操作。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Base
from reimbursement_manager.services import (
    AttachmentService,
    BatchService,
    CompletenessService,
    DashboardService,
    ItemService,
    PendingMaterialsService,
    StoragePathService,
    SubmissionReadinessService,
    TemplateService,
)
from reimbursement_manager.ui.windows import MainWindow
from reimbursement_manager.ui.windows.main_window import ITEM_DETAIL_PAGE_INDEX


def _window_with_item(
    tmp_path: Path, *, amount_cents: int
) -> tuple[MainWindow, DatabaseManager, object]:
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    storage = StoragePathService(tmp_path / "archive")
    template = TemplateService(database).ensure_default_template()
    batch = BatchService(database).create_batch(name="2026年8月实验耗材")
    item_service = ItemService(database)
    item = item_service.create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W",
        total_amount_cents=amount_cents,
        platform="淘宝",
        merchant="电子器材店",
        order_number="ORDER-20260820-0001",
    )
    completeness = CompletenessService(database, storage)
    submission = SubmissionReadinessService(database, storage)
    window = MainWindow(
        DashboardService(database, completeness, submission),
        batch_service=BatchService(database, storage),
        item_service=item_service,
        completeness_service=completeness,
        attachment_service=AttachmentService(database, storage),
        submission_readiness_service=submission,
        pending_materials_service=PendingMaterialsService(
            item_service, completeness, submission
        ),
    )
    window.show()
    window._populate_item_detail(item.id)
    window.pages.setCurrentIndex(ITEM_DETAIL_PAGE_INDEX)
    QApplication.processEvents()
    return window, database, item


def test_item_amount_uses_thousands_separators_and_plain_text_colour(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    window, database, _item = _window_with_item(tmp_path, amount_cents=1234560)
    try:
        assert window.item_detail_amount_label.text() == "¥12,345.60"

        stylesheet = QApplication.instance().styleSheet()
        amount_rule = stylesheet.split("QLabel#itemDetailAmount {", 1)[1].split("}", 1)[0]
        # 金额是数据，不是链接：不能再用 accent 蓝。
        assert "color: #1D1D1F" in amount_rule
    finally:
        window.close()
        database.dispose()


def test_item_headline_groups_name_status_and_amount(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    window, database, _item = _window_with_item(tmp_path, amount_cents=18000)
    try:
        name = window.item_detail_name_label
        status = window.item_detail_status_label
        amount = window.item_detail_amount_label
        headline = name.parentWidget()

        assert headline is not None
        assert headline.objectName() == "itemDetailHeadline"
        assert status.parentWidget() is headline
        assert amount.parentWidget() is headline
        assert status.text() in {"待补材料", "可提交", "待生成凭证"}

        # 基本信息不再用卡片包住，而是一行文本。
        metadata_parent = window.item_detail_primary_metadata_label.parentWidget()
        assert metadata_parent is not None
        assert metadata_parent.objectName() != "itemDetailMetadata"
    finally:
        window.close()
        database.dispose()


def test_item_status_strip_holds_both_blocks_and_the_actions(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    window, database, _item = _window_with_item(tmp_path, amount_cents=18000)
    try:
        strip = window.item_detail_workflow_button.parentWidget()
        assert strip is not None
        assert strip.objectName() == "itemDetailStatusStrip"

        blocks = strip.findChildren(QFrame, "itemDetailStatusBlock")
        assert len(blocks) == 2
        assert len(strip.findChildren(QFrame, "itemDetailStatusDivider")) == 1

        # 两个进度块和两个动作都在同一个视觉单元内。
        assert window.export_submission_materials_button.parentWidget() is strip
        assert window.item_detail_collection_progress.parentWidget() in blocks
        assert window.item_detail_submission_progress.parentWidget() in blocks
    finally:
        window.close()
        database.dispose()


def test_batch_detail_keeps_a_single_solid_primary_action(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    template = TemplateService(database).ensure_default_template()
    batch_service = BatchService(database)
    batch = batch_service.create_batch(name="实验耗材")
    ItemService(database).create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=1, name="树莓派"
    )
    storage = StoragePathService(tmp_path / "archive")
    window = MainWindow(
        batch_service=batch_service,
        item_service=ItemService(database),
        completeness_service=CompletenessService(database, storage),
    )
    try:
        window.show()
        window.navigation.setCurrentRow(1)
        application.processEvents()
        window.batch_table.cellClicked.emit(0, 0)
        application.processEvents()

        page = window.pages.currentWidget()
        solid_primaries = [
            button
            for button in page.findChildren(QPushButton)
            if button.objectName() == "primaryButton"
            and button.isVisibleTo(page)
            and button.property("quiet") != "true"
        ]
        assert solid_primaries == [window.new_item_button]

        # 工作流按钮仍然存在、仍然可点，只是降为强调色而非实心。
        assert window.batch_mark_submitted_button.objectName() == "primaryButton"
        assert window.batch_mark_submitted_button.property("quiet") == "true"
        assert window.batch_mark_submitted_button.isHidden() is False
        assert window.batch_mark_submitted_button.text() == "标记批次已提交"
    finally:
        window.close()
        database.dispose()
