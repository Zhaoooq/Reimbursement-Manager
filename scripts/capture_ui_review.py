"""Capture the current UI as PNGs for design review (scratch copy, never the real data)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "scripts"))

from PySide6.QtWidgets import QApplication  # noqa: E402

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
from seed_ui_review_data import main as seed  # noqa: E402

OUT = PROJECT / "docs" / "ui-review"
SANDBOX = Path(r"C:\Users\THIS PC\AppData\Local\Temp\rm-ui-review")


def main() -> int:
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX)
    shutil.copytree(PROJECT / "data", SANDBOX / "data")
    OUT.mkdir(parents=True, exist_ok=True)

    settings, _ = initialize_runtime_database(SANDBOX)
    seed(SANDBOX)

    db = DatabaseManager.from_sqlite_path(settings.database_path)
    storage = StoragePathService(settings.archive_root)
    completeness = CompletenessService(db, storage)
    readiness = SubmissionReadinessService(db, storage)
    attachment_service = AttachmentService(db, storage)
    item_service = ItemService(db, attachment_service)

    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        DashboardService(db, completeness, readiness),
        BatchService(db, storage),
        item_service,
        completeness,
        TemplateService(db),
        attachment_service,
        PaymentScreenshotMergeService(db, storage),
        readiness,
        export_service=ExportService(db, storage, submission_readiness_service=readiness),
        pending_materials_service=PendingMaterialsService(item_service, completeness, readiness),
        backup_service=BackupService(db, settings),
        restore_service=RestoreService(db, settings),
        workflow_service=WorkflowService(db, readiness),
    )
    window.resize(1360, 860)
    window.show()
    app.processEvents()

    def shot(name: str) -> None:
        for _ in range(4):
            app.processEvents()
        window.grab().save(str(OUT / f"{name}.png"))

    names = ["dashboard", "batches", "items", "pending", "templates", "settings"]
    for index, name in enumerate(names):
        window.navigation.setCurrentRow(index)
        app.processEvents()
        shot(f"01-{name}")

    window.navigation.setCurrentRow(1)
    app.processEvents()
    window._open_batch_detail(0, 0)
    shot("02-batch-detail")

    window._open_item_detail(0, 0)
    shot("03-item-detail-top")
    scroll = window.findChild(type(window.pages), "itemDetailScrollArea")
    window._show_all_items()
    window.navigation.setCurrentRow(2)
    app.processEvents()
    window.refresh_all_items()
    shot("04-items-filled")

    window._open_item_detail(0, 0)
    shot("05-item-detail-full")

    window.close()
    db.dispose()
    print("saved to", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
