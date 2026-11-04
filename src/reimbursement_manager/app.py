from pathlib import Path
import logging
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from reimbursement_manager import updater
from reimbursement_manager.config import AppPaths, AppSettings, is_packaged_runtime
from reimbursement_manager.database import DatabaseManager, upgrade_database
from reimbursement_manager.database.seed import initialize_default_material_types
from reimbursement_manager.services import (
    AttachmentService,
    BatchService,
    CompletenessService,
    DashboardService,
    ExportService,
    ItemService,
    PaymentScreenshotMergeService,
    PendingMaterialsService,
    RestoreService,
    LegacyDatabaseMigrationResult,
    LegacyDatabaseMigrationService,
    StoragePathService,
    SubmissionReadinessService,
    TemplateService,
    UpdateService,
    WorkflowService,
)
from reimbursement_manager.services.backup_service import BackupService
from reimbursement_manager.ui.windows import MainWindow
from reimbursement_manager.ui.windows.update_dialog import UpdateContext
from reimbursement_manager.version import __version__


logger = logging.getLogger(__name__)


def build_update_context(
    settings: AppSettings, *, frozen: bool | None = None
) -> UpdateContext | None:
    """Return the update wiring, or ``None`` when running from a checkout.

    A development run has no installation directory to replace, so the settings
    page hides the update block entirely.
    """
    if not is_packaged_runtime(frozen=frozen):
        return None
    return UpdateContext(
        service=UpdateService(),
        current_version=__version__,
        install_directory=updater.current_install_directory(),
        updates_directory=settings.paths.app_data_dir / "updates",
    )


def report_previous_update(parent: MainWindow) -> None:
    """Tell the user how the update that relaunched the app ended."""
    result = updater.consume_update_result()
    if result is None:
        return
    if result.success:
        QMessageBox.information(parent, "更新完成", f"已更新到版本 {result.version}。")
        return
    QMessageBox.warning(
        parent, "更新未完成", result.message or "更新未能完成，请重新检查更新。"
    )


def initialize_runtime_database(
    project_root: Path | None = None,
    *,
    frozen: bool | None = None,
    app_paths: AppPaths | None = None,
) -> tuple[AppSettings, LegacyDatabaseMigrationResult | None]:
    """Prepare the selected runtime database and its idempotent defaults.

    ``app_paths`` is an explicit test/runtime injection point.  Normal startup
    always resolves it from the active development or packaged runtime mode.
    """
    source_root = AppSettings.default_project_root()
    runtime_project_root = project_root or source_root
    packaged_runtime = is_packaged_runtime(frozen=frozen)
    paths = app_paths or AppPaths.for_current_runtime(
        project_root=runtime_project_root, frozen=packaged_runtime
    )
    settings = AppSettings.from_paths(paths, migration_project_root=source_root)
    settings.ensure_directories()
    logger.info(
        "%s database path: %s",
        "Production" if packaged_runtime else "Development",
        settings.database_path,
    )

    legacy_migration_result: LegacyDatabaseMigrationResult | None = None
    if packaged_runtime and not settings.database_path.exists():
        legacy_migration_result = LegacyDatabaseMigrationService(
            legacy_database_path=AppPaths.for_development(runtime_project_root).database_path,
            destination_database_path=settings.database_path,
            migration_project_root=source_root,
        ).migrate_if_needed()
        if legacy_migration_result.status.value == "migrated":
            logger.info("Migrated legacy database into production location")
        elif legacy_migration_result.status.value == "no_legacy_database":
            logger.info("Initialized new production database")
    elif packaged_runtime:
        logger.info("Using existing production database")

    upgrade_database(
        project_root=source_root,
        database_path=settings.database_path,
    )
    database = DatabaseManager.from_sqlite_path(settings.database_path)
    try:
        with database.transaction() as session:
            initialize_default_material_types(session)
        TemplateService(database).ensure_default_template()
    finally:
        database.dispose()
    return settings, legacy_migration_result


def main(
    project_root: Path | None = None,
    *,
    run_event_loop: bool = True,
    frozen: bool | None = None,
    argv: list[str] | None = None,
) -> int:
    """Start the local application and show its service-backed Dashboard."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if updater.is_update_invocation(arguments):
        # Installing an update must not touch the database or start Qt.
        return updater.run_from_command_line(arguments)

    settings, _legacy_migration_result = initialize_runtime_database(
        project_root, frozen=frozen
    )
    database = DatabaseManager.from_sqlite_path(settings.database_path)

    completeness_service = CompletenessService(
        database, StoragePathService(settings.archive_root)
    )
    storage_path_service = StoragePathService(settings.archive_root)
    attachment_service = AttachmentService(database, storage_path_service)
    item_service = ItemService(database, attachment_service)
    batch_service = BatchService(database, storage_path_service)
    submission_readiness_service = SubmissionReadinessService(
        database, StoragePathService(settings.archive_root)
    )
    dashboard_service = DashboardService(
        database,
        completeness_service,
        submission_readiness_service,
    )

    application = QApplication.instance() or QApplication([])
    application.setFont(QFont("Microsoft YaHei UI", 9))
    update_context = build_update_context(settings, frozen=frozen)
    if update_context is not None:
        # The update that just restarted us left its download and staging copy.
        updater.cleanup_update_workspace(update_context.updates_directory)
    window = MainWindow(
        dashboard_service,
        batch_service,
        item_service,
        completeness_service,
        TemplateService(database),
        attachment_service,
        PaymentScreenshotMergeService(
            database, StoragePathService(settings.archive_root)
        ),
        submission_readiness_service,
        export_service=ExportService(
            database,
            StoragePathService(settings.archive_root),
            submission_readiness_service=submission_readiness_service,
        ),
        pending_materials_service=PendingMaterialsService(
            item_service,
            completeness_service,
            submission_readiness_service,
        ),
        backup_service=BackupService(database, settings),
        restore_service=RestoreService(database, settings),
        workflow_service=WorkflowService(database, submission_readiness_service),
        update_context=update_context,
    )
    try:
        if not run_event_loop:
            return 0
        window.show()
        report_previous_update(window)
        return application.exec()
    finally:
        window.close()
        database.dispose()
