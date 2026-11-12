"""R1 UI 一致性：待补材料列宽、详情页导航同步、批次删除可用性。"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Base
from reimbursement_manager.services import (
    BatchListEntry,
    BatchService,
    CompletenessService,
    ItemService,
    PendingMaterialsService,
    StoragePathService,
    SubmissionReadinessService,
    TemplateService,
)
from reimbursement_manager.ui.windows import MainWindow, main_window
from reimbursement_manager.ui.windows.main_window import (
    _PENDING_NAME_COLUMN_MIN_WIDTH,
    BATCH_DETAIL_PAGE_INDEX,
    BATCH_LIST_PAGE_INDEX,
    ITEM_DETAIL_PAGE_INDEX,
    PENDING_MATERIALS_PAGE_INDEX,
)


def _build_window(database: DatabaseManager, storage: StoragePathService) -> MainWindow:
    completeness = CompletenessService(database, storage)
    submission = SubmissionReadinessService(database, storage)
    item_service = ItemService(database)
    return MainWindow(
        batch_service=BatchService(database),
        item_service=item_service,
        completeness_service=completeness,
        submission_readiness_service=submission,
        pending_materials_service=PendingMaterialsService(
            item_service, completeness, submission
        ),
    )


def _click_navigation_row(window: MainWindow, row: int) -> None:
    """Click a sidebar row the way a user would, including the selected one."""
    navigation = window.navigation
    is_primary = row < navigation._primary_list.count()
    source = navigation._primary_list if is_primary else navigation._management_list
    local_row = row if is_primary else row - navigation._primary_list.count()
    item = source.item(local_row)
    assert item is not None
    QTest.mouseClick(
        source.viewport(),
        Qt.MouseButton.LeftButton,
        pos=source.visualItemRect(item).center(),
    )
    QApplication.processEvents()


def test_pending_materials_keeps_the_item_name_column_readable(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    storage = StoragePathService(tmp_path / "archive")
    template = TemplateService(database).ensure_default_template()
    batch = BatchService(database).create_batch(name="实验耗材")
    ItemService(database).create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W",
    )
    window = _build_window(database, storage)
    try:
        window.show()
        window.navigation.setCurrentRow(PENDING_MATERIALS_PAGE_INDEX)
        QApplication.processEvents()

        table = window.pending_materials_table
        header = table.horizontalHeader()
        assert table.rowCount() == 1
        assert header.sectionSize(0) >= _PENDING_NAME_COLUMN_MIN_WIDTH
        # The visible columns must fill the viewport exactly: nothing is
        # squeezed away and no horizontal scrolling is needed at this size.
        assert sum(header.sectionSize(i) for i in range(table.columnCount())) == (
            table.viewport().width()
        )
        assert table.horizontalScrollBar().maximum() == 0
    finally:
        window.close()
        database.dispose()


def test_item_name_column_survives_a_manual_shrink_attempt(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    window = _build_window(database, StoragePathService(tmp_path / "archive"))
    try:
        window.show()
        window.navigation.setCurrentRow(PENDING_MATERIALS_PAGE_INDEX)
        QApplication.processEvents()

        window.pending_materials_table.setColumnWidth(0, 40)
        QApplication.processEvents()

        assert (
            window.pending_materials_table.horizontalHeader().sectionSize(0)
            >= _PENDING_NAME_COLUMN_MIN_WIDTH
        )
    finally:
        window.close()
        database.dispose()


def test_item_detail_from_pending_materials_keeps_sidebar_and_back_link_in_sync(
    tmp_path: Path,
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    template = TemplateService(database).ensure_default_template()
    batch = BatchService(database).create_batch(name="实验耗材")
    item = ItemService(database).create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W",
    )
    window = _build_window(database, StoragePathService(tmp_path / "archive"))
    try:
        window.show()
        window.navigation.setCurrentRow(PENDING_MATERIALS_PAGE_INDEX)
        QApplication.processEvents()

        window.pending_materials_table.cellClicked.emit(0, 0)
        QApplication.processEvents()

        assert window.pages.currentIndex() == ITEM_DETAIL_PAGE_INDEX
        assert window.item_detail_name_label.text() == item.name
        assert window.navigation.currentRow() == PENDING_MATERIALS_PAGE_INDEX
        assert window.back_to_all_items_button.text() == "← 待补材料"

        # Re-clicking the highlighted section must leave the detail page.
        _click_navigation_row(window, PENDING_MATERIALS_PAGE_INDEX)
        assert window.pages.currentIndex() == PENDING_MATERIALS_PAGE_INDEX
    finally:
        window.close()
        database.dispose()


def test_item_detail_back_link_names_the_batch_list_when_opened_from_a_batch(
    tmp_path: Path,
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    storage = StoragePathService(tmp_path / "archive")
    template = TemplateService(database).ensure_default_template()
    batch = BatchService(database).create_batch(name="实验耗材")
    ItemService(database).create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W",
    )
    window = _build_window(database, storage)
    try:
        window.show()
        window.navigation.setCurrentRow(BATCH_LIST_PAGE_INDEX)
        QApplication.processEvents()
        window.batch_table.cellClicked.emit(0, 0)
        QApplication.processEvents()
        window.batch_detail_table.cellClicked.emit(0, 0)
        QApplication.processEvents()

        assert window.pages.currentIndex() == ITEM_DETAIL_PAGE_INDEX
        assert window.navigation.currentRow() == BATCH_LIST_PAGE_INDEX
        assert window.back_to_all_items_button.text() == "← 报销批次"
    finally:
        window.close()
        database.dispose()


def _batch_detail_window(
    tmp_path: Path, *, filled_items: int, empty_batches: int
) -> tuple[MainWindow, DatabaseManager, BatchService, object | None, object | None]:
    """Build a window whose batch list holds the requested mix of batches."""
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    template = TemplateService(database).ensure_default_template()
    batch_service = BatchService(database)
    filled = None
    if filled_items:
        filled = batch_service.create_batch(name="有物品的批次")
        for sequence in range(1, filled_items + 1):
            ItemService(database).create_item(
                batch_id=filled.id,
                template_id=template.id,
                sequence_number=sequence,
                name=f"物品 {sequence}",
            )
    empty = None
    for index in range(empty_batches):
        empty = batch_service.create_batch(name=f"空批次{index or ''}")
    window = _build_window(database, StoragePathService(tmp_path / "archive"))
    window.show()
    window.navigation.setCurrentRow(BATCH_LIST_PAGE_INDEX)
    QApplication.processEvents()
    return window, database, batch_service, filled, empty


def _open_batch_row(window: MainWindow, batch_name: str) -> None:
    for row in range(window.batch_table.rowCount()):
        if window.batch_table.item(row, 0).text() == batch_name:
            window.batch_table.cellClicked.emit(row, 0)
            QApplication.processEvents()
            return
    raise AssertionError(f"batch row not found: {batch_name}")


def test_batch_delete_button_disabled_with_reason_when_batch_has_items(
    tmp_path: Path,
) -> None:
    """item_count > 0: 按钮禁用，并给出与业务规则一致的原因。"""
    application = QApplication.instance() or QApplication([])
    del application
    window, database, _service, filled, _empty = _batch_detail_window(
        tmp_path, filled_items=2, empty_batches=0
    )
    try:
        _open_batch_row(window, filled.name)

        assert window.delete_batch_button.isEnabled() is False
        assert window.batch_delete_hint_label.text() == (
            "该批次仍包含 2 个物品，需先删除物品后才能删除批次。"
        )
        assert window.delete_batch_button.toolTip() == (
            window.batch_delete_hint_label.text()
        )
    finally:
        window.close()
        database.dispose()


def test_batch_delete_button_enabled_for_an_empty_batch(tmp_path: Path) -> None:
    """item_count == 0 且 Service 可用：按钮启用并说明后果。"""
    application = QApplication.instance() or QApplication([])
    del application
    window, database, _service, _filled, empty = _batch_detail_window(
        tmp_path, filled_items=0, empty_batches=1
    )
    try:
        _open_batch_row(window, empty.name)

        assert window.delete_batch_button.isEnabled() is True
        assert window.batch_delete_hint_label.text() == (
            "该批次没有物品，删除后不可恢复。"
        )
        assert window.delete_batch_button.toolTip() == (
            window.batch_delete_hint_label.text()
        )
    finally:
        window.close()
        database.dispose()


def test_batch_delete_stays_disabled_without_a_batch_service(tmp_path: Path) -> None:
    """Service 不可用：保持禁用，说明原因，且不抛异常。"""
    application = QApplication.instance() or QApplication([])
    del application
    window = MainWindow()
    try:
        entry = BatchListEntry(
            id=1,
            name="无服务批次",
            created_at=datetime(2026, 8, 1),
            item_count=0,
            total_amount_cents=0,
        )

        window._update_batch_delete_action(entry)

        assert window.delete_batch_button.isEnabled() is False
        assert window.batch_delete_hint_label.text() == "当前无法删除批次。"
        assert window.delete_batch_button.toolTip() == "当前无法删除批次。"

        # A disabled button must stay inert instead of reaching the service.
        window.delete_batch_button.click()
        assert window.delete_batch_button.isEnabled() is False
        # The delete handler itself must also bail out quietly without a service.
        window._delete_current_batch()
        assert window.delete_batch_button.isEnabled() is False
    finally:
        window.close()


def test_enabled_batch_delete_confirms_then_removes_the_batch(
    tmp_path: Path, monkeypatch
) -> None:
    """启用状态下：二次确认 → 调用 Service → 回到批次列表。"""
    application = QApplication.instance() or QApplication([])
    del application
    window, database, batch_service, _filled, empty = _batch_detail_window(
        tmp_path, filled_items=0, empty_batches=1
    )
    confirmations: list[str] = []

    def record_question(_parent, title, text, *_args, **_kwargs):
        confirmations.append(title)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(main_window.QMessageBox, "question", record_question)
    try:
        _open_batch_row(window, empty.name)
        assert window.delete_batch_button.isEnabled() is True

        window.delete_batch_button.click()
        QApplication.processEvents()

        assert confirmations == ["删除批次"]
        assert [batch.name for batch in batch_service.list_batches()] == []
        assert window.pages.currentIndex() == BATCH_LIST_PAGE_INDEX
        assert window.navigation.currentRow() == BATCH_LIST_PAGE_INDEX
        assert window.batch_table.rowCount() == 0
    finally:
        window.close()
        database.dispose()


def test_batch_delete_cancel_keeps_the_batch(tmp_path: Path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    window, database, batch_service, _filled, empty = _batch_detail_window(
        tmp_path, filled_items=0, empty_batches=1
    )
    monkeypatch.setattr(
        main_window.QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )
    try:
        _open_batch_row(window, empty.name)
        window.delete_batch_button.click()
        QApplication.processEvents()

        assert [batch.name for batch in batch_service.list_batches()] == [empty.name]
        assert window.pages.currentIndex() == BATCH_DETAIL_PAGE_INDEX
    finally:
        window.close()
        database.dispose()
