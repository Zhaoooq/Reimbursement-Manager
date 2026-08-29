from __future__ import annotations

from collections.abc import Iterator
from contextlib import closing
from datetime import datetime
from pathlib import Path
import sqlite3

import pytest
from sqlalchemy import text

from reimbursement_manager.config.settings import AppSettings
from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Base
from reimbursement_manager.services.backup_service import BackupService
from reimbursement_manager.services.restore_service import (
    DatabaseReplacementError,
    InvalidBackupDatabaseError,
    RestoreService,
    SafetyBackupError,
)


HEAD_REVISION = "20260829_0002"


def make_settings(tmp_path: Path) -> AppSettings:
    return AppSettings.from_project_root(tmp_path / "恢复项目")


def create_database(path: Path, name: str) -> None:
    manager = DatabaseManager.from_sqlite_path(path)
    try:
        Base.metadata.create_all(manager.engine)
        with manager.transaction() as session:
            session.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
            session.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:version)"),
                {"version": HEAD_REVISION},
            )
            session.execute(
                text("INSERT INTO reimbursement_batches (name, status) VALUES (:name, 'collecting')"),
                {"name": name},
            )
    finally:
        manager.dispose()


@pytest.fixture
def settings(tmp_path: Path) -> AppSettings:
    result = make_settings(tmp_path)
    result.ensure_directories()
    result.archive_root.mkdir(parents=True, exist_ok=True)
    return result


@pytest.fixture
def database(settings: AppSettings) -> Iterator[DatabaseManager]:
    create_database(settings.database_path, "当前数据")
    manager = DatabaseManager.from_sqlite_path(settings.database_path)
    try:
        yield manager
    finally:
        manager.dispose()


def make_service(database: DatabaseManager, settings: AppSettings) -> RestoreService:
    return RestoreService(
        database,
        settings,
        backup_service=BackupService(
            database,
            settings,
            now_provider=lambda: datetime(2026, 8, 29, 15, 0, 0),
        ),
    )


def current_batch_name(database: DatabaseManager) -> str:
    with database.transaction() as session:
        return str(session.scalar(text("SELECT name FROM reimbursement_batches")))


def test_restores_valid_backup_and_creates_safety_backup(
    database: DatabaseManager, settings: AppSettings, tmp_path: Path
) -> None:
    backup_path = tmp_path / "备份" / "有效备份.db"
    backup_path.parent.mkdir()
    create_database(backup_path, "备份数据")

    result = make_service(database, settings).restore_database(backup_path)

    assert current_batch_name(database) == "备份数据"
    assert result.restored_database_path == settings.database_path
    assert result.source_backup_path == backup_path.resolve()
    assert result.safety_backup_path.is_file()
    assert result.schema_version == HEAD_REVISION
    with closing(sqlite3.connect(result.safety_backup_path)) as connection:
        assert connection.execute("SELECT name FROM reimbursement_batches").fetchone() == (
            "当前数据",
        )


def test_rejects_non_sqlite_file_without_changing_current_database(
    database: DatabaseManager, settings: AppSettings, tmp_path: Path
) -> None:
    backup_path = tmp_path / "invalid.db"
    backup_path.write_text("not a database", encoding="utf-8")

    with pytest.raises(InvalidBackupDatabaseError):
        make_service(database, settings).restore_database(backup_path)

    assert current_batch_name(database) == "当前数据"


def test_rejects_sqlite_database_missing_required_tables(
    database: DatabaseManager, settings: AppSettings, tmp_path: Path
) -> None:
    backup_path = tmp_path / "partial.db"
    with closing(sqlite3.connect(backup_path)) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO alembic_version (version_num) VALUES (?)", (HEAD_REVISION,)
        )
        connection.commit()

    with pytest.raises(InvalidBackupDatabaseError, match="missing required tables"):
        make_service(database, settings).restore_database(backup_path)

    assert current_batch_name(database) == "当前数据"


@pytest.mark.parametrize("revision", [None, "unknown_revision"])
def test_rejects_missing_or_unknown_alembic_revision(
    database: DatabaseManager, settings: AppSettings, tmp_path: Path, revision: str | None
) -> None:
    backup_path = tmp_path / f"revision-{revision}.db"
    create_database(backup_path, "备份数据")
    with closing(sqlite3.connect(backup_path)) as connection:
        connection.execute("DELETE FROM alembic_version")
        if revision is not None:
            connection.execute(
                "INSERT INTO alembic_version (version_num) VALUES (?)", (revision,)
            )
        connection.commit()

    with pytest.raises(InvalidBackupDatabaseError):
        make_service(database, settings).restore_database(backup_path)

    assert current_batch_name(database) == "当前数据"


def test_rejects_backup_without_alembic_version_table(
    database: DatabaseManager, settings: AppSettings, tmp_path: Path
) -> None:
    backup_path = tmp_path / "without-alembic-table.db"
    create_database(backup_path, "备份数据")
    with closing(sqlite3.connect(backup_path)) as connection:
        connection.execute("DROP TABLE alembic_version")
        connection.commit()

    with pytest.raises(InvalidBackupDatabaseError, match="Alembic version table"):
        make_service(database, settings).restore_database(backup_path)

    assert current_batch_name(database) == "当前数据"


def test_safety_backup_failure_does_not_restore(
    database: DatabaseManager,
    settings: AppSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_path = tmp_path / "backup.db"
    create_database(backup_path, "备份数据")
    service = make_service(database, settings)

    def fail_safety_backup(_directory: Path) -> object:
        raise OSError("disk full")

    monkeypatch.setattr(service._backup_service, "create_backup", fail_safety_backup)

    with pytest.raises(SafetyBackupError, match="safety backup failed"):
        service.restore_database(backup_path)

    assert current_batch_name(database) == "当前数据"


def test_copy_failure_keeps_current_database(
    database: DatabaseManager,
    settings: AppSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_path = tmp_path / "backup.db"
    create_database(backup_path, "备份数据")
    service = make_service(database, settings)

    def fail_copy(_source: Path, _directory: Path) -> Path:
        raise OSError("copy failed")

    monkeypatch.setattr(service, "_copy_to_temporary", fail_copy)

    with pytest.raises(DatabaseReplacementError, match="original database was restored"):
        service.restore_database(backup_path)

    assert current_batch_name(database) == "当前数据"


def test_rename_failure_rolls_back_current_database(
    database: DatabaseManager, settings: AppSettings, tmp_path: Path
) -> None:
    backup_path = tmp_path / "backup.db"
    create_database(backup_path, "备份数据")
    calls = 0

    def fail_second_replace(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("rename failed")
        source.replace(destination)

    service = RestoreService(
        database,
        settings,
        backup_service=BackupService(
            database, settings, now_provider=lambda: datetime(2026, 8, 29, 15, 0, 1)
        ),
        replace_file=fail_second_replace,
    )

    with pytest.raises(DatabaseReplacementError, match="original database was restored"):
        service.restore_database(backup_path)

    assert current_batch_name(database) == "当前数据"
    assert settings.database_path.is_file()


def test_post_replacement_validation_failure_rolls_back(
    database: DatabaseManager,
    settings: AppSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_path = tmp_path / "backup.db"
    create_database(backup_path, "备份数据")
    service = make_service(database, settings)

    def fail_validation(_path: Path) -> None:
        raise InvalidBackupDatabaseError("post replacement validation failed")

    monkeypatch.setattr(service, "_validate_replacement", fail_validation)

    with pytest.raises(DatabaseReplacementError, match="original database was restored"):
        service.restore_database(backup_path)

    assert current_batch_name(database) == "当前数据"


def test_restore_does_not_modify_archive_files(
    database: DatabaseManager, settings: AppSettings, tmp_path: Path
) -> None:
    archive_file = settings.archive_root / "附件" / "保留.txt"
    archive_file.parent.mkdir()
    archive_file.write_text("do not change", encoding="utf-8")
    backup_path = tmp_path / "backup.db"
    create_database(backup_path, "备份数据")

    make_service(database, settings).restore_database(backup_path)

    assert archive_file.read_text(encoding="utf-8") == "do not change"
