from __future__ import annotations

from collections.abc import Iterator
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3

import pytest
from sqlalchemy import text

from reimbursement_manager import __version__
from reimbursement_manager.config.settings import AppSettings
from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.services.backup_service import BackupResult, BackupService


@pytest.fixture
def database(tmp_path: Path) -> Iterator[DatabaseManager]:
    manager = DatabaseManager.from_sqlite_path(tmp_path / "app.db")
    try:
        with manager.transaction() as session:
            session.execute(text("CREATE TABLE entries (value TEXT NOT NULL)"))
            session.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
            session.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:version)"),
                {"version": "phase4_task1"},
            )
            session.execute(
                text("INSERT INTO entries (value) VALUES (:value)"),
                {"value": "before backup"},
            )
        yield manager
    finally:
        manager.dispose()


def make_settings(tmp_path: Path) -> AppSettings:
    return AppSettings.from_project_root(tmp_path / "项目")


def test_creates_timestamped_backup_and_metadata_in_unicode_directory(
    database: DatabaseManager, tmp_path: Path
) -> None:
    backup_directory = tmp_path / "备份目录"
    service = BackupService(
        database,
        make_settings(tmp_path),
        now_provider=lambda: datetime(2026, 8, 29, 14, 30, 0),
    )

    result = service.create_backup(backup_directory)

    assert result == BackupResult(
        database_path=backup_directory / "reimbursement_backup_2026-08-29_143000.db",
        metadata_path=(
            backup_directory / "reimbursement_backup_2026-08-29_143000_info.json"
        ),
    )
    assert result.database_path.is_file()
    assert result.metadata_path.is_file()
    with closing(sqlite3.connect(result.database_path)) as backup_connection:
        assert backup_connection.execute("SELECT value FROM entries").fetchall() == [
            ("before backup",)
        ]
    metadata_text = result.metadata_path.read_text(encoding="utf-8")
    assert "项目" in metadata_text
    assert json.loads(metadata_text) == {
        "backup_time": "2026-08-29T14:30:00",
        "app_version": __version__,
        "archive_root": str(make_settings(tmp_path).archive_root),
        "database_schema_version": "phase4_task1",
        "database_filename": result.database_path.name,
    }


def test_backup_does_not_modify_the_current_database(
    database: DatabaseManager, tmp_path: Path
) -> None:
    result = BackupService(database, make_settings(tmp_path)).create_backup(
        tmp_path / "backups"
    )

    with database.transaction() as session:
        assert session.scalar(text("SELECT COUNT(*) FROM entries")) == 1
        session.execute(
            text("INSERT INTO entries (value) VALUES (:value)"),
            {"value": "after backup"},
        )

    with closing(sqlite3.connect(result.database_path)) as backup_connection:
        assert backup_connection.execute("SELECT value FROM entries").fetchall() == [
            ("before backup",)
        ]


def test_failed_backup_leaves_no_published_or_temporary_file(
    database: DatabaseManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_directory = tmp_path / "backups"
    service = BackupService(
        database,
        make_settings(tmp_path),
        now_provider=lambda: datetime(2026, 8, 29, 14, 30, 0),
    )

    def fail_backup(destination: Path) -> None:
        del destination
        raise OSError("simulated SQLite backup failure")

    monkeypatch.setattr(service, "_backup_to", fail_backup)

    with pytest.raises(OSError, match="simulated SQLite backup failure"):
        service.create_backup(backup_directory)

    assert list(backup_directory.iterdir()) == []


def test_consecutive_backups_publish_distinct_metadata_files(
    database: DatabaseManager, tmp_path: Path
) -> None:
    backup_times = iter(
        [datetime(2026, 8, 29, 14, 30, 0), datetime(2026, 8, 29, 14, 30, 1)]
    )
    service = BackupService(
        database,
        make_settings(tmp_path),
        now_provider=lambda: next(backup_times),
    )

    first_result = service.create_backup(tmp_path / "backups")
    second_result = service.create_backup(tmp_path / "backups")

    assert first_result.database_path != second_result.database_path
    assert first_result.metadata_path != second_result.metadata_path
    assert first_result.metadata_path.is_file()
    assert second_result.metadata_path.is_file()


def test_metadata_failure_removes_the_database_backup(
    database: DatabaseManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_directory = tmp_path / "backups"
    service = BackupService(
        database,
        make_settings(tmp_path),
        now_provider=lambda: datetime(2026, 8, 29, 14, 30, 0),
    )

    def fail_metadata_write(destination: Path, metadata: dict[str, str]) -> None:
        del destination, metadata
        raise OSError("simulated metadata write failure")

    monkeypatch.setattr(service, "_write_metadata", fail_metadata_write)

    with pytest.raises(OSError, match="simulated metadata write failure"):
        service.create_backup(backup_directory)

    assert list(backup_directory.iterdir()) == []
