"""R7 设置页、模板管理与对话框：尺寸约束、主次按钮、删除确认。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
)

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Base
from reimbursement_manager.services import TemplateService
from reimbursement_manager.ui.theme import apply_light_theme
from reimbursement_manager.ui.windows import MainWindow
from reimbursement_manager.ui.windows import main_window
from reimbursement_manager.ui.windows.main_window import (
    NewBatchDialog,
    NewItemDialog,
    NewMaterialTypeDialog,
)

TEMPLATE_PAGE_INDEX = 4
SETTINGS_PAGE_INDEX = 5


def _window_with_templates(tmp_path: Path) -> tuple[MainWindow, DatabaseManager, TemplateService]:
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    service = TemplateService(database)
    service.ensure_default_template()
    window = MainWindow(template_service=service)
    window.resize(1100, 700)
    window.show()
    QApplication.processEvents()
    return window, database, service


def test_new_item_dialog_fits_inside_the_minimum_window() -> None:
    application = QApplication.instance() or QApplication([])
    apply_light_theme(application)
    parent = MainWindow()
    parent.resize(1100, 700)
    parent.show()
    application.processEvents()
    dialog = NewItemDialog("2026年8月实验耗材", [], parent)
    try:
        assert dialog.minimumWidth() == 560
        dialog.show()
        application.processEvents()

        assert dialog.height() <= 700
        body = dialog.findChild(QScrollArea, "dialogBodyScroll")
        assert body is not None
        # 滚动体高度被限制在窗口预算内：装不下时滚动，而不是把对话框撑出窗口。
        assert body.maximumHeight() <= 501
        assert body.height() == body.maximumHeight()
    finally:
        dialog.close()
        parent.close()


def test_dialog_buttons_stay_outside_the_scrolling_body() -> None:
    application = QApplication.instance() or QApplication([])
    apply_light_theme(application)
    dialog = NewBatchDialog()
    try:
        buttons = dialog.buttons
        body = dialog.findChild(QScrollArea, "dialogBodyScroll")
        assert body is not None
        assert buttons.parentWidget() is not body.widget()
        assert buttons.parentWidget() is dialog

        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        assert save_button is not None
        assert save_button.objectName() == "primaryButton"
        assert save_button.text() == "创建批次"
    finally:
        dialog.close()


def test_every_form_dialog_keeps_labels_on_the_same_row() -> None:
    application = QApplication.instance() or QApplication([])
    apply_light_theme(application)
    dialogs = [NewBatchDialog(), NewMaterialTypeDialog(), NewItemDialog("批次", [])]
    try:
        for dialog in dialogs:
            dialog.show()
            application.processEvents()
            body = dialog.findChild(QScrollArea, "dialogBodyScroll")
            assert body is not None
            forms = [
                layout
                for layout in body.widget().findChildren(main_window.QFormLayout)
            ]
            assert forms, "表单应当放在滚动体内"
            for form in forms:
                assert (
                    form.rowWrapPolicy()
                    == main_window.QFormLayout.RowWrapPolicy.DontWrapRows
                )
            assert dialog.height() <= 700
    finally:
        for dialog in dialogs:
            dialog.close()


def test_template_row_exposes_edit_and_delete(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    window, database, _service = _window_with_templates(tmp_path)
    try:
        window.navigation.setCurrentRow(TEMPLATE_PAGE_INDEX)
        application.processEvents()

        actions = window.template_table.cellWidget(0, 2)
        assert actions is not None
        edit = actions.findChild(QPushButton, "templateEditAction")
        delete = actions.findChild(QPushButton, "templateDeleteAction")
        assert edit is not None and edit.text() == "编辑"
        assert delete is not None and delete.text() == "删除"
        assert window.template_table.horizontalHeaderItem(2).text() == "操作"
        assert window.template_table.item(0, 0).toolTip()
    finally:
        window.close()
        database.dispose()


def test_deleting_a_template_asks_first_then_removes_the_row(tmp_path: Path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    window, database, service = _window_with_templates(tmp_path)
    asked: list[str] = []
    try:
        window.navigation.setCurrentRow(TEMPLATE_PAGE_INDEX)
        application.processEvents()

        monkeypatch.setattr(
            main_window.QMessageBox,
            "question",
            lambda _parent, _title, text, *_args: (
                asked.append(text) or QMessageBox.StandardButton.No
            ),
        )
        actions = window.template_table.cellWidget(0, 2)
        actions.findChild(QPushButton, "templateDeleteAction").click()
        application.processEvents()
        assert asked and "确定删除模板" in asked[0]
        assert window.template_table.rowCount() == 1

        monkeypatch.setattr(
            main_window.QMessageBox,
            "question",
            lambda *_args: QMessageBox.StandardButton.Yes,
        )
        window.template_table.cellWidget(0, 2).findChild(
            QPushButton, "templateDeleteAction"
        ).click()
        application.processEvents()

        assert service.list_templates() == []
        assert window.template_table.isHidden() is True
        assert window.template_empty_state.isHidden() is False
    finally:
        window.close()
        database.dispose()


def test_settings_restore_section_is_the_last_danger_zone(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    window = MainWindow(template_service=TemplateService(database))
    try:
        window.navigation.setCurrentRow(SETTINGS_PAGE_INDEX)
        application.processEvents()

        danger = window.findChild(QFrame, "settingsDangerSurface")
        assert danger is not None
        title = danger.findChild(QLabel, "dangerZoneTitle")
        assert title is not None and title.text() == "恢复数据库"

        # 危险区排在"应用"分区之后。
        page = danger.parentWidget()
        assert page is not None
        sections = [
            child
            for child in page.findChildren(QFrame)
            if child.objectName() in {"settingsGroupSurface", "settingsDangerSurface"}
        ]
        assert sections[0].objectName() == "settingsGroupSurface"
        assert sections[-1] is danger
    finally:
        window.close()
        database.dispose()
