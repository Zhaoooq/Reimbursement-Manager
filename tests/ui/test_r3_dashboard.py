"""R3 首页改造：统计语义、主操作、行密度与溢出约束。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Base
from reimbursement_manager.services import (
    AttachmentService,
    BatchService,
    CompletenessService,
    DashboardData,
    DashboardService,
    IncompleteDashboardItem,
    ItemService,
    PendingMaterialsService,
    StoragePathService,
    SubmissionReadinessService,
    TemplateService,
)
from reimbursement_manager.ui.windows import MainWindow


class _StubDashboard:
    """Two outstanding items so the attention list has real content."""

    def __init__(self, *, outstanding: int = 2) -> None:
        self._outstanding = outstanding

    def get_data(self) -> DashboardData:
        items = tuple(
            IncompleteDashboardItem(
                item_id=index + 1,
                name=f"物品 {index + 1}",
                completed_count=1,
                required_count=4,
                missing_materials=("发票", "支付截图", "订单截图"),
            )
            for index in range(self._outstanding)
        )
        return DashboardData(
            incomplete_count=self._outstanding,
            complete_count=1,
            submitted_count=2,
            reimbursed_count=3,
            incomplete_items=items,
        )


def _dashboard_window(database, storage) -> MainWindow:
    completeness = CompletenessService(database, storage)
    submission = SubmissionReadinessService(database, storage)
    item_service = ItemService(database, AttachmentService(database, storage))
    return MainWindow(
        _StubDashboard(),
        batch_service=BatchService(database, storage),
        item_service=item_service,
        completeness_service=completeness,
        attachment_service=AttachmentService(database, storage),
        submission_readiness_service=submission,
        pending_materials_service=PendingMaterialsService(
            item_service, completeness, submission
        ),
    )


def test_dashboard_has_one_primary_action_reusing_the_batch_dialog(
    tmp_path: Path, monkeypatch
) -> None:
    application = QApplication.instance() or QApplication([])
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    window = _dashboard_window(database, StoragePathService(tmp_path / "archive"))
    calls: list[bool] = []
    monkeypatch.setattr(
        window, "_open_new_batch_dialog", lambda: calls.append(True), raising=False
    )
    try:
        button = window.dashboard_new_batch_button
        assert button.objectName() == "primaryButton"
        assert button.text() == "+ 新建批次"
        assert button.isEnabled() is True

        button.click()
        assert calls == [True]
    finally:
        window.close()
        database.dispose()


def test_dashboard_new_batch_action_is_disabled_without_a_batch_service() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(_StubDashboard())  # type: ignore[arg-type]
    try:
        assert window.dashboard_new_batch_button.isEnabled() is False
    finally:
        window.close()


def test_only_the_outstanding_statistic_is_coloured() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(_StubDashboard(outstanding=2))  # type: ignore[arg-type]
    try:
        labels = window.dashboard_summary_labels
        assert labels["待处理"].property("semantic") == "warning"
        assert labels["可提交"].property("semantic") == "secondary"
        assert labels["已提交"].property("semantic") == "secondary"
        assert labels["已报销"].property("semantic") == "secondary"
    finally:
        window.close()

    clear = MainWindow()  # nothing outstanding
    try:
        for value_label in clear.dashboard_summary_labels.values():
            assert value_label.property("semantic") == "secondary"
    finally:
        clear.close()


def test_dashboard_pending_summary_is_hidden_when_nothing_is_left() -> None:
    application = QApplication.instance() or QApplication([])
    empty = MainWindow()
    try:
        assert empty.dashboard_pending_summary.isVisible() is False
        assert empty.dashboard_pending_summary.text() == "还有 0 个物品需要处理"
    finally:
        empty.close()

    busy = MainWindow(_StubDashboard())  # type: ignore[arg-type]
    try:
        busy.show()
        application.processEvents()
        assert busy.dashboard_pending_summary.isVisible() is True
        assert busy.dashboard_pending_summary.text() == "还有 2 个物品需要处理"
    finally:
        busy.close()


def test_dashboard_pending_row_stays_compact_and_inside_the_viewport(
    tmp_path: Path,
) -> None:
    application = QApplication.instance() or QApplication([])
    database = DatabaseManager.in_memory()
    Base.metadata.create_all(database.engine)
    storage = StoragePathService(tmp_path / "archive")
    template = TemplateService(database).ensure_default_template()
    batch = BatchService(database).create_batch(
        name="2026年8月北京航空航天大学国际创新研究院纳米颗粒检测课题组实验耗材采购"
    )
    ItemService(database).create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W 及配套散热片、电源适配器、MicroSD 卡整套采购",
    )
    completeness = CompletenessService(database, storage)
    submission = SubmissionReadinessService(database, storage)
    item_service = ItemService(database)
    window = MainWindow(
        DashboardService(database, completeness, submission),
        batch_service=BatchService(database),
        item_service=item_service,
        completeness_service=completeness,
        submission_readiness_service=submission,
        pending_materials_service=PendingMaterialsService(
            item_service, completeness, submission
        ),
    )
    try:
        window.resize(1100, 700)
        window.show()
        application.processEvents()

        row = window.dashboard_pending_items[0]
        viewport = window.dashboard_pending_scroll.viewport().width()
        assert row.width() <= viewport
        assert row.minimumSizeHint().width() <= viewport
        assert window.dashboard_pending_scroll.horizontalScrollBar().maximum() == 0
        assert row.height() <= 100

        # The full name is still available even though the label elides it.
        name = row.findChild(QLabel, "dashboardItemName")
        assert name is not None
        assert name.text().startswith("树莓派 Zero 2 W 及配套散热片")
        assert name.toolTip() == name.text()
    finally:
        window.close()
        database.dispose()


def test_dashboard_attention_row_keeps_the_detail_entry_point() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(_StubDashboard())  # type: ignore[arg-type]
    try:
        window.show()
        application.processEvents()
        row = window.dashboard_pending_items[0]
        button = row.findChild(QPushButton, "dashboardItemDetailButton")
        assert button is not None
        assert button.text() == "查看  ›"
        assert len(row.findChildren(QLabel, "dashboardProgressLabel")) == 1
        assert [
            label.text() for label in row.findChildren(QLabel, "dashboardProgressValue")
        ] == ["1 / 4"]
    finally:
        window.close()
