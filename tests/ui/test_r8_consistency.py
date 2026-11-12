"""R8 收口：间距网格、危险区一致性、表格行高与图标几何。"""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtGui import QColor, QImage
from PySide6.QtCore import QPoint
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QTableWidget, QToolTip, QToolTip

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Base
from reimbursement_manager.services import (
    AttachmentService,
    BatchService,
    CompletenessService,
    ItemService,
    StoragePathService,
    TemplateService,
)
from reimbursement_manager.ui.theme import IOS_LIGHT_TOKENS
from reimbursement_manager.ui.windows import MainWindow

SETTINGS_PAGE_INDEX = 5
SPACING_GRID = {4, 8, 12, 16, 20, 24, 32}


def _window() -> tuple[MainWindow, DatabaseManager]:
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    window = MainWindow(template_service=TemplateService(database))
    window.resize(1100, 700)
    window.show()
    QApplication.processEvents()
    return window, database


def test_sidebar_uses_the_spacing_grid_and_token_width() -> None:
    application = QApplication.instance() or QApplication([])
    window, database = _window()
    try:
        sidebar = window.findChild(QFrame, "sidebar")
        assert sidebar is not None
        assert sidebar.width() == IOS_LIGHT_TOKENS.sidebar_width

        layout = sidebar.layout()
        margins = layout.contentsMargins()
        assert all(
            value in SPACING_GRID
            for value in (margins.left(), margins.top(), margins.right(), margins.bottom())
        )
        assert layout.spacing() in SPACING_GRID
    finally:
        window.close()
        database.dispose()


def test_every_table_row_height_comes_from_the_token() -> None:
    application = QApplication.instance() or QApplication([])
    window, database = _window()
    try:
        tables = window.findChildren(QTableWidget)
        assert len(tables) >= 5
        for table in tables:
            assert (
                table.verticalHeader().defaultSectionSize()
                == IOS_LIGHT_TOKENS.table_row_height
            )
    finally:
        window.close()
        database.dispose()


def test_both_danger_zones_share_one_title_style() -> None:
    application = QApplication.instance() or QApplication([])
    window, database = _window()
    try:
        window.navigation.setCurrentRow(SETTINGS_PAGE_INDEX)
        application.processEvents()
        settings_danger = window.findChild(QFrame, "settingsDangerSurface")
        item_danger = window.findChild(QFrame, "itemDetailDangerZone")

        assert settings_danger is not None and item_danger is not None
        for zone, expected_title in (
            (settings_danger, "恢复数据库"),
            (item_danger, "危险操作"),
        ):
            title = zone.findChild(QLabel, "dangerZoneTitle")
            assert title is not None
            assert title.text() == expected_title
        # 两个危险区不再各自定义标题样式。
        stylesheet = application.styleSheet()
        assert "settingsDangerTitle" not in stylesheet
        assert stylesheet.count("QLabel#dangerZoneTitle") == 1
    finally:
        window.close()
        database.dispose()


def test_navigation_icons_keep_one_stroke_vocabulary() -> None:
    icons = Path("src/reimbursement_manager/ui/resources/icons")
    files = sorted(icons.glob("nav-*.svg"))
    assert len(files) == 12

    for path in files:
        markup = path.read_text(encoding="utf-8")
        assert 'width="18" height="18" viewBox="0 0 18 18"' in markup, path.name
        assert 'stroke-width="1.5"' in markup, path.name

    # 报销批次图标内部只保留一条内容线：第二条会与底边粘连成实心块。
    for name in ("nav-batches.svg", "nav-batches-active.svg"):
        markup = (icons / name).read_text(encoding="utf-8")
        assert len(re.findall(r"<path ", markup)) == 2, name


def test_repopulating_the_detail_page_leaves_no_floating_widgets(tmp_path: Path) -> None:
    """重建页面时不能用「游离顶层窗口」的方式残留在屏幕上。"""
    application = QApplication.instance() or QApplication([])
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    storage = StoragePathService(tmp_path / "archive")
    template = TemplateService(database).ensure_default_template()
    batch = BatchService(database).create_batch(name="漂浮窗口")
    item_service = ItemService(database)
    attachment = AttachmentService(database, storage)
    item = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=1, name="路由器"
    )
    source = tmp_path / "shot.png"
    image = QImage(40, 24, QImage.Format.Format_RGB32)
    image.fill(QColor("#8FA8C8"))
    assert image.save(str(source), "PNG")
    attachment.add_attachment(
        item_id=item.id,
        material_type_id=item.requirements[0].material_type_id,
        source_path=source,
    )
    window = MainWindow(
        batch_service=BatchService(database),
        item_service=item_service,
        completeness_service=CompletenessService(database, storage),
        attachment_service=attachment,
    )
    try:
        window.resize(1100, 700)
        window.show()
        window._populate_item_detail(item.id)
        window.pages.setCurrentIndex(7)
        for _ in range(6):
            application.processEvents()

        for _ in range(3):
            window._populate_item_detail(item.id)
            for _ in range(6):
                application.processEvents()

        strays = [
            widget
            for widget in application.topLevelWidgets()
            if widget is not window and widget.isVisible()
        ]
        assert strays == []
    finally:
        window.close()
        database.dispose()


def test_repopulating_the_detail_page_leaves_no_floating_widgets(tmp_path: Path) -> None:
    """重建页面时不能用「游离顶层窗口」的方式残留在屏幕上。"""
    application = QApplication.instance() or QApplication([])
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    storage = StoragePathService(tmp_path / "archive")
    template = TemplateService(database).ensure_default_template()
    batch = BatchService(database).create_batch(name="漂浮窗口")
    item_service = ItemService(database)
    attachment = AttachmentService(database, storage)
    item = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=1, name="路由器"
    )
    source = tmp_path / "shot.png"
    image = QImage(40, 24, QImage.Format.Format_RGB32)
    image.fill(QColor("#8FA8C8"))
    assert image.save(str(source), "PNG")
    attachment.add_attachment(
        item_id=item.id,
        material_type_id=item.requirements[0].material_type_id,
        source_path=source,
    )
    window = MainWindow(
        batch_service=BatchService(database),
        item_service=item_service,
        completeness_service=CompletenessService(database, storage),
        attachment_service=attachment,
    )
    try:
        window.resize(1100, 700)
        window.show()
        window._populate_item_detail(item.id)
        window.pages.setCurrentIndex(7)
        for _ in range(6):
            application.processEvents()

        for _ in range(3):
            window._populate_item_detail(item.id)
            for _ in range(6):
                application.processEvents()

        strays = [
            widget
            for widget in application.topLevelWidgets()
            if widget is not window and widget.isVisible()
        ]
        assert strays == []
    finally:
        window.close()
        database.dispose()


def test_switching_pages_dismisses_a_lingering_tooltip() -> None:
    """切页时收起悬停气泡，避免它压在新页面标题上被当成"小弹窗"。"""
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.show()
        application.processEvents()

        QToolTip.showText(QPoint(60, 60), "26.11.4", window)
        application.processEvents()
        assert QToolTip.isVisible() is True

        window._set_page(1)
        application.processEvents()
        assert QToolTip.isVisible() is False
    finally:
        window.close()


def test_switching_pages_dismisses_a_lingering_tooltip() -> None:
    """切页时收起悬停气泡，避免它压在新页面标题上被当成"小弹窗"。"""
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.show()
        application.processEvents()

        QToolTip.showText(QPoint(60, 60), "26.11.4", window)
        application.processEvents()
        assert QToolTip.isVisible() is True

        window._set_page(1)
        application.processEvents()
        assert QToolTip.isVisible() is False
    finally:
        window.close()


def test_material_count_label_never_becomes_its_own_window(tmp_path: Path) -> None:
    """「N 个附件」标签在布局挂上去之前不能 setVisible，否则会变成顶层小窗口。"""
    application = QApplication.instance() or QApplication([])
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    storage = StoragePathService(tmp_path / "archive")
    template = TemplateService(database).ensure_default_template()
    batch = BatchService(database).create_batch(name="附件计数")
    item_service = ItemService(database)
    attachment = AttachmentService(database, storage)
    item = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=1, name="路由器"
    )
    source = tmp_path / "shot.png"
    image = QImage(40, 24, QImage.Format.Format_RGB32)
    image.fill(QColor("#A8C8A0"))
    assert image.save(str(source), "PNG")
    attachment.add_attachment(
        item_id=item.id,
        material_type_id=item.requirements[0].material_type_id,
        source_path=source,
    )
    window = MainWindow(
        batch_service=BatchService(database),
        item_service=item_service,
        completeness_service=CompletenessService(database, storage),
        attachment_service=attachment,
    )
    try:
        window._populate_item_detail(item.id)
        application.processEvents()

        labels = window.findChildren(QLabel, "materialAttachmentCount")
        assert labels, "材料卡应当渲染附件数标签"
        assert [label.text() for label in labels if label.text().endswith("个附件")]
        assert all(label.isWindow() is False for label in labels)
    finally:
        window.close()
        database.dispose()
