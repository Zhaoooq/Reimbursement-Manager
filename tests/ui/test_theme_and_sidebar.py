from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from reimbursement_manager.ui.windows import MainWindow
from reimbursement_manager.ui.windows.main_window import PAGE_TITLES


def test_main_window_uses_the_light_theme_and_sidebar_navigation() -> None:
    application = QApplication.instance() or QApplication([])
    del application
    window = MainWindow()
    try:
        assert window.navigation.objectName() == "navigation"
        assert window.navigation.count() == len(PAGE_TITLES)
        assert window.navigation.iconSize().width() == 18
        assert window.navigation.currentRow() == 0
        assert window.navigation.item(0).isSelected()
        assert window.navigation.item(0).icon().isNull() is False
        assert "QListWidget#navigation::item:selected" in QApplication.instance().styleSheet()
        assert window.minimumWidth() == 1100
        assert window.minimumHeight() == 700
    finally:
        window.close()


def test_shared_ui_conventions_cover_tables_inputs_and_danger_actions() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        tables = (
            window.batch_table,
            window.batch_detail_table,
            window.all_items_table,
            window.pending_materials_table,
            window.template_table,
        )
        assert all(table.alternatingRowColors() for table in tables)
        assert all(table.verticalHeader().defaultSectionSize() == 42 for table in tables)
        assert window.delete_item_button.objectName() == "dangerButton"
        assert "QDateEdit" in application.styleSheet()
        assert "QPushButton#dangerButton:disabled" in application.styleSheet()
    finally:
        window.close()
