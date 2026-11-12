"""R6 表格页：待补材料的换行/行高/术语，所有物品的列宽与省略。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication, QLabel

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Base
from reimbursement_manager.services import (
    AttachmentService,
    BatchService,
    CompletenessService,
    ItemService,
    PendingMaterialsService,
    StoragePathService,
    SubmissionReadinessService,
    TemplateService,
)
from reimbursement_manager.ui.windows import MainWindow
from reimbursement_manager.ui.windows.main_window import (
    ALL_ITEMS_PAGE_INDEX,
    PENDING_MATERIALS_PAGE_INDEX,
)

LONG_BATCH = "2026年8月北京航空航天大学国际创新研究院纳米颗粒检测课题组实验耗材采购"
LONG_NAME = "树莓派 Zero 2 W 及配套散热片、电源适配器、MicroSD 卡整套采购"


def _window(tmp_path: Path) -> tuple[MainWindow, DatabaseManager, object]:
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    storage = StoragePathService(tmp_path / "archive")
    template = TemplateService(database).ensure_default_template()
    batch = BatchService(database).create_batch(name=LONG_BATCH)
    item_service = ItemService(database)
    item = item_service.create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name=LONG_NAME,
        total_amount_cents=1234560,
        platform="淘宝",
        merchant="电子器材店",
        order_number="ORDER-20260820-0001",
    )
    completeness = CompletenessService(database, storage)
    submission = SubmissionReadinessService(database, storage)
    window = MainWindow(
        batch_service=BatchService(database),
        item_service=item_service,
        completeness_service=completeness,
        attachment_service=AttachmentService(database, storage),
        submission_readiness_service=submission,
        pending_materials_service=PendingMaterialsService(
            item_service, completeness, submission
        ),
    )
    return window, database, item


def _settle(application: QApplication, rounds: int = 4) -> None:
    for _ in range(rounds):
        application.processEvents()


def _open(window: MainWindow, application: QApplication, page: int) -> None:
    """Show first, then size: Qt lays pages out at the pre-show geometry."""
    window.show()
    _settle(application, 6)
    window.resize(1100, 700)
    _settle(application, 6)
    window.navigation.setCurrentRow(page)
    _settle(application, 6)


def test_pending_missing_text_wraps_instead_of_being_cut(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    window, database, _item = _window(tmp_path)
    try:
        _open(window, application, PENDING_MATERIALS_PAGE_INDEX)

        table = window.pending_materials_table
        assert table.wordWrap() is True

        missing_cells = [
            table.item(row, column).text()
            for row in range(table.rowCount())
            for column in (3, 5)
        ]
        assert any(text.count("、") >= 2 for text in missing_cells)

        # 文案完整：单元格里保留全部材料名，换行由行高承担。
        assert any("支付截图" in text and "订单截图" in text for text in missing_cells)

        # 行高至少能容下按实际列宽测量出的整段文字，否则会被截断。
        metrics = table.fontMetrics()
        flags = int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft)
        for row in range(table.rowCount()):
            for column in (3, 5):
                cell = table.item(row, column)
                inner = table.columnWidth(column) - 26
                needed = metrics.boundingRect(
                    QRect(0, 0, inner, 10000), flags, cell.text()
                ).height()
                assert table.rowHeight(row) >= needed
    finally:
        window.close()
        database.dispose()


def test_pending_page_uses_the_merged_payment_term(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    window, database, _item = _window(tmp_path)
    try:
        _open(window, application, PENDING_MATERIALS_PAGE_INDEX)

        table = window.pending_materials_table
        texts = [
            table.item(row, column).text()
            for row in range(table.rowCount())
            for column in (3, 5)
        ]
        assert not [text for text in texts if "最终支付截图" in text]
        assert any("合并支付截图" in text for text in texts)
    finally:
        window.close()
        database.dispose()


def test_pending_name_column_widens_on_large_windows(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    window, database, _item = _window(tmp_path)
    try:
        _open(window, application, PENDING_MATERIALS_PAGE_INDEX)
        narrow = window.pending_materials_table.columnWidth(0)
        assert narrow >= 180

        window.resize(1440, 900)
        _settle(application, rounds=10)
        wide = window.pending_materials_table.columnWidth(0)
        assert wide > narrow
        viewport = window.pending_materials_table.viewport().width()
        assert (
            sum(
                window.pending_materials_table.columnWidth(column)
                for column in range(6)
            )
            == viewport
        )
    finally:
        window.close()
        database.dispose()


def test_pending_name_column_keeps_a_manual_width(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    window, database, _item = _window(tmp_path)
    try:
        _open(window, application, PENDING_MATERIALS_PAGE_INDEX)

        header = window.pending_materials_table.horizontalHeader()
        window.pending_materials_table.setColumnWidth(0, 260)
        header.sectionResized.emit(0, 200, 260)  # 模拟用户拖拽
        _settle(application)

        window.resize(1440, 900)
        _settle(application, rounds=10)
        assert window.pending_materials_table.columnWidth(0) == 260
    finally:
        window.close()
        database.dispose()


def test_all_items_columns_fit_their_content(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    window, database, _item = _window(tmp_path)
    try:
        _open(window, application, ALL_ITEMS_PAGE_INDEX)

        table = window.all_items_table
        header = table.horizontalHeader()
        viewport = table.viewport().width()
        # 物品名称与缺失材料是主信息，两者平分剩余宽度，不再被挤成 20px。
        assert header.sectionSize(0) > 100
        assert header.sectionSize(0) == header.sectionSize(6)
        assert (
            sum(header.sectionSize(column) for column in range(8)) == viewport
        )

        # 金额（含千分位）与状态徽标都必须完整显示。
        assert table.item(0, 2).text() == "¥12,345.60"
        badge = table.cellWidget(0, 7)
        assert isinstance(badge, QLabel)
        assert header.sectionSize(7) >= badge.sizeHint().width() + 12

        for column in range(1, 8):
            if column in (2, 7):
                continue
            assert header.sectionSize(column) > 0
    finally:
        window.close()
        database.dispose()


def test_all_items_keeps_tooltips_for_elided_text(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    window, database, _item = _window(tmp_path)
    try:
        _open(window, application, ALL_ITEMS_PAGE_INDEX)

        table = window.all_items_table
        assert table.item(0, 0).toolTip() == LONG_NAME
        assert table.item(0, 1).toolTip() == LONG_BATCH
        assert table.item(0, 4).toolTip() == "淘宝"
        assert table.item(0, 6).toolTip()
    finally:
        window.close()
        database.dispose()
