from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QDragEnterEvent, QDragLeaveEvent, QDropEvent, QImage
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QFrame,
    QWidget,
)

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Base, Item
from reimbursement_manager.database.repositories import MaterialTypeRepository
from reimbursement_manager.domain import ReimbursementStatus
from reimbursement_manager.services import (
    AttachmentService,
    BatchExportResult,
    BatchSubmissionMaterialsIncompleteError,
    BatchService,
    CompletenessService,
    DashboardData,
    DashboardService,
    EmptyBatchExportError,
    ExportServiceError,
    ExportTargetExistsError,
    IncompleteDashboardItem,
    ItemExportResult,
    IncompleteBatchExportItem,
    ItemService,
    PaymentScreenshotMergeService,
    PendingMaterialsService,
    StoragePathService,
    SubmissionReadinessService,
    TemplateService,
    WorkflowService,
)
from reimbursement_manager.services.desktop_integration_service import (
    DesktopIntegrationService,
)
from reimbursement_manager.services.backup_service import BackupResult
from reimbursement_manager.version import __version__
from reimbursement_manager.services.restore_service import (
    DatabaseReplacementError,
    InvalidBackupDatabaseError,
    RestoreResult,
    SafetyBackupError,
)
from reimbursement_manager.ui.windows import MainWindow
from reimbursement_manager.ui.windows import main_window
from reimbursement_manager.ui.windows.main_window import (
    BATCH_DETAIL_PAGE_INDEX,
    BATCH_LIST_PAGE_INDEX,
    ITEM_DETAIL_PAGE_INDEX,
    NewBatchDialog,
    NewItemDialog,
    NewMaterialTypeDialog,
    PENDING_MATERIALS_PAGE_INDEX,
    PAGE_TITLES,
    TEMPLATE_MANAGEMENT_PAGE_INDEX,
    TemplateEditorDialog,
)


@pytest.fixture(autouse=True)
def _dispose_qt_widgets_after_test() -> None:
    """Keep each MainWindow test isolated from Qt's deferred widget deletion."""
    yield

    application = QApplication.instance()
    if application is None:
        return

    for widget in application.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


def test_pending_materials_page_opens_item_detail_and_returns(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch = BatchService(database).create_batch(name="8月实验耗材")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=1, name="树莓派"
    )
    storage = StoragePathService(tmp_path / "archive")
    completeness = CompletenessService(database, storage)
    submission = SubmissionReadinessService(database, storage)
    window = MainWindow(
        batch_service=BatchService(database),
        item_service=item_service,
        completeness_service=completeness,
        submission_readiness_service=submission,
        pending_materials_service=PendingMaterialsService(
            item_service, completeness, submission
        ),
    )
    try:
        window.show()
        application.processEvents()
        home_item = window.navigation.item(0)
        primary_navigation = window.navigation._primary_list
        window.navigation.setCurrentRow(PENDING_MATERIALS_PAGE_INDEX)
        assert window.pending_materials_table.rowCount() == 1
        assert window.pending_materials_table.item(0, 0).text() == item.name
        assert primary_navigation.indexFromItem(home_item).isValid()
        assert primary_navigation.visualItemRect(home_item).y() >= 0

        window.pending_materials_table.cellDoubleClicked.emit(0, 0)
        assert window.pages.currentIndex() == ITEM_DETAIL_PAGE_INDEX
        assert window.item_detail_name_label.text() == item.name

        window.back_to_all_items_button.click()
        assert window.pages.currentIndex() == PENDING_MATERIALS_PAGE_INDEX

        window.navigation.setCurrentRow(0)
        assert window.pages.currentIndex() == 0
        assert home_item.isSelected()
        assert primary_navigation.indexFromItem(home_item).isValid()
        assert primary_navigation.visualItemRect(home_item).y() >= 0
    finally:
        window.close()
        database.dispose()


def test_pending_materials_page_shows_empty_state_when_all_items_are_ready(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    item_service = ItemService(database)
    storage = StoragePathService(tmp_path / "archive")
    completeness = CompletenessService(database, storage)
    submission = SubmissionReadinessService(database, storage)
    window = MainWindow(
        item_service=item_service,
        completeness_service=completeness,
        submission_readiness_service=submission,
        pending_materials_service=PendingMaterialsService(
            item_service, completeness, submission
        ),
    )
    try:
        window.navigation.setCurrentRow(PENDING_MATERIALS_PAGE_INDEX)
        assert window.pending_materials_subtitle.text() == (
            "集中处理仍缺材料或尚未准备好提交的物品"
        )
        assert window.pending_materials_table.rowCount() == 0
        assert window.pending_materials_empty_state.isHidden() is False
        assert window.pending_materials_empty_title.text() == (
            "当前没有待处理事项"
        )
        assert window.pending_materials_table.isHidden() is True
        assert window.pending_materials_list_surface.isHidden() is True
        assert window.pending_materials_summary_label.text() == "还有 0 个物品需要处理"
    finally:
        window.close()
        database.dispose()


def test_pending_materials_separates_collection_and_submission_states(tmp_path) -> None:
    """Collection-complete Items remain visible until final submission files exist."""
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch = BatchService(database).create_batch(name="8月实验耗材")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    collection_incomplete = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=1, name="缺发票物品"
    )
    submission_incomplete = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=2, name="待合并支付截图物品"
    )
    submission_ready = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=3, name="已完成物品"
    )
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    with database.transaction() as session:
        material_types = MaterialTypeRepository(session)
        material_type_ids = {
            code: material_types.get_by_code(code).id
            for code in (
                "physical_photo",
                "payment_screenshot",
                "invoice",
                "order_screenshot",
            )
        }

    def add_collection_attachments(
        item_id: int, stem: str, *, include_invoice: bool = True
    ) -> None:
        for code, color in (
            ("physical_photo", "red"),
            ("payment_screenshot", "blue"),
            ("order_screenshot", "green"),
        ):
            source = tmp_path / f"{stem}-{code}.png"
            image = QImage(2, 2, QImage.Format.Format_RGB32)
            image.fill(QColor(color))
            assert image.save(str(source), "PNG")
            attachments.add_attachment(
                item_id=item_id,
                material_type_id=material_type_ids[code],
                source_path=source,
            )
        if include_invoice:
            invoice = tmp_path / f"{stem}-invoice.pdf"
            invoice.write_bytes(stem.encode())
            attachments.add_attachment(
                item_id=item_id,
                material_type_id=material_type_ids["invoice"],
                source_path=invoice,
            )

    add_collection_attachments(
        collection_incomplete.id, "collection-incomplete", include_invoice=False
    )
    add_collection_attachments(submission_incomplete.id, "submission-incomplete")
    add_collection_attachments(submission_ready.id, "submission-ready")
    PaymentScreenshotMergeService(database, storage).generate(submission_ready.id)

    completeness = CompletenessService(database, storage)
    submission = SubmissionReadinessService(database, storage)
    window = MainWindow(
        batch_service=BatchService(database),
        item_service=item_service,
        completeness_service=completeness,
        attachment_service=attachments,
        submission_readiness_service=submission,
        pending_materials_service=PendingMaterialsService(
            item_service, completeness, submission
        ),
    )
    try:
        window.navigation.setCurrentRow(PENDING_MATERIALS_PAGE_INDEX)
        assert window.pending_materials_table.rowCount() == 2
        assert window.pending_materials_summary_label.text() == "还有 2 个物品需要处理"

        rows_by_name = {
            window.pending_materials_table.item(row, 0).text(): row
            for row in range(window.pending_materials_table.rowCount())
        }
        incomplete_row = rows_by_name[collection_incomplete.name]
        assert window.pending_materials_table.item(incomplete_row, 2).text() == "3 / 4"
        assert window.pending_materials_table.item(incomplete_row, 3).text() == "缺少：发票"
        assert window.pending_materials_table.item(incomplete_row, 4).text() == "1 / 3"

        submission_row = rows_by_name[submission_incomplete.name]
        assert window.pending_materials_table.item(submission_row, 2).text() == "4 / 4"
        assert window.pending_materials_table.item(submission_row, 3).text() == "材料完整"
        assert window.pending_materials_table.item(submission_row, 4).text() == "2 / 3"
        assert window.pending_materials_table.item(submission_row, 5).text() == "缺少：合并支付截图"
        assert submission_ready.name not in rows_by_name
    finally:
        window.close()
        database.dispose()


def test_pending_materials_refreshes_after_final_payment_changes_and_item_delete(
    tmp_path,
) -> None:
    """The view refreshes service-provided pending data after each material change."""
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch = BatchService(database).create_batch(name="待补材料刷新")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=1, name="待提交物品"
    )
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    item_service = ItemService(database, attachments)
    with database.transaction() as session:
        material_types = MaterialTypeRepository(session)
        material_type_ids = {
            code: material_types.get_by_code(code).id
            for code in (
                "physical_photo",
                "payment_screenshot",
                "invoice",
                "order_screenshot",
            )
        }
    for code, color in (
        ("physical_photo", "red"),
        ("payment_screenshot", "blue"),
        ("order_screenshot", "green"),
    ):
        source = tmp_path / f"{code}.png"
        image = QImage(2, 2, QImage.Format.Format_RGB32)
        image.fill(QColor(color))
        assert image.save(str(source), "PNG")
        attachments.add_attachment(
            item_id=item.id,
            material_type_id=material_type_ids[code],
            source_path=source,
        )
    invoice = tmp_path / "invoice.pdf"
    invoice.write_bytes(b"invoice")
    attachments.add_attachment(
        item_id=item.id,
        material_type_id=material_type_ids["invoice"],
        source_path=invoice,
    )

    completeness = CompletenessService(database, storage)
    submission = SubmissionReadinessService(database, storage)
    window = MainWindow(
        item_service=item_service,
        completeness_service=completeness,
        attachment_service=attachments,
        submission_readiness_service=submission,
        pending_materials_service=PendingMaterialsService(
            item_service, completeness, submission
        ),
    )
    try:
        window.navigation.setCurrentRow(PENDING_MATERIALS_PAGE_INDEX)
        assert window.pending_materials_table.rowCount() == 1

        PaymentScreenshotMergeService(database, storage).generate(item.id)
        window.refresh_pending_materials()
        assert window.pending_materials_table.rowCount() == 0

        derived_attachment = next(
            attachment
            for attachment in attachments.list_attachments(item.id)
            if attachment.is_derived
        )
        attachments.remove_attachment(derived_attachment.id)
        window.refresh_pending_materials()
        assert window.pending_materials_table.rowCount() == 1

        item_service.delete_item(item.id)
        window.refresh_pending_materials()
        assert window.pending_materials_table.rowCount() == 0
    finally:
        window.close()
        database.dispose()


def test_main_window_has_navigation_and_placeholder_pages() -> None:
    application = QApplication.instance() or QApplication([])
    del application
    window = MainWindow()
    try:
        assert window.windowTitle() == "报销材料管理器"
        assert window.navigation.count() == len(PAGE_TITLES)
        assert [
            window.navigation.item(index).text()
            for index in range(len(PAGE_TITLES))
        ] == list(PAGE_TITLES)
        assert window.pages.count() == len(PAGE_TITLES) + 2

        window.navigation.setCurrentRow(2)
        assert window.pages.currentIndex() == 2
    finally:
        window.close()


class DashboardServiceStub:
    def get_data(self) -> DashboardData:
        return DashboardData(
            incomplete_count=1,
            complete_count=2,
            submitted_count=3,
            reimbursed_count=4,
            incomplete_items=(
                IncompleteDashboardItem(
                    item_id=1,
                    name="树莓派 Zero 2 W",
                    completed_count=3,
                    required_count=4,
                    missing_materials=("发票",),
                ),
            ),
        )


def test_main_window_displays_dashboard_data() -> None:
    application = QApplication.instance() or QApplication([])
    del application
    window = MainWindow(DashboardServiceStub())  # type: ignore[arg-type]
    try:
        assert len(window.findChildren(QFrame, "dashboardStatCard")) == 4
        assert window.dashboard_summary_labels["待处理"].text() == "1"
        assert window.dashboard_summary_labels["可提交"].text() == "2"
        assert window.dashboard_summary_labels["已提交"].text() == "3"
        assert window.dashboard_summary_labels["已报销"].text() == "4"
        assert len(window.dashboard_pending_items) == 1
        pending_item = window.dashboard_pending_items[0]
        assert (
            pending_item.findChild(QLabel, "dashboardItemName").text()
            == "树莓派 Zero 2 W"
        )
        assert pending_item.findChild(QLabel, "dashboardItemBatch").text() == "所属批次：—"
        assert [
            label.text()
            for label in pending_item.findChildren(QLabel, "dashboardProgressLabel")
        ] == ["材料收集"]
        assert [
            label.text()
            for label in pending_item.findChildren(QLabel, "dashboardProgressValue")
        ] == ["3 / 4"]
        assert pending_item.findChild(QLabel, "dashboardMissing").text() == "缺少：发票"
        assert window.dashboard_pending_summary.text() == "还有 1 个物品需要处理"
        window.resize(1100, 700)
    finally:
        window.close()


def test_dashboard_shows_empty_state_when_no_items_need_attention() -> None:
    application = QApplication.instance() or QApplication([])
    del application
    window = MainWindow()
    try:
        assert window.dashboard_pending_items == []
        assert window.dashboard_empty_state.text() == (
            "当前没有待处理事项\n所有物品的提交材料都已准备完成。"
        )
    finally:
        window.close()


def test_dashboard_constructs_and_reflows_stat_cards_on_resize() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(DashboardServiceStub())  # type: ignore[arg-type]
    try:
        window.show()
        window.resize(1100, 700)
        application.processEvents()
        assert window.dashboard_stats_grid.layout().itemAtPosition(0, 3) is not None
    finally:
        window.close()


def test_dashboard_reuses_injected_services_for_batch_and_submission(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch_service = BatchService(database)
    batch = batch_service.create_batch(name="8月实验耗材")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=1, name="树莓派"
    )
    storage = StoragePathService(tmp_path / "archive")
    completeness = CompletenessService(database, storage)
    window = MainWindow(
        DashboardService(database, completeness),
        batch_service=batch_service,
        item_service=item_service,
        completeness_service=completeness,
        submission_readiness_service=SubmissionReadinessService(database, storage),
    )
    try:
        pending_item = window.dashboard_pending_items[0]
        assert pending_item.findChild(QLabel, "dashboardItemBatch").text() == (
            "所属批次：8月实验耗材"
        )
        assert [
            label.text()
            for label in pending_item.findChildren(QLabel, "dashboardProgressLabel")
        ] == ["材料收集", "提交材料"]
        assert [
            label.text()
            for label in pending_item.findChildren(QLabel, "dashboardProgressValue")
        ] == ["0 / 4", "0 / 3"]
        pending_item.findChild(QPushButton, "dashboardItemDetailButton").click()
        assert window.pages.currentIndex() == ITEM_DETAIL_PAGE_INDEX
        assert item.name == "树莓派"
    finally:
        window.close()
        database.dispose()


def test_batch_list_displays_batches_and_refreshes_after_creation(monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch_service = BatchService(database)
    batch_service.create_batch(name="已有批次")

    class TextFieldStub:
        def __init__(self, value: str) -> None:
            self._value = value

        def text(self) -> str:
            return self._value

        def toPlainText(self) -> str:
            return self._value

    class NewBatchDialogStub:
        def __init__(self, parent) -> None:
            del parent
            self.name_input = TextFieldStub("新批次")
            self.reimburser_input = TextFieldStub("张三")
            self.project_name_input = TextFieldStub("测试项目")
            self.notes_input = TextFieldStub("测试备注")

        def exec(self):
            return main_window.QDialog.DialogCode.Accepted

    monkeypatch.setattr(main_window, "NewBatchDialog", NewBatchDialogStub)
    window = MainWindow(batch_service=batch_service)
    try:
        assert window.batch_table.rowCount() == 1
        assert [
            window.batch_table.item(0, column).text() for column in range(5)
        ] == ["已有批次", window.batch_table.item(0, 1).text(), "0", "¥0.00", "收集中"]

        window.new_batch_button.click()

        assert window.batch_table.rowCount() == 2
        assert [
            window.batch_table.item(1, column).text() for column in range(5)
        ] == ["新批次", window.batch_table.item(1, 1).text(), "0", "¥0.00", "收集中"]
        assert batch_service.list_batches()[1].reimburser == "张三"
        assert batch_service.list_batches()[1].project_name == "测试项目"
        assert batch_service.list_batches()[1].notes == "测试备注"
    finally:
        window.close()
        database.dispose()


def test_batch_detail_displays_items_completeness_and_empty_batch(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch_service = BatchService(database)
    empty_batch = batch_service.create_batch(name="空批次")
    populated_batch = batch_service.create_batch(name="实验耗材")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item_service.create_item(
        batch_id=populated_batch.id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W",
        total_amount_cents=12345,
    )
    completeness_service = CompletenessService(
        database, StoragePathService(tmp_path)
    )
    window = MainWindow(
        batch_service=batch_service,
        item_service=item_service,
        completeness_service=completeness_service,
    )
    try:
        window.navigation.setCurrentRow(BATCH_LIST_PAGE_INDEX)
        window.batch_table.cellDoubleClicked.emit(1, 0)

        assert window.pages.currentIndex() == BATCH_DETAIL_PAGE_INDEX
        assert window.batch_detail_name_label.text() == "实验耗材"
        assert window.batch_detail_total_amount_label.text() == "总金额：¥123.45"
        assert window.batch_detail_item_count_label.text() == "物品数量：1"
        assert [
            window.batch_detail_table.item(0, column).text()
            for column in range(4)
        ] == [
            "树莓派 Zero 2 W",
            "¥123.45",
            "0/4",
            "实物照片、支付截图、发票、订单截图",
        ]

        window.back_to_batch_list_button.click()
        assert window.pages.currentIndex() == BATCH_LIST_PAGE_INDEX
        assert window.navigation.currentRow() == BATCH_LIST_PAGE_INDEX

        window.batch_table.cellDoubleClicked.emit(0, 0)
        assert window.pages.currentIndex() == BATCH_DETAIL_PAGE_INDEX
        assert window.batch_detail_name_label.text() == empty_batch.name
        assert window.batch_detail_total_amount_label.text() == "总金额：¥0.00"
        assert window.batch_detail_item_count_label.text() == "物品数量：0"
        assert window.batch_detail_table.rowCount() == 0
    finally:
        window.close()
        database.dispose()


def test_batch_detail_uses_compact_summary_empty_state_and_item_navigation(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch_service = BatchService(database)
    empty_batch = batch_service.create_batch(name="\u7a7a\u6279\u6b21")
    batch = batch_service.create_batch(name="\u5b9e\u9a8c\u8017\u6750")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="\u6811\u8393\u6d3e Zero 2 W",
        total_amount_cents=12345,
    )
    completeness = CompletenessService(database, StoragePathService(tmp_path))
    window = MainWindow(
        batch_service=batch_service,
        item_service=item_service,
        completeness_service=completeness,
        export_service=object(),
        workflow_service=object(),
    )
    try:
        window.batch_table.cellDoubleClicked.emit(1, 0)

        assert window.back_to_batch_list_button.text() == "\u2190 \u62a5\u9500\u6279\u6b21"
        assert window.batch_detail_summary_label.text() == "1 \u4e2a\u7269\u54c1 \u00b7 \u00a5123.45"
        assert window.new_item_button.text() == "+ \u65b0\u589e\u7269\u54c1"
        assert window.new_item_button.isEnabled() is True
        assert window.export_batch_materials_button.isEnabled() is True
        assert window.batch_detail_overview_count_label.text() == "1 \u4e2a"
        assert window.batch_detail_overview_amount_label.text() == "\u00a5123.45"
        assert window.batch_detail_workflow_summary_label.text() == "1 个待补材料"
        assert window.batch_mark_submitted_button.text() == "\u6807\u8bb0\u6279\u6b21\u5df2\u63d0\u4ea4"
        assert window.batch_mark_reimbursed_button.text() == "\u6807\u8bb0\u6279\u6b21\u5df2\u62a5\u9500"
        assert window.batch_mark_submitted_button.isEnabled() is True
        assert window.batch_mark_reimbursed_button.isEnabled() is False
        assert window.delete_batch_button.text() == "\u5220\u9664\u6279\u6b21"
        assert window.batch_detail_list_surface.isHidden() is False
        assert window.batch_detail_empty_state.isHidden() is True
        assert window.batch_detail_table.horizontalHeaderItem(4).text() == "\u62a5\u9500\u72b6\u6001"
        assert window.batch_detail_table.item(0, 4).text() == "\u5f85\u8865\u6750\u6599"
        assert window.batch_detail_table.cellWidget(0, 4).text() == "\u5f85\u8865\u6750\u6599"
        assert window.batch_detail_table.item(0, 1).textAlignment() & int(
            Qt.AlignmentFlag.AlignRight
        )

        window.batch_detail_table.cellDoubleClicked.emit(0, 0)
        assert window.pages.currentIndex() == ITEM_DETAIL_PAGE_INDEX
        assert window.item_detail_name_label.text() == item.name
        window.back_to_all_items_button.click()
        assert window.pages.currentIndex() == BATCH_DETAIL_PAGE_INDEX
        assert window.navigation.currentRow() == BATCH_LIST_PAGE_INDEX

        window.batch_table.cellDoubleClicked.emit(0, 0)
        assert window.batch_detail_list_surface.isHidden() is True
        assert window.batch_detail_empty_state.isHidden() is False
        assert window.empty_new_item_button.text() == "+ \u65b0\u589e\u7269\u54c1"
        assert empty_batch.name == "\u7a7a\u6279\u6b21"
    finally:
        window.close()
        database.dispose()


def test_new_item_from_batch_detail_uses_template_and_refreshes_detail(
    monkeypatch, tmp_path
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch_service = BatchService(database)
    batch = batch_service.create_batch(name="实验耗材")
    item_service = ItemService(database)
    template_service = TemplateService(database)
    template = template_service.ensure_default_template()
    completeness_service = CompletenessService(
        database, StoragePathService(tmp_path)
    )

    class TextFieldStub:
        def __init__(self, value: str) -> None:
            self._value = value

        def text(self) -> str:
            return self._value

        def toPlainText(self) -> str:
            return self._value

    class NewItemDialogStub:
        def __init__(self, batch_name, templates, parent) -> None:
            del batch_name, templates, parent
            self.name_input = TextFieldStub("树莓派 Zero 2 W")
            self.platform_input = TextFieldStub("淘宝")
            self.merchant_input = TextFieldStub("电子器材店")
            self.order_number_input = TextFieldStub("ORDER-001")
            self.notes_input = TextFieldStub("测试备注")

        def exec(self):
            return main_window.QDialog.DialogCode.Accepted

        def template_id(self) -> int:
            return template.id

        def purchase_date(self):
            return None

        def total_amount_cents(self) -> int:
            return 12345

    monkeypatch.setattr(main_window, "NewItemDialog", NewItemDialogStub)
    window = MainWindow(
        batch_service=batch_service,
        item_service=item_service,
        completeness_service=completeness_service,
        template_service=template_service,
    )
    try:
        window.batch_table.cellDoubleClicked.emit(0, 0)
        window.new_item_button.click()

        assert window.batch_detail_table.rowCount() == 1
        assert [
            window.batch_detail_table.item(0, column).text()
            for column in range(4)
        ] == [
            "树莓派 Zero 2 W",
            "¥123.45",
            "0/4",
            "实物照片、支付截图、发票、订单截图",
        ]
        created_id = item_service.list_items_by_batch(batch.id)[0].id
        created = item_service.get_item(created_id)
        assert created.sequence_number == 1
        assert created.platform == "淘宝"
        assert created.merchant == "电子器材店"
        assert created.order_number == "ORDER-001"
        assert created.total_amount_cents == 12345
        assert [
            (requirement.material_type.code, requirement.required)
            for requirement in created.requirements
        ] == [
            ("physical_photo", True),
            ("payment_screenshot", True),
            ("invoice", True),
            ("order_screenshot", True),
        ]
    finally:
        window.close()
        database.dispose()


def test_batch_list_empty_state_exposes_creation_entry() -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    window = MainWindow(batch_service=BatchService(database))
    try:
        assert window.batch_list_page.findChild(QLabel, "pageTitle").text() == "报销批次"
        assert window.batch_list_subtitle.text() == "管理当前和历史报销批次"
        assert window.new_batch_button.text() == "+ 新建批次"
        assert window.batch_list_surface.isHidden() is True
        assert window.batch_empty_state.isHidden() is False
        assert "暂无报销批次" in [
            label.text() for label in window.batch_empty_state.findChildren(QLabel)
        ]
        assert window.empty_new_batch_button.text() == "新建批次"
    finally:
        window.close()
        database.dispose()


def test_batch_list_applies_alignment_and_hides_empty_state_when_populated() -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch_service = BatchService(database)
    batch_service.create_batch(name="实验耗材")
    window = MainWindow(batch_service=batch_service)
    try:
        assert window.batch_table.rowCount() == 1
        assert window.batch_list_surface.isHidden() is False
        assert window.batch_empty_state.isHidden() is True
        assert window.batch_table.item(0, 2).textAlignment() & int(
            Qt.AlignmentFlag.AlignRight
        )
        assert window.batch_table.item(0, 3).textAlignment() & int(
            Qt.AlignmentFlag.AlignRight
        )
        assert window.batch_table.item(0, 4).text() == "收集中"
        assert window.batch_table.horizontalHeader().isHidden() is False
        assert window.batch_table.horizontalHeaderItem(0).text() == "批次名称"
        assert window.batch_table.verticalHeader().defaultSectionSize() == 52
    finally:
        window.close()
        database.dispose()


def test_new_batch_dialog_uses_required_field_and_primary_action() -> None:
    application = QApplication.instance() or QApplication([])
    del application
    dialog = NewBatchDialog()
    try:
        assert dialog.windowTitle() == "新建报销批次"
        assert dialog.objectName() == "standardDialog"
        assert dialog.findChild(QLabel, "dialogTitle").text() == "新建报销批次"
        assert dialog.name_input is not None
        assert dialog.buttons.button(QDialogButtonBox.StandardButton.Save).text() == "创建批次"
        assert dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel).text() == "取消"
    finally:
        dialog.close()


def test_template_management_list_shows_existing_template() -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    template = TemplateService(database).ensure_default_template()
    window = MainWindow(template_service=TemplateService(database))
    try:
        window.navigation.setCurrentRow(TEMPLATE_MANAGEMENT_PAGE_INDEX)

        assert window.findChild(QLabel, "templatePageTitle").text() == "模板管理"
        assert window.new_template_button.text() == "+ 新建模板"
        assert window.template_table.rowCount() == 1
        assert window.template_table.isHidden() is False
        assert window.template_empty_state.isHidden() is True
        assert [
            window.template_table.item(0, column).text()
            for column in range(2)
        ] == [template.name, "4 项材料 · 4 项必需"]
        actions = window.template_table.cellWidget(0, 2)
        assert actions is not None
        assert [
            button.text() for button in actions.findChildren(QPushButton)
        ] == ["编辑", "删除"]
        assert window.findChild(QLabel, "templatePageSubtitle").text() == (
            "管理新建报销物品时使用的材料清单"
        )
    finally:
        window.close()
        database.dispose()


def test_template_management_empty_state_provides_creation_entry() -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    window = MainWindow(template_service=TemplateService(database))
    try:
        window.navigation.setCurrentRow(TEMPLATE_MANAGEMENT_PAGE_INDEX)

        assert window.template_table.isHidden() is True
        assert window.template_empty_state.isHidden() is False
        assert window.template_empty_state.findChild(QLabel, "emptyStateTitle").text() == "暂无报销模板"
        assert window.template_empty_state.findChild(QLabel, "emptyStateDescription").text() == (
            "创建模板后，新建物品时可以快速生成材料清单。"
        )
        assert window.empty_new_template_button.text() == "+ 新建模板"
    finally:
        window.close()
        database.dispose()


def test_template_editor_creates_and_edits_material_configuration() -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    service = TemplateService(database)
    service.ensure_default_template()
    material_types = service.list_material_types()
    dialog = TemplateEditorDialog(service, material_types)
    try:
        assert dialog.objectName() == "standardDialog"
        assert dialog.findChild(QLabel, "dialogSectionTitle").text() == "模板材料"
        dialog.name_input.setText("发票采购")
        dialog.material_inputs["physical_photo"][0].setChecked(True)
        dialog.material_inputs["invoice"][0].setChecked(True)
        dialog._save()

        created = service.get_template(dialog.template_id)
        assert [
            (value.material_type.code, value.required)
            for value in created.materials
        ] == [("physical_photo", True), ("invoice", True)]
    finally:
        dialog.close()

    editor = TemplateEditorDialog(service, material_types, created)
    try:
        assert editor.windowTitle() == "编辑模板"
        assert editor.buttons.button(QDialogButtonBox.StandardButton.Save).text() == "保存模板"
        editor.material_inputs["physical_photo"][0].setChecked(False)
        editor.material_inputs["invoice"][1].setChecked(False)
        editor.material_inputs["order_detail"][0].setChecked(True)
        editor._save()

        updated = service.get_template(created.id)
        assert [
            (value.material_type.code, value.required)
            for value in updated.materials
        ] == [("invoice", False), ("order_detail", True)]
    finally:
        editor.close()
        database.dispose()


def test_template_editor_rejects_blank_name_without_crashing(monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    service = TemplateService(database)
    service.ensure_default_template()
    dialog = TemplateEditorDialog(service, service.list_material_types())
    warnings: list[str] = []
    monkeypatch.setattr(
        main_window.QMessageBox,
        "warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    try:
        dialog.material_inputs["invoice"][0].setChecked(True)
        dialog._save()

        assert warnings == ["模板名称不能为空。"]
        assert dialog.result() != main_window.QDialog.DialogCode.Accepted
    finally:
        dialog.close()
        database.dispose()


def test_template_editor_adds_a_custom_material_type(
    monkeypatch,
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    service = TemplateService(database)

    class _AcceptedMaterialTypeDialog:
        def __init__(self, parent=None) -> None:
            self._parent = parent

        def exec(self) -> object:
            return main_window.QDialog.DialogCode.Accepted

        def material_name(self) -> str:
            return "验收单"

        def description(self) -> str:
            return "设备到货验收"

    monkeypatch.setattr(main_window, "NewMaterialTypeDialog", _AcceptedMaterialTypeDialog)
    dialog = TemplateEditorDialog(service, service.list_material_types())
    try:
        assert dialog.add_material_type_button.text() == "+ 新增材料类型"

        dialog._add_custom_material_type()

        material_type = next(
            value for value in service.list_material_types() if value.name == "验收单"
        )
        assert material_type.code == "custom"
        assert material_type.description == "设备到货验收"
        included, required = dialog.material_inputs[material_type.code]
        assert included.isChecked()
        assert required.isChecked()
        assert required.isEnabled()

        dialog.name_input.setText("验收模板")
        dialog._save()

        created = service.get_template(dialog.template_id)
        assert [
            (value.material_type.code, value.material_type.name, value.required)
            for value in created.materials
        ] == [("custom", "验收单", True)]
    finally:
        dialog.close()
        database.dispose()


def test_new_material_type_dialog_rejects_blank_name(monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    dialog = NewMaterialTypeDialog()
    warnings: list[str] = []
    monkeypatch.setattr(
        main_window.QMessageBox,
        "warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    try:
        dialog._accept_if_valid()

        assert warnings == ["材料名称不能为空。"]
        assert dialog.result() != main_window.QDialog.DialogCode.Accepted
    finally:
        dialog.close()


def test_template_editor_changes_do_not_change_existing_item_materials() -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    template_service = TemplateService(database)
    template = template_service.ensure_default_template()
    batch = BatchService(database).create_batch(name="模板快照")
    item_service = ItemService(database)
    item = item_service.create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="已有物品",
    )
    editor = TemplateEditorDialog(
        template_service, template_service.list_material_types(), template
    )
    try:
        editor.material_inputs["invoice"][0].setChecked(False)
        editor._save()

        stored_item = item_service.get_item(item.id)
        assert {requirement.material_type.code for requirement in stored_item.requirements} == {
            "physical_photo",
            "payment_screenshot",
            "invoice",
            "order_screenshot",
        }
    finally:
        editor.close()
        database.dispose()


def test_new_item_dialog_converts_amount_to_cents_without_float() -> None:
    application = QApplication.instance() or QApplication([])
    del application
    dialog = NewItemDialog("实验耗材", [SimpleNamespace(id=1, name="普通购物")])
    try:
        assert dialog.objectName() == "standardDialog"
        assert dialog.minimumWidth() == 560
        assert dialog.buttons.button(QDialogButtonBox.StandardButton.Save).text() == "创建物品"
        assert dialog.total_amount_cents() == 0
        dialog.amount_input.setText("123.45")
        assert dialog.total_amount_cents() == 12345
        dialog.amount_input.setText("1.001")
        with pytest.raises(ValueError, match="最多保留两位小数"):
            dialog.total_amount_cents()
    finally:
        dialog.close()


def test_all_items_page_displays_and_searches_items(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch_service = BatchService(database)
    batch = batch_service.create_batch(name="实验耗材")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item_service.create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W",
        merchant="电子器材店",
        order_number="ORDER-001",
        total_amount_cents=12345,
    )
    item_service.create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=2,
        name="HDMI 转接头",
        platform="淘宝",
        total_amount_cents=500,
    )
    completeness_service = CompletenessService(
        database, StoragePathService(tmp_path)
    )
    window = MainWindow(
        batch_service=batch_service,
        item_service=item_service,
        completeness_service=completeness_service,
    )
    try:
        window.navigation.setCurrentRow(2)
        assert window.all_items_table.rowCount() == 2
        assert [
            window.all_items_table.item(0, column).text()
            for column in range(7)
        ] == [
            "树莓派 Zero 2 W",
            "实验耗材",
            "¥123.45",
            "—",
            "—",
            "0 / 4",
            "实物照片、支付截图、发票、订单截图",
        ]
        assert window.all_items_title.text() == "所有物品"
        assert window.all_items_subtitle.text() == "查看和搜索全部报销物品"
        assert (
            window.all_items_search_input.placeholderText()
            == "搜索物品、商家或订单号"
        )
        assert (
            window.all_items_table.item(0, 2).textAlignment()
            == int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        )
        assert window.all_items_table.cellWidget(0, 7).text() == "待补材料"

        window.all_items_search_input.setText("电子器材")
        assert window.all_items_table.rowCount() == 1
        assert window.all_items_table.item(0, 0).text() == "树莓派 Zero 2 W"

        window.all_items_search_input.clear()
        assert window.all_items_table.rowCount() == 2

        window.all_items_search_input.setText("不存在")
        assert window.all_items_table.rowCount() == 0
        assert window.all_items_empty_title.text() == "没有找到匹配的物品"
        assert window.all_items_empty_description.text() == "尝试使用其他关键词。"

        window.all_items_search_input.clear()
        assert window.all_items_table.rowCount() == 2
    finally:
        window.close()
        database.dispose()


def test_all_items_shows_ready_status_when_submission_package_is_complete(
    tmp_path,
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch = BatchService(database).create_batch(name="实验耗材")
    template_service = TemplateService(database)
    template_service.ensure_default_template()
    template = template_service.create_template(name="简化模板")
    template_service.add_material(template.id, "physical_photo", required=True)
    item = ItemService(database).create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="墙报",
        total_amount_cents=4000,
    )
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    source = tmp_path / "photo.png"
    image = QImage(2, 2, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    assert image.save(str(source), "PNG")
    with database.transaction() as session:
        stored_material_type = MaterialTypeRepository(session).get_by_code(
            "physical_photo"
        )
        assert stored_material_type is not None
        material_type_id = stored_material_type.id
    attachments.add_attachment(
        item_id=item.id,
        material_type_id=material_type_id,
        source_path=source,
    )
    window = MainWindow(
        batch_service=BatchService(database),
        item_service=ItemService(database),
        completeness_service=CompletenessService(database, storage),
        attachment_service=attachments,
        submission_readiness_service=SubmissionReadinessService(database, storage),
    )
    try:
        window.navigation.setCurrentRow(2)
        status_badge = window.all_items_table.cellWidget(0, 7)
        assert status_badge is not None
        assert status_badge.text() == "可提交"
        assert status_badge.property("status") == "ready"

        window.all_items_table.cellDoubleClicked.emit(0, 0)
        assert window.item_detail_status_label.text() == "可提交"
        assert window.item_detail_status_label.property("status") == "ready"

        with database.transaction() as session:
            stored_item = session.get(Item, item.id)
            assert stored_item is not None
            assert stored_item.status is ReimbursementStatus.COLLECTING
    finally:
        window.close()
        database.dispose()


def test_all_items_flags_missing_merged_payment_as_pending_receipt(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch = BatchService(database).create_batch(name="实验耗材")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W",
        total_amount_cents=12345,
    )
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    with database.transaction() as session:
        material_types = MaterialTypeRepository(session)
        material_type_ids = {
            code: material_types.get_by_code(code).id  # type: ignore[union-attr]
            for code in (
                "physical_photo",
                "payment_screenshot",
                "invoice",
                "order_screenshot",
            )
        }
    for code, suffix in (
        ("physical_photo", ".png"),
        ("payment_screenshot", ".png"),
        ("invoice", ".pdf"),
        ("order_screenshot", ".png"),
    ):
        source = tmp_path / f"{code}{suffix}"
        if suffix == ".png":
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
        else:
            source.write_bytes(b"invoice")
        attachments.add_attachment(
            item_id=item.id,
            material_type_id=material_type_ids[code],
            source_path=source,
        )
    window = MainWindow(
        batch_service=BatchService(database),
        item_service=ItemService(database),
        completeness_service=CompletenessService(database, storage),
        attachment_service=attachments,
        submission_readiness_service=SubmissionReadinessService(database, storage),
    )
    try:
        window.navigation.setCurrentRow(2)
        assert window.all_items_table.item(0, 5).text() == "4 / 4"
        status_badge = window.all_items_table.cellWidget(0, 7)
        assert status_badge is not None
        assert status_badge.text() == "待生成凭证"
        assert status_badge.property("status") == "pending_payment"
    finally:
        window.close()
        database.dispose()


def test_all_items_opens_item_detail_and_returns_with_all_attachments(
    tmp_path,
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch_service = BatchService(database)
    batch = batch_service.create_batch(name="实验耗材")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W",
        purchase_date=date(2026, 8, 29),
        merchant="电子器材店",
        platform="淘宝",
        order_number="ORDER-001",
        total_amount_cents=12345,
    )
    storage = StoragePathService(tmp_path / "archive")
    attachment_service = AttachmentService(database, storage)
    with database.transaction() as session:
        material_types = MaterialTypeRepository(session)
        photo = material_types.get_by_code("physical_photo")
        payment = material_types.get_by_code("payment_screenshot")
        invoice = material_types.get_by_code("invoice")
        order = material_types.get_by_code("order_screenshot")
        assert photo is not None
        assert payment is not None
        assert invoice is not None
        assert order is not None
        material_type_ids = [photo.id, payment.id, invoice.id, order.id]
    sources = []
    for index, material_type_id in enumerate(material_type_ids, start=1):
        source = tmp_path / f"source-{index}.png"
        source.write_bytes(f"attachment-{index}".encode())
        sources.append((source, material_type_id))
    extra_photo = tmp_path / "source-extra.png"
    extra_photo.write_bytes(b"extra photo")
    sources.append((extra_photo, material_type_ids[0]))
    attachments = [
        attachment_service.add_attachment(
            item_id=item.id,
            material_type_id=material_type_id,
            source_path=source,
        )
        for source, material_type_id in sources
    ]
    completeness_service = CompletenessService(database, storage)
    window = MainWindow(
        batch_service=batch_service,
        item_service=item_service,
        completeness_service=completeness_service,
        attachment_service=attachment_service,
        submission_readiness_service=SubmissionReadinessService(database, storage),
    )
    try:
        window.navigation.setCurrentRow(2)
        assert window.all_items_table.item(0, 5).text() == "4 / 4"
        assert window.all_items_table.item(0, 6).text() == "材料完整"
        assert window.all_items_table.cellWidget(0, 7).text() == "待生成凭证"
        window.all_items_table.cellDoubleClicked.emit(0, 0)

        assert window.pages.currentIndex() == ITEM_DETAIL_PAGE_INDEX
        assert window.item_detail_name_label.text() == "树莓派 Zero 2 W"
        assert window.item_detail_amount_label.text() == "¥123.45"
        assert window.item_detail_primary_metadata_label.text() == "淘宝 · 2026-08-29"
        assert window.item_detail_merchant_label.text() == "商家：电子器材店"
        assert window.item_detail_order_number_label.text() == "订单号：ORDER-001"
        assert window.item_detail_batch_label.text() == "所属批次：实验耗材"
        assert window.item_detail_collection_count_label.text() == "4 / 4"
        assert window.item_detail_collection_percentage_label.text() == "100%"
        assert window.item_detail_completeness_label.text() == "材料完整"
        assert window.item_detail_submission_count_label.text() == "2 / 3"
        assert window.item_detail_submission_readiness_label.text() == "缺少：合并支付截图"
        sections = _material_sections(window)
        assert len(sections) == 4
        first_requirement = sections[0]
        cards = _attachment_cards(window, requirement_index=0)
        assert len(cards) == 2
        assert {card.findChild(QLabel, "attachmentFilename").toolTip() for card in cards} == {
            attachments[0].stored_filename,
            attachments[-1].stored_filename,
        }
        assert first_requirement.findChild(QLabel, "materialSectionTitle") is not None
        assert first_requirement.findChild(QLabel, "materialRequirementBadge").text() == "必需"
        assert first_requirement.findChild(QLabel, "materialAttachmentCount").text() == "2 个附件"
        add_attachment_button = first_requirement.findChild(
            QPushButton, "itemDetailAddAttachmentButton"
        )
        assert add_attachment_button is not None
        window.resize(1015, 800)
        window.show()
        QApplication.processEvents()
        assert window.item_detail_scroll_area.horizontalScrollBar().maximum() == 0
        assert first_requirement.findChild(QWidget, "attachmentGrid") is not None

        window.back_to_all_items_button.click()
        assert window.pages.currentIndex() == 2
    finally:
        window.close()
        database.dispose()


def test_item_detail_marks_unuploaded_optional_material_as_optional(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch = BatchService(database).create_batch(name="可选材料")
    template_service = TemplateService(database)
    template = template_service.ensure_default_template()
    template_service.set_material_required(template.id, "invoice", required=False)
    item = ItemService(database).create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="带可选发票的物品",
    )
    storage = StoragePathService(tmp_path / "archive")
    window = MainWindow(
        batch_service=BatchService(database),
        item_service=ItemService(database),
        completeness_service=CompletenessService(database, storage),
        attachment_service=AttachmentService(database, storage),
    )
    try:
        window.navigation.setCurrentRow(2)
        window.all_items_table.cellDoubleClicked.emit(0, 0)

        optional_requirement = _material_sections(window)[2]
        assert optional_requirement.findChild(
            QLabel, "materialRequirementBadge"
        ).text() == "可选"
        assert optional_requirement.findChild(
            QLabel, "materialAttachmentCount"
        ).text() == "0 个附件"
        assert optional_requirement.findChild(
            QLabel, "materialOptionalState"
        ).text() == "暂无附件"
        assert optional_requirement.findChild(QLabel, "materialMissingState") is None
        assert window.item_detail_collection_progress.value() == 0
        assert window.item_detail_scroll_area.widget() is not None
        assert item.id > 0
    finally:
        window.close()
        database.dispose()


def test_item_detail_adds_attachment_and_refreshes_completeness(
    tmp_path, monkeypatch
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch_service = BatchService(database)
    batch = batch_service.create_batch(name="实验耗材")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W",
        total_amount_cents=12345,
    )
    storage = StoragePathService(tmp_path / "archive")
    attachment_service = AttachmentService(database, storage)
    completeness_service = CompletenessService(database, storage)
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"invoice")
    window = MainWindow(
        batch_service=batch_service,
        item_service=item_service,
        completeness_service=completeness_service,
        attachment_service=attachment_service,
    )
    try:
        window.navigation.setCurrentRow(2)
        window.all_items_table.cellDoubleClicked.emit(0, 0)
        add_button = _material_add_button(window, 2)
        monkeypatch.setattr(
            main_window.QFileDialog,
            "getOpenFileName",
            lambda *_args: (str(source), "支持的文件 (*.jpg *.jpeg *.png *.pdf)"),
        )

        add_button.click()

        assert (
            _attachment_cards(window, requirement_index=2)[0]
            .findChild(QLabel, "attachmentFilename")
            .toolTip()
            .endswith(".pdf")
        )
        assert window.item_detail_collection_count_label.text() == "1 / 4"
        assert window.item_detail_collection_percentage_label.text() == "25%"
        assert window.item_detail_completeness_label.text() == "缺少：实物照片、支付截图、订单截图"
        assert completeness_service.calculate(item.id).completed_count == 1
    finally:
        window.close()
        database.dispose()


def test_item_detail_uploading_last_missing_material_marks_complete(
    tmp_path, monkeypatch
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch_service = BatchService(database)
    batch = batch_service.create_batch(name="实验耗材")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W",
    )
    storage = StoragePathService(tmp_path / "archive")
    attachment_service = AttachmentService(database, storage)
    completeness_service = CompletenessService(database, storage)
    with database.transaction() as session:
        material_types = MaterialTypeRepository(session)
        material_type_ids = [
            material_types.get_by_code(code).id  # type: ignore[union-attr]
            for code in ("physical_photo", "payment_screenshot", "order_screenshot")
        ]
    for index, material_type_id in enumerate(material_type_ids, start=1):
        source = tmp_path / f"existing-{index}.png"
        source.write_bytes(f"existing-{index}".encode())
        attachment_service.add_attachment(
            item_id=item.id,
            material_type_id=material_type_id,
            source_path=source,
        )
    invoice = tmp_path / "invoice.pdf"
    invoice.write_bytes(b"invoice")
    window = MainWindow(
        batch_service=batch_service,
        item_service=item_service,
        completeness_service=completeness_service,
        attachment_service=attachment_service,
    )
    try:
        window.navigation.setCurrentRow(2)
        window.all_items_table.cellDoubleClicked.emit(0, 0)
        add_button = _material_add_button(window, 2)
        monkeypatch.setattr(
            main_window.QFileDialog,
            "getOpenFileName",
            lambda *_args: (str(invoice), "支持的文件 (*.jpg *.jpeg *.png *.pdf)"),
        )

        add_button.click()

        assert completeness_service.calculate(item.id).is_complete is True
        assert window.item_detail_collection_count_label.text() == "4 / 4"
        assert window.item_detail_collection_percentage_label.text() == "100%"
        assert window.item_detail_completeness_label.text() == "材料完整"
    finally:
        window.close()
        database.dispose()


def test_item_detail_cancelled_upload_has_no_side_effects(tmp_path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch_service = BatchService(database)
    batch = batch_service.create_batch(name="实验耗材")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W",
    )
    storage = StoragePathService(tmp_path / "archive")
    attachment_service = AttachmentService(database, storage)
    window = MainWindow(
        batch_service=batch_service,
        item_service=item_service,
        completeness_service=CompletenessService(database, storage),
        attachment_service=attachment_service,
    )
    try:
        window.navigation.setCurrentRow(2)
        window.all_items_table.cellDoubleClicked.emit(0, 0)
        add_button = _material_add_button(window, 0)
        monkeypatch.setattr(
            main_window.QFileDialog, "getOpenFileName", lambda *_args: ("", "")
        )

        add_button.click()

        assert attachment_service.list_attachments(item.id) == []
        assert _material_sections(window)[0].findChild(
            QLabel, "materialMissingState"
        ).text() == "缺少材料"
    finally:
        window.close()
        database.dispose()


def test_material_section_accepts_only_local_file_drags(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    section = main_window.MaterialDropSection()
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"invoice")

    local_mime = QMimeData()
    local_mime.setUrls([QUrl.fromLocalFile(str(source))])
    local_drag = QDragEnterEvent(
        QPoint(4, 4),
        Qt.DropAction.CopyAction,
        local_mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    section.dragEnterEvent(local_drag)

    assert local_drag.isAccepted()
    assert section.property("dropActive") is True

    section.dragLeaveEvent(QDragLeaveEvent())
    assert section.property("dropActive") is False

    remote_mime = QMimeData()
    remote_mime.setUrls([QUrl("https://example.com/invoice.pdf")])
    remote_drag = QDragEnterEvent(
        QPoint(4, 4),
        Qt.DropAction.CopyAction,
        remote_mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    section.dragEnterEvent(remote_drag)

    assert not remote_drag.isAccepted()
    assert section.property("dropActive") is False


def test_dropping_multiple_files_adds_them_to_target_material(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch_service = BatchService(database)
    batch = batch_service.create_batch(name="拖放附件")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W",
    )
    storage = StoragePathService(tmp_path / "archive")
    attachment_service = AttachmentService(database, storage)
    sources = [tmp_path / "invoice-front.pdf", tmp_path / "invoice-back.png"]
    for index, source in enumerate(sources):
        source.write_bytes(f"invoice-{index}".encode())
    window = MainWindow(
        batch_service=batch_service,
        item_service=item_service,
        completeness_service=CompletenessService(database, storage),
        attachment_service=attachment_service,
    )
    try:
        window.navigation.setCurrentRow(2)
        window.all_items_table.cellDoubleClicked.emit(0, 0)
        invoice_section = _material_sections(window)[2]
        invoice_material_type_id = invoice_section.property("materialTypeId")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(source)) for source in sources])
        event = QDropEvent(
            QPointF(4, 4),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        invoice_section.dropEvent(event)

        added = attachment_service.list_attachments(item.id)
        assert event.isAccepted()
        assert len(added) == 2
        assert {attachment.original_filename for attachment in added} == {
            source.name for source in sources
        }
        assert {
            attachment.material_type_id for attachment in added
        } == {invoice_material_type_id}
        assert len(_attachment_cards(window, requirement_index=2)) == 2
        assert window.item_detail_collection_count_label.text() == "1 / 4"
    finally:
        window.close()
        database.dispose()


def test_multi_file_add_continues_after_one_duplicate(tmp_path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application

    class PartialAttachmentService:
        def __init__(self) -> None:
            self.calls: list[Path] = []

        def add_attachment(self, *, source_path: Path, **_kwargs) -> object:
            self.calls.append(source_path)
            if source_path.name == "duplicate.pdf":
                raise main_window.DuplicateAttachmentError(1, "hash", 10)
            return object()

    service = PartialAttachmentService()
    warnings: list[tuple[str, str]] = []
    refreshed: list[int] = []
    monkeypatch.setattr(
        main_window.QMessageBox,
        "warning",
        lambda _parent, title, text: warnings.append((title, text)),
    )
    window = MainWindow(attachment_service=service)  # type: ignore[arg-type]
    monkeypatch.setattr(window, "_populate_item_detail", refreshed.append)
    sources = (tmp_path / "duplicate.pdf", tmp_path / "new.pdf")
    try:
        window._add_attachments(1, 3, sources)

        assert service.calls == list(sources)
        assert refreshed == [1]
        assert warnings == [
            (
                "部分附件未添加",
                "已添加 1 个文件，1 个文件未能添加：\n"
                "duplicate.pdf：该文件已经添加到这个报销物品。",
            )
        ]
    finally:
        window.close()


def test_item_detail_duplicate_upload_shows_friendly_error(tmp_path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch_service = BatchService(database)
    batch = batch_service.create_batch(name="实验耗材")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W",
    )
    storage = StoragePathService(tmp_path / "archive")
    attachment_service = AttachmentService(database, storage)
    with database.transaction() as session:
        photo = MaterialTypeRepository(session).get_by_code("physical_photo")
        assert photo is not None
        photo_id = photo.id
    source = tmp_path / "photo.png"
    source.write_bytes(b"photo")
    attachment_service.add_attachment(
        item_id=item.id, material_type_id=photo_id, source_path=source
    )
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main_window.QFileDialog,
        "getOpenFileName",
        lambda *_args: (str(source), "支持的文件 (*.jpg *.jpeg *.png *.pdf)"),
    )
    monkeypatch.setattr(
        main_window.QMessageBox,
        "warning",
        lambda _parent, title, text: warnings.append((title, text)),
    )
    window = MainWindow(
        batch_service=batch_service,
        item_service=item_service,
        completeness_service=CompletenessService(database, storage),
        attachment_service=attachment_service,
    )
    try:
        window.navigation.setCurrentRow(2)
        window.all_items_table.cellDoubleClicked.emit(0, 0)
        add_button = _material_add_button(window, 0)

        add_button.click()

        assert warnings == [("无法添加附件", "该文件已经添加到这个报销物品。")]
        assert len(attachment_service.list_attachments(item.id)) == 1
    finally:
        window.close()
        database.dispose()


def _material_sections(window: MainWindow) -> list[QFrame]:
    return window.item_detail_materials.findChildren(QFrame, "materialSection")


def _material_add_button(window: MainWindow, requirement_index: int) -> QPushButton:
    button = _material_sections(window)[requirement_index].findChild(
        QPushButton, "itemDetailAddAttachmentButton"
    )
    assert button is not None
    return button


def _attachment_cards(window: MainWindow, *, requirement_index: int) -> list[QFrame]:
    return _material_sections(window)[requirement_index].findChildren(
        QFrame, "attachmentCard"
    )


def _attachment_action_button(
    window: MainWindow,
    *,
    requirement_index: int,
    action_index: int,
    attachment_index: int = 0,
) -> QPushButton:
    cards = _attachment_cards(window, requirement_index=requirement_index)
    actions = cards[attachment_index].findChild(QWidget, "attachmentActions")
    assert actions is not None
    return actions.findChildren(QPushButton)[action_index]


class ExportServiceStub:
    def __init__(self, result: ItemExportResult | Exception) -> None:
        self.result = result
        self.calls: list[tuple[int, Path]] = []

    def export_item(self, item_id: int, destination: Path) -> ItemExportResult:
        self.calls.append((item_id, destination))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _create_item_detail_for_export(
    tmp_path: Path, exporter: ExportServiceStub, *, ready: bool
) -> tuple[MainWindow, DatabaseManager, int]:
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch = BatchService(database).create_batch(name="导出测试")
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
    if ready:
        with database.transaction() as session:
            material_types = MaterialTypeRepository(session)
            material_type_ids = {
                code: material_types.get_by_code(code).id  # type: ignore[union-attr]
                for code in (
                    "physical_photo",
                    "payment_screenshot",
                    "invoice",
                    "order_screenshot",
                )
            }
        for code, suffix in (
            ("physical_photo", ".png"),
            ("payment_screenshot", ".png"),
            ("invoice", ".pdf"),
            ("order_screenshot", ".png"),
        ):
            source = tmp_path / f"{code}{suffix}"
            if suffix == ".png":
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
            else:
                source.write_bytes(b"invoice")
            attachments.add_attachment(
                item_id=item.id,
                material_type_id=material_type_ids[code],
                source_path=source,
            )
        PaymentScreenshotMergeService(database, storage).generate(item.id)

    window = MainWindow(
        batch_service=BatchService(database),
        item_service=item_service,
        completeness_service=CompletenessService(database, storage),
        attachment_service=attachments,
        submission_readiness_service=SubmissionReadinessService(database, storage),
        export_service=exporter,  # type: ignore[arg-type]
    )
    window.navigation.setCurrentRow(2)
    window.all_items_table.cellDoubleClicked.emit(0, 0)
    return window, database, item.id


def _create_item_detail_workflow_window(
    tmp_path: Path, status: ReimbursementStatus
) -> tuple[MainWindow, DatabaseManager, int]:
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch = BatchService(database).create_batch(name="2026年8月实验耗材")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W",
        purchase_date=date(2026, 8, 20),
        platform="淘宝",
        merchant="示例商家",
        order_number="ORDER-007",
        total_amount_cents=18000,
    )
    if status is not ReimbursementStatus.COLLECTING:
        with database.transaction() as session:
            stored_item = session.get(Item, item.id)
            assert stored_item is not None
            stored_item.status = status
    storage = StoragePathService(tmp_path / "archive")
    completeness = CompletenessService(database, storage)
    submission = SubmissionReadinessService(database, storage)
    window = MainWindow(
        batch_service=BatchService(database),
        item_service=item_service,
        completeness_service=completeness,
        submission_readiness_service=submission,
        workflow_service=WorkflowService(database, submission),
    )
    window._populate_item_detail(item.id)
    return window, database, item.id


@pytest.mark.parametrize(
    ("status", "status_text", "status_key", "next_action"),
    (
        (ReimbursementStatus.COLLECTING, "待补材料", "incomplete", "标记已提交"),
        (ReimbursementStatus.SUBMITTED, "已提交", "submitted", "标记已报销"),
        (ReimbursementStatus.REIMBURSED, "已报销", "reimbursed", "归档"),
        (ReimbursementStatus.ARCHIVED, "已归档", "archived", None),
    ),
)
def test_item_detail_header_and_workflow_card_follow_status(
    tmp_path,
    status: ReimbursementStatus,
    status_text: str,
    status_key: str,
    next_action: str | None,
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    window, database, _item_id = _create_item_detail_workflow_window(tmp_path, status)
    try:
        assert window.item_detail_name_label.text() == "树莓派 Zero 2 W"
        assert window.item_detail_amount_label.text() == "¥180.00"
        assert window.item_detail_primary_metadata_label.text() == "淘宝 · 2026-08-20"
        assert window.item_detail_merchant_label.text() == "商家：示例商家"
        assert window.item_detail_order_number_label.text() == "订单号：ORDER-007"
        assert window.item_detail_batch_label.text() == "所属批次：2026年8月实验耗材"
        assert window.item_detail_status_label.text() == status_text
        assert window.item_detail_status_label.property("status") == status_key
        assert window.item_detail_collection_count_label.text() == "0 / 4"
        assert window.item_detail_completeness_label.text().startswith("缺少：")
        assert window.item_detail_submission_count_label.text() == "0 / 3"
        assert window.item_detail_submission_readiness_label.text().startswith("缺少：")
        assert window.item_detail_workflow_button.isHidden() is (next_action is None)
        if next_action is not None:
            assert window.item_detail_workflow_button.text() == next_action
    finally:
        window.close()
        database.dispose()


def test_item_detail_unready_submission_confirms_then_refreshes_workflow(
    tmp_path, monkeypatch
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    window, database, _item_id = _create_item_detail_workflow_window(
        tmp_path, ReimbursementStatus.COLLECTING
    )
    questions: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main_window.QMessageBox,
        "question",
        lambda _parent, title, text, *_args: (
            questions.append((title, text)) or QMessageBox.StandardButton.Yes
        ),
    )
    try:
        window.item_detail_workflow_button.click()

        assert questions and questions[0][0] == "提交材料不完整"
        assert "缺：" in questions[0][1]
        assert window.item_detail_status_label.text() == "已提交"
        assert window.item_detail_workflow_button.text() == "标记已报销"
    finally:
        window.close()
        database.dispose()


def test_item_detail_exports_ready_submission_materials(tmp_path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    destination = tmp_path / "export"
    expected_output = destination / "001_树莓派Zero2W"
    exporter = ExportServiceStub(
        ItemExportResult(1, expected_output, (expected_output / "发票.pdf",))
    )
    window, database, item_id = _create_item_detail_for_export(tmp_path, exporter, ready=True)
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(main_window.QFileDialog, "getExistingDirectory", lambda *_args: str(destination))
    monkeypatch.setattr(
        main_window.QMessageBox,
        "information",
        lambda _parent, title, text: messages.append((title, text)),
    )
    try:
        assert window.export_submission_materials_button.isEnabled()
        window.export_submission_materials_button.click()

        assert exporter.calls == [(item_id, destination)]
        assert messages == [("导出完成", f"提交材料导出成功。\n已导出到：{expected_output}")]
    finally:
        window.close()
        database.dispose()


def test_all_items_page_shows_distinct_empty_states(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch_service = BatchService(database)
    item_service = ItemService(database)
    completeness_service = CompletenessService(database, StoragePathService(tmp_path))
    window = MainWindow(
        batch_service=batch_service,
        item_service=item_service,
        completeness_service=completeness_service,
    )
    try:
        window.navigation.setCurrentRow(2)
        assert window.all_items_table.rowCount() == 0
        assert not window.all_items_empty_state.isHidden()
        assert window.all_items_empty_title.text() == "暂无报销物品"
        assert (
            window.all_items_empty_description.text()
            == "创建报销批次并添加物品后，它们会出现在这里。"
        )
    finally:
        window.close()
        database.dispose()


def test_item_detail_export_cancel_does_not_call_service(tmp_path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    exporter = ExportServiceStub(ItemExportResult(1, tmp_path / "unused", ()))
    window, database, _item_id = _create_item_detail_for_export(tmp_path, exporter, ready=True)
    monkeypatch.setattr(main_window.QFileDialog, "getExistingDirectory", lambda *_args: "")
    try:
        window.export_submission_materials_button.click()
        assert exporter.calls == []
    finally:
        window.close()
        database.dispose()


def test_item_detail_export_is_disabled_when_submission_is_not_ready(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    exporter = ExportServiceStub(ItemExportResult(1, tmp_path / "unused", ()))
    window, database, _item_id = _create_item_detail_for_export(tmp_path, exporter, ready=False)
    try:
        assert not window.export_submission_materials_button.isEnabled()
        assert "缺少：实物照片" in window.item_detail_submission_readiness_label.text()
        window.export_submission_materials_button.click()
        assert exporter.calls == []
    finally:
        window.close()
        database.dispose()


def test_item_detail_export_existing_target_shows_friendly_error(tmp_path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    destination = tmp_path / "export"
    exporter = ExportServiceStub(ExportTargetExistsError(destination / "001_树莓派Zero2W"))
    window, database, _item_id = _create_item_detail_for_export(tmp_path, exporter, ready=True)
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(main_window.QFileDialog, "getExistingDirectory", lambda *_args: str(destination))
    monkeypatch.setattr(main_window.QMessageBox, "warning", lambda _parent, title, text: warnings.append((title, text)))
    try:
        window.export_submission_materials_button.click()
        assert warnings == [("无法导出提交材料", "目标导出目录已存在，请选择其他目录或先处理旧导出结果。")]
    finally:
        window.close()
        database.dispose()


def test_item_detail_export_failure_shows_friendly_error(tmp_path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    exporter = ExportServiceStub(ExportServiceError("copy failed"))
    window, database, _item_id = _create_item_detail_for_export(tmp_path, exporter, ready=True)
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(main_window.QFileDialog, "getExistingDirectory", lambda *_args: str(tmp_path / "export"))
    monkeypatch.setattr(main_window.QMessageBox, "warning", lambda _parent, title, text: warnings.append((title, text)))
    try:
        window.export_submission_materials_button.click()
        assert warnings == [("无法导出提交材料", "导出失败，请确认附件可访问后重试。")]
    finally:
        window.close()
        database.dispose()


class BatchExportServiceStub:
    def __init__(
        self,
        result: BatchExportResult | Exception,
        forced_result: BatchExportResult | Exception | None = None,
    ) -> None:
        self.result = result
        self.calls: list[tuple[int, Path]] = []
        self.force_calls: list[tuple[int, Path]] = []
        self.zip_calls: list[tuple[int, Path]] = []
        self.zip_force_calls: list[tuple[int, Path]] = []
        self.forced_result = forced_result

    def export_batch(
        self, batch_id: int, destination: Path, *, force: bool = False
    ) -> BatchExportResult:
        if force:
            self.force_calls.append((batch_id, destination))
            result = self.forced_result
        else:
            self.calls.append((batch_id, destination))
            result = self.result
        if isinstance(result, Exception):
            raise result
        assert result is not None
        return result

    def export_batch_zip(
        self, batch_id: int, destination: Path, *, force: bool = False
    ) -> BatchExportResult:
        if force:
            self.zip_force_calls.append((batch_id, destination))
            result = self.forced_result
        else:
            self.zip_calls.append((batch_id, destination))
            result = self.result
        if isinstance(result, Exception):
            raise result
        assert result is not None
        return result


def _create_batch_detail_for_export(
    exporter: BatchExportServiceStub, *, has_items: bool = True
) -> tuple[MainWindow, DatabaseManager, int]:
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch_service = BatchService(database)
    batch = batch_service.create_batch(name="批次导出测试")
    if has_items:
        template = TemplateService(database).ensure_default_template()
        ItemService(database).create_item(
            batch_id=batch.id,
            template_id=template.id,
            sequence_number=1,
            name="树莓派 Zero 2 W",
        )
    window = MainWindow(
        batch_service=batch_service,
        export_service=exporter,  # type: ignore[arg-type]
    )
    window.batch_table.cellDoubleClicked.emit(0, 0)
    window._choose_batch_export_format = lambda: "directory"
    return window, database, batch.id


def test_batch_detail_exports_ready_batch(tmp_path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    destination = tmp_path / "export"
    expected_output = destination / "批次导出测试"
    exporter = BatchExportServiceStub(
        BatchExportResult(1, expected_output, item_count=5, file_count=17)
    )
    window, database, batch_id = _create_batch_detail_for_export(exporter)
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(main_window.QFileDialog, "getExistingDirectory", lambda *_args: str(destination))
    monkeypatch.setattr(main_window.QMessageBox, "information", lambda _parent, title, text: messages.append((title, text)))
    try:
        window.export_batch_materials_button.click()

        assert exporter.calls == [(batch_id, destination)]
        assert messages == [(
            "导出完成",
            f"批次报销材料导出成功。\n已导出到：{expected_output}\n已导出 5 个物品，共 17 个文件。",
        )]
    finally:
        window.close()
        database.dispose()


def test_batch_detail_exports_zip_with_zip_service(tmp_path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    destination = tmp_path / "export"
    expected_output = destination / "批次导出测试.zip"
    exporter = BatchExportServiceStub(
        BatchExportResult(
            1, expected_output, item_count=5, file_count=17, export_format="zip"
        )
    )
    window, database, batch_id = _create_batch_detail_for_export(exporter)
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(window, "_choose_batch_export_format", lambda: "zip")
    monkeypatch.setattr(main_window.QFileDialog, "getExistingDirectory", lambda *_args: str(destination))
    monkeypatch.setattr(main_window.QMessageBox, "information", lambda _parent, title, text: messages.append((title, text)))
    try:
        window.export_batch_materials_button.click()

        assert exporter.calls == []
        assert exporter.zip_calls == [(batch_id, destination)]
        assert messages[0][0] == "导出完成"
        assert "批次 ZIP 导出成功。" in messages[0][1]
    finally:
        window.close()
        database.dispose()


def test_batch_detail_export_cancel_does_not_call_service(tmp_path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    exporter = BatchExportServiceStub(BatchExportResult(1, tmp_path / "unused", 0, 0))
    window, database, _batch_id = _create_batch_detail_for_export(exporter)
    monkeypatch.setattr(main_window.QFileDialog, "getExistingDirectory", lambda *_args: "")
    try:
        window.export_batch_materials_button.click()
        assert exporter.calls == []
    finally:
        window.close()
        database.dispose()


def test_batch_detail_export_cancel_does_not_force_export(tmp_path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    incomplete = BatchSubmissionMaterialsIncompleteError((
        IncompleteBatchExportItem(1, 1, "树莓派 Zero 2 W", ("合并支付截图",)),
        IncompleteBatchExportItem(2, 2, "SD卡", ("发票",)),
    ))
    exporter = BatchExportServiceStub(incomplete)
    window, database, _batch_id = _create_batch_detail_for_export(exporter)
    monkeypatch.setattr(main_window.QFileDialog, "getExistingDirectory", lambda *_args: str(tmp_path / "export"))
    monkeypatch.setattr(window, "_confirm_force_batch_export", lambda _details: False)
    try:
        window.export_batch_materials_button.click()

        assert exporter.calls == [(window._current_batch_entry.id, tmp_path / "export")]
        assert exporter.force_calls == []
    finally:
        window.close()
        database.dispose()


def test_batch_detail_export_confirmed_force_export_uses_batch_and_destination(
    tmp_path, monkeypatch
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    destination = tmp_path / "export"
    incomplete = BatchSubmissionMaterialsIncompleteError((
        IncompleteBatchExportItem(1, 1, "树莓派 Zero 2 W", ("合并支付截图",)),
    ))
    forced = BatchExportResult(
        1, destination / "批次导出测试", item_count=1, file_count=2,
        forced=True,
    )
    exporter = BatchExportServiceStub(incomplete, forced)
    window, database, batch_id = _create_batch_detail_for_export(exporter)
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(main_window.QFileDialog, "getExistingDirectory", lambda *_args: str(destination))
    monkeypatch.setattr(window, "_confirm_force_batch_export", lambda _details: True)
    monkeypatch.setattr(main_window.QMessageBox, "information", lambda _parent, title, text: messages.append((title, text)))
    try:
        window.export_batch_materials_button.click()

        assert exporter.calls == [(batch_id, destination)]
        assert exporter.force_calls == [(batch_id, destination)]
        assert messages[0][0] == "强制导出完成"
        assert "导出结果.txt" in messages[0][1]
    finally:
        window.close()
        database.dispose()


def test_batch_detail_export_existing_target_shows_friendly_error(tmp_path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    destination = tmp_path / "export"
    exporter = BatchExportServiceStub(ExportTargetExistsError(destination / "批次导出测试"))
    window, database, _batch_id = _create_batch_detail_for_export(exporter)
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(main_window.QFileDialog, "getExistingDirectory", lambda *_args: str(destination))
    monkeypatch.setattr(main_window.QMessageBox, "warning", lambda _parent, title, text: warnings.append((title, text)))
    try:
        window.export_batch_materials_button.click()
        assert warnings == [("无法导出报销材料", "目标批次导出目录已存在，请选择其他目录或先处理旧导出结果。")]
    finally:
        window.close()
        database.dispose()


def test_batch_detail_export_empty_batch_shows_friendly_error(tmp_path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    exporter = BatchExportServiceStub(EmptyBatchExportError(1))
    window, database, _batch_id = _create_batch_detail_for_export(exporter, has_items=False)
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(main_window.QFileDialog, "getExistingDirectory", lambda *_args: str(tmp_path / "export"))
    monkeypatch.setattr(main_window.QMessageBox, "warning", lambda _parent, title, text: warnings.append((title, text)))
    try:
        window.export_batch_materials_button.click()
        assert warnings == [("无法导出报销材料", "当前批次没有可导出的物品。")]
    finally:
        window.close()
        database.dispose()


def test_item_detail_attachment_open_actions_use_attachment_path_and_handle_missing_file(
    tmp_path, monkeypatch
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch = BatchService(database).create_batch(name="附件操作")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=1, name="树莓派"
    )
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    with database.transaction() as session:
        photo = MaterialTypeRepository(session).get_by_code("physical_photo")
        assert photo is not None
        photo_id = photo.id
    source = tmp_path / "photo.png"
    source.write_bytes(b"photo")
    attachment = attachments.add_attachment(
        item_id=item.id, material_type_id=photo_id, source_path=source
    )
    opened: list[str] = []
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main_window.QMessageBox,
        "warning",
        lambda _parent, title, text: warnings.append((title, text)),
    )
    window = MainWindow(
        batch_service=BatchService(database),
        item_service=item_service,
        completeness_service=CompletenessService(database, storage),
        attachment_service=attachments,
        desktop_integration_service=DesktopIntegrationService(startfile=opened.append),
    )
    try:
        window.navigation.setCurrentRow(2)
        window.all_items_table.cellDoubleClicked.emit(0, 0)

        _attachment_action_button(window, requirement_index=0, action_index=0).click()
        _attachment_action_button(window, requirement_index=0, action_index=1).click()

        target = storage.resolve_relative_path(attachment.relative_path)
        assert opened == [str(target), str(target.parent)]

        target.unlink()
        _attachment_action_button(window, requirement_index=0, action_index=0).click()
        assert warnings == [("\u65e0\u6cd5\u6253\u5f00\u9644\u4ef6", "\u9644\u4ef6\u6587\u4ef6\u4e0d\u5b58\u5728\u6216\u5df2\u88ab\u79fb\u52a8\u3002")]
    finally:
        window.close()
        database.dispose()


def test_item_detail_removing_unique_invoice_refreshes_collection_and_submission(
    tmp_path, monkeypatch
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch = BatchService(database).create_batch(name="删除附件")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=1, name="树莓派"
    )
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    with database.transaction() as session:
        material_types = MaterialTypeRepository(session)
        material_type_ids = {
            code: material_types.get_by_code(code).id  # type: ignore[union-attr]
            for code in ("physical_photo", "payment_screenshot", "invoice", "order_screenshot")
        }
    for code, suffix in (("physical_photo", ".png"), ("payment_screenshot", ".png"), ("invoice", ".pdf"), ("order_screenshot", ".png")):
        source = tmp_path / f"{code}{suffix}"
        if suffix == ".png":
            image = QImage(2, 2, QImage.Format.Format_RGB32)
            image.fill(QColor({"physical_photo": "red", "payment_screenshot": "blue", "order_screenshot": "green"}[code]))
            assert image.save(str(source), "PNG")
        else:
            source.write_bytes(code.encode())
        attachments.add_attachment(
            item_id=item.id, material_type_id=material_type_ids[code], source_path=source
        )
    PaymentScreenshotMergeService(database, storage).generate(item.id)
    completeness = CompletenessService(database, storage)
    submission = SubmissionReadinessService(database, storage)
    window = MainWindow(
        batch_service=BatchService(database),
        item_service=item_service,
        completeness_service=completeness,
        attachment_service=attachments,
        submission_readiness_service=submission,
    )
    monkeypatch.setattr(
        main_window.QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )
    try:
        window.navigation.setCurrentRow(2)
        window.all_items_table.cellDoubleClicked.emit(0, 0)
        _attachment_action_button(window, requirement_index=2, action_index=2).click()

        assert (completeness.calculate(item.id).completed_count, completeness.calculate(item.id).required_count) == (3, 4)
        assert (submission.calculate(item.id).completed_count, submission.calculate(item.id).required_count) == (2, 3)
        assert [entry.name for entry in submission.calculate(item.id).missing] == ["\u53d1\u7968"]
        assert window.item_detail_collection_count_label.text() == "3 / 4"
        assert window.item_detail_completeness_label.text() == "缺少：发票"
    finally:
        window.close()
        database.dispose()


def test_item_detail_removing_merged_payment_keeps_collection_but_updates_submission(
    tmp_path, monkeypatch
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch = BatchService(database).create_batch(name="合并文件")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=1, name="树莓派"
    )
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    with database.transaction() as session:
        material_types = MaterialTypeRepository(session)
        material_type_ids = {
            code: material_types.get_by_code(code).id  # type: ignore[union-attr]
            for code in ("physical_photo", "payment_screenshot", "invoice", "order_screenshot")
        }
    for code in material_type_ids:
        source = tmp_path / f"{code}.png"
        if code == "invoice":
            source = tmp_path / "invoice.pdf"
            source.write_bytes(b"invoice")
        else:
            image = QImage(2, 2, QImage.Format.Format_RGB32)
            image.fill(QColor({"physical_photo": "red", "payment_screenshot": "blue", "order_screenshot": "green"}[code]))
            assert image.save(str(source), "PNG")
        attachments.add_attachment(
            item_id=item.id, material_type_id=material_type_ids[code], source_path=source
        )
    PaymentScreenshotMergeService(database, storage).generate(item.id)
    completeness = CompletenessService(database, storage)
    submission = SubmissionReadinessService(database, storage)
    monkeypatch.setattr(main_window.QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    window = MainWindow(
        batch_service=BatchService(database), item_service=item_service,
        completeness_service=completeness, attachment_service=attachments,
        submission_readiness_service=submission,
    )
    try:
        window.navigation.setCurrentRow(2)
        window.all_items_table.cellDoubleClicked.emit(0, 0)
        merged_card = next(
            card
            for card in _attachment_cards(window, requirement_index=1)
            if "\u5408\u5e76\u63d0\u4ea4\u6587\u4ef6"
            in card.findChild(QLabel, "attachmentFilename").toolTip()
        )
        actions = merged_card.findChild(QWidget, "attachmentActions")
        assert actions is not None
        next(button for button in actions.findChildren(QPushButton) if button.text() == "\u5220\u9664").click()

        assert (completeness.calculate(item.id).completed_count, completeness.calculate(item.id).required_count) == (4, 4)
        assert (submission.calculate(item.id).completed_count, submission.calculate(item.id).required_count) == (2, 3)
        assert [entry.name for entry in submission.calculate(item.id).missing] == ["\u5408\u5e76\u652f\u4ed8\u622a\u56fe"]
    finally:
        window.close()
        database.dispose()


def test_item_detail_removing_one_of_multiple_photos_keeps_material_complete(
    tmp_path, monkeypatch
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch = BatchService(database).create_batch(name="多附件")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=1, name="树莓派"
    )
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    with database.transaction() as session:
        photo = MaterialTypeRepository(session).get_by_code("physical_photo")
        assert photo is not None
        photo_id = photo.id
    for index in (1, 2):
        source = tmp_path / f"photo-{index}.png"
        source.write_bytes(f"photo-{index}".encode())
        attachments.add_attachment(item_id=item.id, material_type_id=photo_id, source_path=source)
    completeness = CompletenessService(database, storage)
    monkeypatch.setattr(main_window.QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    window = MainWindow(
        batch_service=BatchService(database), item_service=item_service,
        completeness_service=completeness, attachment_service=attachments,
    )
    try:
        window.navigation.setCurrentRow(2)
        window.all_items_table.cellDoubleClicked.emit(0, 0)
        _attachment_action_button(window, requirement_index=0, action_index=2).click()

        assert len(attachments.list_attachments(item.id)) == 1
        assert _material_sections(window)[0].findChild(
            QLabel, "materialAttachmentCount"
        ).text() == "1 个附件"
        assert completeness.calculate(item.id).completed_count == 1
    finally:
        window.close()
        database.dispose()


def test_item_detail_image_attachments_show_thumbnails_filenames_and_open(
    tmp_path
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch = BatchService(database).create_batch(name="图片附件")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=1, name="树莓派"
    )
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    with database.transaction() as session:
        photo = MaterialTypeRepository(session).get_by_code("physical_photo")
        assert photo is not None
        photo_id = photo.id
    created = []
    for filename, image_format, color in (
        ("photo.png", "PNG", "red"),
        ("photo.jpg", "JPG", "blue"),
    ):
        source = tmp_path / filename
        image = QImage(24, 16, QImage.Format.Format_RGB32)
        image.fill(QColor(color))
        assert image.save(str(source), image_format)
        created.append(
            attachments.add_attachment(
                item_id=item.id, material_type_id=photo_id, source_path=source
            )
        )
    opened: list[str] = []
    window = MainWindow(
        batch_service=BatchService(database),
        item_service=item_service,
        completeness_service=CompletenessService(database, storage),
        attachment_service=attachments,
        desktop_integration_service=DesktopIntegrationService(startfile=opened.append),
    )
    try:
        window.navigation.setCurrentRow(2)
        window.all_items_table.cellDoubleClicked.emit(0, 0)
        cards = _attachment_cards(window, requirement_index=0)
        assert len(cards) == 2
        assert all(card.findChild(QPushButton, "attachmentThumbnail") for card in cards)
        assert {card.findChild(QLabel, "attachmentFilename").toolTip() for card in cards} == {
            attachment.stored_filename for attachment in created
        }

        cards[0].findChild(QPushButton, "attachmentThumbnail").click()
        assert opened == [str(storage.resolve_relative_path(created[0].relative_path))]
    finally:
        window.close()
        database.dispose()


def test_item_detail_pdf_card_keeps_attachment_actions(tmp_path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch = BatchService(database).create_batch(name="PDF 附件")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=1, name="树莓派"
    )
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    with database.transaction() as session:
        invoice = MaterialTypeRepository(session).get_by_code("invoice")
        assert invoice is not None
        invoice_id = invoice.id
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"invoice")
    attachment = attachments.add_attachment(
        item_id=item.id, material_type_id=invoice_id, source_path=source
    )
    opened: list[str] = []
    monkeypatch.setattr(
        main_window.QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )
    window = MainWindow(
        batch_service=BatchService(database),
        item_service=item_service,
        completeness_service=CompletenessService(database, storage),
        attachment_service=attachments,
        desktop_integration_service=DesktopIntegrationService(startfile=opened.append),
    )
    try:
        window.navigation.setCurrentRow(2)
        window.all_items_table.cellDoubleClicked.emit(0, 0)
        card = _attachment_cards(window, requirement_index=2)[0]
        assert card.findChild(QLabel, "attachmentPdfBadge").text() == "PDF"
        assert card.findChild(QPushButton, "attachmentThumbnail") is None

        _attachment_action_button(window, requirement_index=2, action_index=0).click()
        _attachment_action_button(window, requirement_index=2, action_index=1).click()
        target = storage.resolve_relative_path(attachment.relative_path)
        assert opened == [str(target), str(target.parent)]
        _attachment_action_button(window, requirement_index=2, action_index=2).click()
        assert attachments.list_attachments(item.id) == []
    finally:
        window.close()
        database.dispose()


def test_item_detail_generic_file_uses_file_card(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch = BatchService(database).create_batch(name="通用附件")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=1, name="树莓派"
    )
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    with database.transaction() as session:
        invoice = MaterialTypeRepository(session).get_by_code("invoice")
        assert invoice is not None
        invoice_id = invoice.id
    source = tmp_path / "scan.webp"
    source.write_bytes(b"not-a-decodable-image")
    attachment = attachments.add_attachment(
        item_id=item.id, material_type_id=invoice_id, source_path=source
    )
    window = MainWindow(
        batch_service=BatchService(database),
        item_service=item_service,
        completeness_service=CompletenessService(database, storage),
        attachment_service=attachments,
    )
    try:
        window.navigation.setCurrentRow(2)
        window.all_items_table.cellDoubleClicked.emit(0, 0)
        card = _attachment_cards(window, requirement_index=2)[0]
        assert card.findChild(QLabel, "attachmentFileBadge").text() == "文件"
        assert card.findChild(QPushButton, "attachmentThumbnail") is None
        assert card.findChild(QLabel, "attachmentFilename").toolTip() == (
            attachment.stored_filename
        )
    finally:
        window.close()
        database.dispose()


def test_item_detail_missing_attachment_shows_missing_file_card(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch = BatchService(database).create_batch(name="缺失附件")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=1, name="树莓派"
    )
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    with database.transaction() as session:
        photo = MaterialTypeRepository(session).get_by_code("physical_photo")
        assert photo is not None
        photo_id = photo.id
    source = tmp_path / "photo.png"
    image = QImage(24, 16, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    assert image.save(str(source), "PNG")
    attachment = attachments.add_attachment(
        item_id=item.id, material_type_id=photo_id, source_path=source
    )
    storage.resolve_relative_path(attachment.relative_path).unlink()
    window = MainWindow(
        batch_service=BatchService(database),
        item_service=item_service,
        completeness_service=CompletenessService(database, storage),
        attachment_service=attachments,
    )
    try:
        window.navigation.setCurrentRow(2)
        window.all_items_table.cellDoubleClicked.emit(0, 0)
        card = _attachment_cards(window, requirement_index=0)[0]
        assert card.findChild(QLabel, "attachmentMissingFile").text() == "文件缺失"
        assert card.findChild(QPushButton, "attachmentThumbnail") is None
    finally:
        window.close()
        database.dispose()


def test_item_detail_derived_png_shows_thumbnail(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch = BatchService(database).create_batch(name="合并支付截图")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=1, name="树莓派"
    )
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    with database.transaction() as session:
        material_types = MaterialTypeRepository(session)
        payment = material_types.get_by_code("payment_screenshot")
        order = material_types.get_by_code("order_screenshot")
        assert payment is not None and order is not None
    for filename, material_type_id, color in (
        ("payment.png", payment.id, "blue"),
        ("order.png", order.id, "green"),
    ):
        source = tmp_path / filename
        image = QImage(24, 16, QImage.Format.Format_RGB32)
        image.fill(QColor(color))
        assert image.save(str(source), "PNG")
        attachments.add_attachment(
            item_id=item.id, material_type_id=material_type_id, source_path=source
        )
    PaymentScreenshotMergeService(database, storage).generate(item.id)
    window = MainWindow(
        batch_service=BatchService(database),
        item_service=item_service,
        completeness_service=CompletenessService(database, storage),
        attachment_service=attachments,
    )
    try:
        window.navigation.setCurrentRow(2)
        window.all_items_table.cellDoubleClicked.emit(0, 0)
        derived_card = next(
            card
            for card in _attachment_cards(window, requirement_index=1)
            if "合并提交文件" in card.findChild(QLabel, "attachmentFilename").toolTip()
        )
        assert derived_card.findChild(QPushButton, "attachmentThumbnail") is not None
    finally:
        window.close()
        database.dispose()


def _create_payment_merge_detail(
    tmp_path: Path,
    *,
    order_suffix: str = ".png",
    payment_suffix: str = ".png",
    include_order: bool = True,
    include_payment: bool = True,
    include_submission_materials: bool = False,
) -> tuple[MainWindow, DatabaseManager, AttachmentService, int]:
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch = BatchService(database).create_batch(name="合并支付截图 UI")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=1, name="树莓派"
    )
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    with database.transaction() as session:
        material_types = MaterialTypeRepository(session)
        material_type_ids = {
            code: material_types.get_by_code(code).id  # type: ignore[union-attr]
            for code in (
                "physical_photo",
                "invoice",
                "order_screenshot",
                "payment_screenshot",
            )
        }

    def add_attachment(code: str, suffix: str, color: str) -> None:
        source = tmp_path / f"{code}{suffix}"
        if suffix == ".pdf":
            source.write_bytes(b"pdf")
        else:
            image = QImage(24, 16, QImage.Format.Format_RGB32)
            image.fill(QColor(color))
            assert image.save(str(source), "PNG")
        attachments.add_attachment(
            item_id=item.id,
            material_type_id=material_type_ids[code],
            source_path=source,
        )

    if include_order:
        add_attachment("order_screenshot", order_suffix, "green")
    if include_payment:
        add_attachment("payment_screenshot", payment_suffix, "blue")
    if include_submission_materials:
        add_attachment("physical_photo", ".png", "red")
        add_attachment("invoice", ".pdf", "white")
    completeness = CompletenessService(database, storage)
    window = MainWindow(
        batch_service=BatchService(database),
        item_service=item_service,
        completeness_service=completeness,
        attachment_service=attachments,
        payment_screenshot_merge_service=PaymentScreenshotMergeService(database, storage),
        submission_readiness_service=SubmissionReadinessService(database, storage),
    )
    window.navigation.setCurrentRow(2)
    window.all_items_table.cellDoubleClicked.emit(0, 0)
    return window, database, attachments, item.id


def test_payment_merge_section_shows_latest_source_thumbnails_and_empty_result(
    tmp_path
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    window, database, attachments, item_id = _create_payment_merge_detail(tmp_path)
    try:
        with database.transaction() as session:
            payment = MaterialTypeRepository(session).get_by_code("payment_screenshot")
            assert payment is not None
        newer = tmp_path / "payment-newer.png"
        image = QImage(24, 16, QImage.Format.Format_RGB32)
        image.fill(QColor("yellow"))
        assert image.save(str(newer), "PNG")
        latest = attachments.add_attachment(
            item_id=item_id, material_type_id=payment.id, source_path=newer
        )
        window._populate_item_detail(item_id)

        order_card = window.merged_payment_section.findChild(QFrame, "mergeOrderSource")
        payment_card = window.merged_payment_section.findChild(QFrame, "mergePaymentSource")
        assert order_card is not None and payment_card is not None
        assert order_card.findChild(QPushButton, "attachmentThumbnail") is not None
        assert payment_card.findChild(QPushButton, "attachmentThumbnail") is not None
        assert payment_card.findChild(QLabel, "mergedPaymentSourceFilename").text() == latest.stored_filename
        assert window.merged_payment_section.findChild(QLabel, "mergedPaymentSectionTitle").text() == "支付凭证"
        assert window.merged_payment_section.findChild(QLabel, "mergedPaymentSectionDescription").text() == "订单截图与支付截图将合并为最终提交用的支付截图"
        assert window.merged_payment_section.findChild(QLabel, "mergedPaymentEmpty").text() == "尚未生成合并支付截图"
        assert window.generate_merged_payment_screenshot_button.text() == "生成支付截图"
    finally:
        window.close()
        database.dispose()


@pytest.mark.parametrize(
    ("include_order", "include_payment", "order_suffix", "payment_suffix", "expected"),
    [
        (False, True, ".png", ".png", "缺少订单截图"),
        (True, False, ".png", ".png", "缺少支付截图"),
        (True, True, ".pdf", ".png", "当前附件不是可直接合并的图片"),
    ],
)
def test_payment_merge_section_shows_missing_or_unsupported_sources(
    tmp_path,
    include_order: bool,
    include_payment: bool,
    order_suffix: str,
    payment_suffix: str,
    expected: str,
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    window, database, _attachments, _item_id = _create_payment_merge_detail(
        tmp_path,
        include_order=include_order,
        include_payment=include_payment,
        order_suffix=order_suffix,
        payment_suffix=payment_suffix,
    )
    try:
        labels = window.merged_payment_section.findChildren(QLabel)
        assert expected in [label.text() for label in labels]
        if order_suffix == ".pdf":
            order_card = window.merged_payment_section.findChild(QFrame, "mergeOrderSource")
            assert order_card is not None
            assert order_card.findChild(QLabel, "mergedPaymentSourceFilename") is not None
        assert not window.generate_merged_payment_screenshot_button.isEnabled()
    finally:
        window.close()
        database.dispose()


def test_payment_merge_section_regenerates_and_shows_latest_result(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    window, database, attachments, item_id = _create_payment_merge_detail(tmp_path)
    try:
        window.generate_merged_payment_screenshot_button.click()
        first = [attachment for attachment in attachments.list_attachments(item_id) if attachment.is_derived]
        assert len(first) == 1
        assert window.generate_merged_payment_screenshot_button.text() == "重新生成"

        window.generate_merged_payment_screenshot_button.click()
        derived = [attachment for attachment in attachments.list_attachments(item_id) if attachment.is_derived]
        latest = derived[-1]
        result_card = window.merged_payment_section.findChild(QFrame, "attachmentCard")
        assert len(derived) == 2
        assert result_card is not None
        assert result_card.findChild(QPushButton, "attachmentThumbnail") is not None
        assert latest.stored_filename in result_card.findChild(QLabel, "attachmentFilename").toolTip()
    finally:
        window.close()
        database.dispose()


def test_payment_merge_section_delete_refreshes_submission_readiness(
    tmp_path, monkeypatch
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    window, database, attachments, item_id = _create_payment_merge_detail(
        tmp_path, include_submission_materials=True
    )
    monkeypatch.setattr(
        main_window.QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )
    try:
        assert window.item_detail_submission_count_label.text() == "2 / 3"
        window.generate_merged_payment_screenshot_button.click()
        assert window.item_detail_submission_count_label.text() == "3 / 3"
        assert window.item_detail_submission_readiness_label.text() == "可提交"

        # 删除入口只在材料卡片里：凭证区只做预览，不提供删除。
        assert not [
            button
            for button in window.merged_payment_section.findChildren(QPushButton)
            if button.text() == "删除"
        ]
        derived_card = next(
            card
            for card in window.item_detail_materials.findChildren(QFrame, "attachmentCard")
            if "合并提交文件"
            in card.findChild(QLabel, "attachmentFilename").toolTip()
        )
        derived_actions = derived_card.findChild(QWidget, "attachmentActions")
        assert derived_actions is not None
        next(
            button
            for button in derived_actions.findChildren(QPushButton)
            if button.text() == "删除"
        ).click()

        assert not [attachment for attachment in attachments.list_attachments(item_id) if attachment.is_derived]
        assert window.item_detail_submission_count_label.text() == "2 / 3"
        assert window.item_detail_submission_readiness_label.text() == "缺少：合并支付截图"
    finally:
        window.close()
        database.dispose()


def test_item_delete_confirmation_cancel_keeps_item(tmp_path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch_service = BatchService(database)
    batch = batch_service.create_batch(name="取消删除物品")
    template = TemplateService(database).ensure_default_template()
    item_service = ItemService(database)
    item = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=1, name="保留物品"
    )
    storage = StoragePathService(tmp_path / "archive")
    window = MainWindow(
        DashboardService(database, CompletenessService(database, storage)),
        batch_service,
        item_service,
        CompletenessService(database, storage),
        attachment_service=AttachmentService(database, storage),
    )
    monkeypatch.setattr(
        main_window.QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.No,
    )
    try:
        window.navigation.setCurrentRow(2)
        window.all_items_table.cellDoubleClicked.emit(0, 0)
        window.delete_item_button.click()

        assert item_service.get_item(item.id).id == item.id
        assert window.all_items_table.rowCount() == 1
    finally:
        window.close()
        database.dispose()


def test_item_delete_refreshes_item_list_pending_and_dashboard(tmp_path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch_service = BatchService(database)
    batch = batch_service.create_batch(name="删除物品刷新")
    template = TemplateService(database).ensure_default_template()
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    item_service = ItemService(database, attachments)
    item = item_service.create_item(
        batch_id=batch.id, template_id=template.id, sequence_number=1, name="待删除物品"
    )
    completeness = CompletenessService(database, storage)
    submission = SubmissionReadinessService(database, storage)
    window = MainWindow(
        DashboardService(database, completeness),
        batch_service,
        item_service,
        completeness,
        attachment_service=attachments,
        submission_readiness_service=submission,
        pending_materials_service=PendingMaterialsService(
            item_service, completeness, submission
        ),
    )
    monkeypatch.setattr(
        main_window.QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )
    try:
        window.navigation.setCurrentRow(2)
        window.all_items_table.cellDoubleClicked.emit(0, 0)
        window.delete_item_button.click()

        assert window.pages.currentIndex() == 2
        assert window.all_items_table.rowCount() == 0
        assert window.pending_materials_table.rowCount() == 0
        assert window.dashboard_summary_labels["待处理"].text() == "0"
        with pytest.raises(Exception):
            item_service.get_item(item.id)
    finally:
        window.close()
        database.dispose()


def test_batch_delete_confirmation_cancel_and_success_refreshes_list(
    tmp_path, monkeypatch
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    batch_service = BatchService(database)
    batch = batch_service.create_batch(name="待删除空批次")
    storage = StoragePathService(tmp_path / "archive")
    window = MainWindow(
        batch_service=batch_service,
        dashboard_service=DashboardService(database, CompletenessService(database, storage)),
    )
    try:
        window.navigation.setCurrentRow(1)
        window.batch_table.cellDoubleClicked.emit(0, 0)
        monkeypatch.setattr(
            main_window.QMessageBox,
            "question",
            lambda *_args: QMessageBox.StandardButton.No,
        )
        window.delete_batch_button.click()
        assert window.batch_table.rowCount() == 1

        monkeypatch.setattr(
            main_window.QMessageBox,
            "question",
            lambda *_args: QMessageBox.StandardButton.Yes,
        )
        window.delete_batch_button.click()
        assert window.pages.currentIndex() == BATCH_LIST_PAGE_INDEX
        assert window.batch_table.rowCount() == 0
        assert batch_service.list_batches() == []
        assert batch.id > 0
    finally:
        window.close()
        database.dispose()


def test_settings_page_has_backup_database_button() -> None:
    application = QApplication.instance() or QApplication([])
    del application
    window = MainWindow()
    try:
        window.navigation.setCurrentRow(5)
        assert window.backup_database_button.text() == "备份数据库"
        assert window.findChild(QLabel, "settingsSectionTitle").text() == "数据与存储"
        assert window.archive_root_label.text() == "未配置"
    finally:
        window.close()


def test_settings_page_has_restore_database_button() -> None:
    application = QApplication.instance() or QApplication([])
    del application
    window = MainWindow()
    try:
        window.navigation.setCurrentRow(5)
        assert window.restore_database_button.text() == "恢复数据库"
        assert window.application_version_label.text() == __version__
    finally:
        window.close()


def test_settings_page_displays_existing_archive_root() -> None:
    application = QApplication.instance() or QApplication([])
    del application
    archive_root = Path("C:/reimbursement/archive")
    backup_service = SimpleNamespace(_settings=SimpleNamespace(archive_root=archive_root))
    window = MainWindow(backup_service=backup_service)
    try:
        assert window.archive_root_label.text() == str(archive_root)
    finally:
        window.close()


def test_settings_restore_cancel_file_selection_does_not_call_service(monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    calls: list[Path] = []
    restore_service = SimpleNamespace(
        restore_database=lambda backup_db_path: calls.append(backup_db_path)
    )
    monkeypatch.setattr(
        main_window.QFileDialog, "getOpenFileName", lambda *_args: ("", "")
    )
    window = MainWindow(restore_service=restore_service)
    try:
        window.restore_database_button.click()
        assert calls == []
    finally:
        window.close()


def test_settings_restore_first_confirmation_cancel_does_not_call_service(
    tmp_path, monkeypatch
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    calls: list[Path] = []
    backup_path = tmp_path / "backup.db"
    restore_service = SimpleNamespace(
        restore_database=lambda backup_db_path: calls.append(backup_db_path)
    )
    monkeypatch.setattr(
        main_window.QFileDialog, "getOpenFileName", lambda *_args: (str(backup_path), "")
    )
    window = MainWindow(restore_service=restore_service)
    monkeypatch.setattr(window, "_confirm_restore_database", lambda *_args: False)
    try:
        window.restore_database_button.click()
        assert calls == []
    finally:
        window.close()


def test_settings_restore_second_confirmation_cancel_does_not_call_service(
    tmp_path, monkeypatch
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    calls: list[Path] = []
    backup_path = tmp_path / "backup.db"
    restore_service = SimpleNamespace(
        restore_database=lambda backup_db_path: calls.append(backup_db_path)
    )
    confirmations = iter((True, False))
    monkeypatch.setattr(
        main_window.QFileDialog, "getOpenFileName", lambda *_args: (str(backup_path), "")
    )
    window = MainWindow(restore_service=restore_service)
    monkeypatch.setattr(
        window, "_confirm_restore_database", lambda *_args: next(confirmations)
    )
    try:
        window.restore_database_button.click()
        assert calls == []
    finally:
        window.close()


def test_settings_restore_calls_service_and_shows_returned_paths(tmp_path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    backup_path = tmp_path / "backup.db"
    result = RestoreResult(
        restored_database_path=tmp_path / "data" / "app.db",
        source_backup_path=backup_path,
        safety_backup_path=tmp_path / "data" / "backups" / "safety.db",
        schema_version="20260829_0002",
    )
    calls: list[Path] = []
    restore_service = SimpleNamespace(
        restore_database=lambda selected_path: calls.append(selected_path) or result
    )
    monkeypatch.setattr(
        main_window.QFileDialog, "getOpenFileName", lambda *_args: (str(backup_path), "")
    )
    window = MainWindow(restore_service=restore_service)
    monkeypatch.setattr(window, "_confirm_restore_database", lambda *_args: True)
    try:
        window.restore_database_button.click()
        assert calls == [backup_path]
        assert window.restore_result_label.text() == (
            "数据库恢复成功。\n"
            f"恢复来源：{result.source_backup_path}\n"
            f"当前数据库：{result.restored_database_path}\n"
            f"恢复前安全备份：{result.safety_backup_path}\n\n"
            "数据库已恢复。请重新启动应用以加载恢复后的全部数据。\n"
            "数据库恢复不会恢复附件文件。如果旧数据库引用的附件当前不存在，"
            "软件会将其显示为文件缺失。"
        )
        assert window.restore_result_label.isHidden() is False
    finally:
        window.close()


@pytest.mark.parametrize(
    ("error", "expected_text"),
    [
        (InvalidBackupDatabaseError("invalid"), "选择的文件不是有效的报销数据库。"),
        (SafetyBackupError("backup failed"), "恢复前备份当前数据库失败，恢复已取消。"),
        (DatabaseReplacementError("rolled back"), "数据库恢复失败，原数据库已恢复。"),
        (RuntimeError("unexpected"), "数据库恢复失败，请检查日志后重试。"),
    ],
)
def test_settings_restore_failure_shows_safe_message(
    tmp_path, monkeypatch, error, expected_text
) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    restore_service = SimpleNamespace(
        restore_database=lambda _backup_db_path: (_ for _ in ()).throw(error)
    )
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main_window.QFileDialog, "getOpenFileName", lambda *_args: (str(tmp_path / "backup.db"), "")
    )
    monkeypatch.setattr(
        main_window.QMessageBox,
        "warning",
        lambda _parent, title, text: warnings.append((title, text)),
    )
    window = MainWindow(restore_service=restore_service)
    monkeypatch.setattr(window, "_confirm_restore_database", lambda *_args: True)
    try:
        window.restore_database_button.click()
        assert warnings == [("无法恢复数据库", expected_text)]
        assert window.restore_result_label.isHidden() is True
    finally:
        window.close()


def test_settings_backup_calls_service_for_selected_directory(tmp_path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    selected_directory = tmp_path / "backups"
    calls: list[Path] = []
    result = BackupResult(
        selected_directory / "backup.db", selected_directory / "backup_info.json"
    )
    backup_service = SimpleNamespace(
        create_backup=lambda directory: calls.append(directory) or result
    )
    monkeypatch.setattr(
        main_window.QFileDialog,
        "getExistingDirectory",
        lambda *_args: str(selected_directory),
    )
    window = MainWindow(backup_service=backup_service)
    try:
        window.backup_database_button.click()
        assert calls == [selected_directory]
    finally:
        window.close()


def test_settings_backup_cancel_does_not_call_service(monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    calls: list[Path] = []
    backup_service = SimpleNamespace(create_backup=lambda directory: calls.append(directory))
    monkeypatch.setattr(
        main_window.QFileDialog, "getExistingDirectory", lambda *_args: ""
    )
    window = MainWindow(backup_service=backup_service)
    try:
        window.backup_database_button.click()
        assert calls == []
    finally:
        window.close()


def test_settings_backup_success_shows_returned_paths(tmp_path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    result = BackupResult(tmp_path / "database.db", tmp_path / "metadata.json")
    backup_service = SimpleNamespace(create_backup=lambda _directory: result)
    monkeypatch.setattr(
        main_window.QFileDialog, "getExistingDirectory", lambda *_args: str(tmp_path)
    )
    window = MainWindow(backup_service=backup_service)
    try:
        window.backup_database_button.click()
        assert window.backup_result_label.text() == (
            f"数据库备份完成。\n数据库：{result.database_path}\n元信息：{result.metadata_path}"
        )
        assert window.backup_result_label.isHidden() is False
    finally:
        window.close()


def test_settings_backup_failure_shows_safe_error(tmp_path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    del application
    backup_service = SimpleNamespace(
        create_backup=lambda _directory: (_ for _ in ()).throw(OSError("disk full"))
    )
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main_window.QFileDialog, "getExistingDirectory", lambda *_args: str(tmp_path)
    )
    monkeypatch.setattr(
        main_window.QMessageBox,
        "warning",
        lambda _parent, title, text: messages.append((title, text)),
    )
    window = MainWindow(backup_service=backup_service)
    try:
        window.backup_database_button.click()
        assert messages == [("数据库备份失败", "数据库备份失败，请检查目录权限后重试。")]
        assert window.backup_result_label.isHidden() is True
    finally:
        window.close()
