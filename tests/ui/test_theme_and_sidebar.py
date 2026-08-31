from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from reimbursement_manager.ui.windows import MainWindow
from reimbursement_manager.ui.windows.main_window import (
    ALL_ITEMS_PAGE_INDEX,
    BATCH_DETAIL_PAGE_INDEX,
    BATCH_LIST_PAGE_INDEX,
    ITEM_DETAIL_PAGE_INDEX,
    PAGE_TITLES,
    PENDING_MATERIALS_PAGE_INDEX,
)
from reimbursement_manager.ui.theme import IOS_LIGHT_TOKENS, load_stylesheet


def test_ios_light_theme_exposes_the_shared_design_tokens() -> None:
    assert IOS_LIGHT_TOKENS.app_background == "#F5F5F7"
    assert IOS_LIGHT_TOKENS.surface == "#FFFFFF"
    assert IOS_LIGHT_TOKENS.secondary_surface == "#F2F2F7"
    assert IOS_LIGHT_TOKENS.primary_text == "#1D1D1F"
    assert IOS_LIGHT_TOKENS.secondary_text == "#6E6E73"
    assert IOS_LIGHT_TOKENS.tertiary_text == "#8E8E93"
    assert IOS_LIGHT_TOKENS.accent == "#007AFF"
    assert IOS_LIGHT_TOKENS.success == "#34C759"
    assert IOS_LIGHT_TOKENS.warning == "#FF9F0A"
    assert IOS_LIGHT_TOKENS.danger == "#FF3B30"
    assert IOS_LIGHT_TOKENS.border == "#D2D2D7"
    assert IOS_LIGHT_TOKENS.selected_surface == "#E5F1FF"
    assert IOS_LIGHT_TOKENS.success_text == "#248A3D"
    assert IOS_LIGHT_TOKENS.warning_text == "#9A5B00"
    assert "@" not in load_stylesheet()


def test_main_window_uses_the_light_theme_and_sidebar_navigation() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert window.navigation.objectName() == "navigation"
        assert window.navigation.count() == len(PAGE_TITLES)
        assert window.navigation.iconSize().width() == 18
        assert window.navigation.currentRow() == 0
        assert window.navigation.item(0).isSelected()
        assert window.navigation.item(0).icon().isNull() is False
        assert window.management_group_title.text() == "管理"
        assert window.navigation.parentWidget().width() == 210
        assert "QListWidget#primaryNavigation::item:selected" in QApplication.instance().styleSheet()
        assert window.minimumWidth() == 1100
        assert window.minimumHeight() == 700
    finally:
        window.close()


def test_sidebar_groups_navigation_and_keeps_selected_page_in_sync() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert window.findChild(type(window.navigation), "navigation") is window.navigation
        assert window.navigation.count() == len(PAGE_TITLES)
        assert window.navigation.item(4).text() == "模板管理"
        assert window.navigation.item(5).text() == "设置"
        assert window.navigation.iconSize() == window.navigation._management_list.iconSize()

        window.show()
        application.processEvents()
        settings_item = window.navigation._management_list.item(1)
        QTest.mouseClick(
            window.navigation._management_list.viewport(),
            Qt.MouseButton.LeftButton,
            pos=window.navigation._management_list.visualItemRect(settings_item).center(),
        )
        assert window.navigation.item(5).isSelected()
        assert window.pages.currentIndex() == 5
    finally:
        window.close()


def test_home_navigation_survives_pending_materials_navigation_and_deferred_deletion() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.show()
        home_item = window.navigation.item(0)
        primary_navigation = window.navigation._primary_list

        def assert_home_is_stable() -> None:
            assert window.navigation.item(0) is home_item
            assert home_item is not None
            assert home_item.text() == "首页"
            assert window.navigation.isHidden() is False
            assert primary_navigation.isHidden() is False
            assert primary_navigation.parent() is window.navigation
            assert window.navigation.layout().indexOf(primary_navigation) >= 0
            assert primary_navigation.objectName() == "primaryNavigation"
            assert primary_navigation.dynamicPropertyNames() == [
                b"_q_styleSheetWidgetFont"
            ]
            assert window.navigation.dynamicPropertyNames() == [
                b"_q_styleSheetWidgetFont"
            ]
            assert primary_navigation.count() == 4
            assert window.navigation.count() == len(PAGE_TITLES)
            assert home_item.isHidden() is False
            assert primary_navigation.indexFromItem(home_item).isValid()
            assert primary_navigation.height() > 0
            assert primary_navigation.minimumHeight() > 0
            assert primary_navigation.maximumHeight() > 0
            assert primary_navigation.visualItemRect(home_item).height() > 0
            assert primary_navigation.visualItemRect(home_item).y() >= 0

        assert_home_is_stable()
        window.navigation.setCurrentRow(PENDING_MATERIALS_PAGE_INDEX)
        application.processEvents()
        assert window.pages.currentIndex() == PENDING_MATERIALS_PAGE_INDEX
        assert window.navigation.currentRow() == PENDING_MATERIALS_PAGE_INDEX
        assert primary_navigation.currentRow() == PENDING_MATERIALS_PAGE_INDEX
        assert home_item.isSelected() is False
        assert_home_is_stable()

        window.refresh_pending_materials()
        application.processEvents()
        assert_home_is_stable()

        for _ in range(10):
            window.navigation.setCurrentRow(0)
            assert home_item.isSelected()
            assert window.pages.currentIndex() == 0
            window.navigation.setCurrentRow(PENDING_MATERIALS_PAGE_INDEX)
            assert home_item.isSelected() is False
            assert window.pages.currentIndex() == PENDING_MATERIALS_PAGE_INDEX
            assert_home_is_stable()

        for _ in range(3):
            application.processEvents()
            application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert_home_is_stable()
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
        assert all(table.verticalHeader().defaultSectionSize() == 52 for table in tables)
        assert window.delete_item_button.objectName() == "dangerButton"
        assert "QDateEdit" in application.styleSheet()
        assert "QPushButton#dangerButton:disabled" in application.styleSheet()
    finally:
        window.close()
