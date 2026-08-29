from PySide6.QtWidgets import QApplication

from pathlib import Path
import sqlite3

import reimbursement_manager.app as application
from reimbursement_manager.app import initialize_runtime_database, main
from reimbursement_manager.config import AppPaths
from reimbursement_manager.database import DatabaseManager, upgrade_database
from reimbursement_manager.services.backup_service import BackupService
from reimbursement_manager.services.restore_service import RestoreService
from sqlalchemy import text


def test_main_returns_success(tmp_path):
    assert main(project_root=tmp_path, run_event_loop=False) == 0
    assert (tmp_path / "data" / "app.db").exists()
    assert QApplication.instance().font().family() == "Microsoft YaHei UI"


def test_development_startup_does_not_use_or_migrate_to_local_app_data(
    monkeypatch, tmp_path: Path
) -> None:
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))

    settings, result = initialize_runtime_database(tmp_path / "开发项目", frozen=False)

    assert result is None
    assert settings.database_path == (tmp_path / "开发项目" / "data" / "app.db").resolve()
    assert settings.database_path.is_file()
    assert not local_app_data.exists()


def test_packaged_startup_migrates_legacy_before_initializing_empty_database(
    monkeypatch, tmp_path: Path
) -> None:
    project_root = tmp_path / "旧开发项目"
    legacy_path = project_root / "data" / "app.db"
    from reimbursement_manager.config.settings import AppSettings

    upgrade_database(
        project_root=AppSettings.default_project_root(), database_path=legacy_path
    )
    legacy_database = DatabaseManager.from_sqlite_path(legacy_path)
    try:
        with legacy_database.transaction() as session:
            session.execute(
                text("INSERT INTO reimbursement_batches (name, status) VALUES ('迁移顺序数据', 'collecting')")
            )
    finally:
        legacy_database.dispose()

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "中文 LocalAppData"))
    settings, result = initialize_runtime_database(project_root, frozen=True)

    assert result is not None
    assert result.status.value == "migrated"
    production_database = DatabaseManager.from_sqlite_path(settings.database_path)
    try:
        with production_database.transaction() as session:
            assert session.scalar(text("SELECT name FROM reimbursement_batches")) == "迁移顺序数据"
    finally:
        production_database.dispose()
    assert legacy_path.is_file()


def test_packaged_startup_uses_existing_production_database_without_legacy_check(
    monkeypatch, tmp_path: Path
) -> None:
    project_root = tmp_path / "development-project"
    paths = AppPaths.for_packaged(local_app_data=tmp_path / "LocalAppData")
    upgrade_database(
        project_root=application.AppSettings.default_project_root(),
        database_path=paths.database_path,
    )
    production_database = DatabaseManager.from_sqlite_path(paths.database_path)
    try:
        with production_database.transaction() as session:
            session.execute(
                text("INSERT INTO reimbursement_batches (name, status) VALUES ('production', 'collecting')")
            )
    finally:
        production_database.dispose()

    legacy_path = project_root / "data" / "app.db"
    upgrade_database(
        project_root=application.AppSettings.default_project_root(),
        database_path=legacy_path,
    )

    class UnexpectedLegacyMigration:
        def __init__(self, **_kwargs: object) -> None:
            raise AssertionError("existing production database must skip legacy migration")

    monkeypatch.setattr(application, "LegacyDatabaseMigrationService", UnexpectedLegacyMigration)
    settings, result = initialize_runtime_database(
        project_root, frozen=True, app_paths=paths
    )

    assert result is None
    assert settings.database_path == paths.database_path
    production_database = DatabaseManager.from_sqlite_path(paths.database_path)
    try:
        with production_database.transaction() as session:
            assert session.scalar(text("SELECT name FROM reimbursement_batches")) == "production"
    finally:
        production_database.dispose()


def test_packaged_first_start_initializes_database_and_default_data_idempotently(
    tmp_path: Path,
) -> None:
    paths = AppPaths.for_packaged(local_app_data=tmp_path / "LocalAppData")

    settings, first_result = initialize_runtime_database(
        tmp_path / "development-project", frozen=True, app_paths=paths
    )
    _, second_result = initialize_runtime_database(
        tmp_path / "development-project", frozen=True, app_paths=paths
    )

    assert first_result is not None
    assert first_result.status.value == "no_legacy_database"
    assert second_result is None
    assert settings.database_path.is_file()
    database = DatabaseManager.from_sqlite_path(settings.database_path)
    try:
        with database.transaction() as session:
            assert session.scalar(text("SELECT COUNT(*) FROM material_types")) == 6
            assert session.scalar(
                text("SELECT COUNT(*) FROM templates WHERE name = '普通购物'")
            ) == 1
    finally:
        database.dispose()


def test_backup_and_restore_use_the_injected_production_database(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "development-project"
    paths = AppPaths.for_packaged(local_app_data=tmp_path / "LocalAppData")
    settings, _ = initialize_runtime_database(
        project_root, frozen=True, app_paths=paths
    )
    production_database = DatabaseManager.from_sqlite_path(settings.database_path)
    backup_source = tmp_path / "backup-source.db"
    upgrade_database(
        project_root=application.AppSettings.default_project_root(),
        database_path=backup_source,
    )
    source_database = DatabaseManager.from_sqlite_path(backup_source)
    try:
        with production_database.transaction() as session:
            session.execute(
                text("INSERT INTO reimbursement_batches (name, status) VALUES ('production', 'collecting')")
            )
        with source_database.transaction() as session:
            session.execute(
                text("INSERT INTO reimbursement_batches (name, status) VALUES ('restored', 'collecting')")
            )

        backup = BackupService(production_database, settings).create_backup(
            tmp_path / "backups"
        )
        with sqlite3.connect(backup.database_path) as connection:
            assert connection.execute("SELECT name FROM reimbursement_batches").fetchone() == (
                "production",
            )

        result = RestoreService(production_database, settings).restore_database(
            backup_source
        )
        with production_database.transaction() as session:
            assert session.scalar(text("SELECT name FROM reimbursement_batches")) == "restored"
        assert result.restored_database_path == paths.database_path
    finally:
        source_database.dispose()
        production_database.dispose()
