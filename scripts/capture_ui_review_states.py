"""Capture secondary states: scrolled item detail, dialogs, empty states."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402

from reimbursement_manager.app import initialize_runtime_database  # noqa: E402
from reimbursement_manager.database import DatabaseManager  # noqa: E402
from reimbursement_manager.services import (  # noqa: E402
    AttachmentService,
    BatchService,
    CompletenessService,
    DashboardService,
    ExportService,
    ItemService,
    PaymentScreenshotMergeService,
    PendingMaterialsService,
    StoragePathService,
    SubmissionReadinessService,
    TemplateService,
    WorkflowService,
)
from reimbursement_manager.services.backup_service import BackupService  # noqa: E402
from reimbursement_manager.services.restore_service import RestoreService  # noqa: E402
from reimbursement_manager.ui.windows import MainWindow  # noqa: E402
from reimbursement_manager.ui.windows.main_window import NewItemDialog  # noqa: E402

OUT = PROJECT / "docs" / "ui-review"
SANDBOX = Path(r"C:\Users\THIS PC\AppData\Local\Temp\rm-ui-review")


def main() -> int:
    settings, _ = initialize_runtime_database(SANDBOX)
    db = DatabaseManager.from_sqlite_path(settings.database_path)
    storage = StoragePathService(settings.archive_root)
    completeness = CompletenessService(db, storage)
    readiness = SubmissionReadinessService(db, storage)
    attachments = AttachmentService(db, storage)
    items = ItemService(db, attachments)

    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        DashboardService(db, completeness, readiness),
        BatchService(db, storage),
        items,
        completeness,
        TemplateService(db),
        attachments,
        PaymentScreenshotMergeService(db, storage),
        readiness,
        export_service=ExportService(db, storage, submission_readiness_service=readiness),
        pending_materials_service=PendingMaterialsService(items, completeness, readiness),
        backup_service=BackupService(db, settings),
        restore_service=RestoreService(db, settings),
        workflow_service=WorkflowService(db, readiness),
    )
    window.resize(1360, 860)
    window.show()
    app.processEvents()

    def shot(widget, name: str) -> None:
        for _ in range(4):
            app.processEvents()
        widget.grab().save(str(OUT / f"{name}.png"))

    window.navigation.setCurrentRow(2)
    app.processEvents()
    window.refresh_all_items()
    window._open_item_detail(0, 0)
    app.processEvents()

    area = window.findChild(QScrollArea, "itemDetailScrollArea")
    if area is not None:
        bar = area.verticalScrollBar()
        bar.setValue(int(bar.maximum() * 0.55))
        shot(window, "06-item-detail-mid")
        bar.setValue(bar.maximum())
        shot(window, "07-item-detail-bottom")

    window._show_all_items()
    app.processEvents()
    window.all_items_search_input.setText("不存在的物品")
    window.refresh_all_items()
    shot(window, "08-items-empty-search")

    dialog = NewItemDialog("实验耗材报销", list(window._template_service.list_templates()))
    dialog.show()
    shot(dialog, "09-new-item-dialog")
    dialog.close()

    window.close()
    db.dispose()
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
