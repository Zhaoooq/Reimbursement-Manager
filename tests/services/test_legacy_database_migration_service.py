from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

import pytest
from sqlalchemy import text

from reimbursement_manager.config.settings import AppSettings
from reimbursement_manager.database import DatabaseManager, upgrade_database
from reimbursement_manager.services.legacy_database_migration_service import (
    LegacyDatabaseMigrationError,
    LegacyDatabaseMigrationService,
    LegacyDatabaseMigrationStatus,
)


PROJECT_ROOT = AppSettings.default_project_root()
INITIAL_REVISION = "20260828_0001"
HEAD_REVISION = "20260829_0002"


def create_database(path: Path, batch_name: str) -> None:
    upgrade_database(project_root=PROJECT_ROOT, database_path=path)
    manager = DatabaseManager.from_sqlite_path(path)
    try:
        with manager.transaction() as session:
            session.execute(
                text("INSERT INTO reimbursement_batches (name, status) VALUES (:name, 'collecting')"),
                {"name": batch_name},
            )
    finally:
        manager.dispose()


def read_batch_name(path: Path) -> str:
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute("SELECT name FROM reimbursement_batches").fetchone()
    assert row is not None
    return str(row[0])


def make_service(source: Path, destination: Path, **kwargs: object) -> LegacyDatabaseMigrationService:
    return LegacyDatabaseMigrationService(
        legacy_database_path=source,
        destination_database_path=destination,
        migration_project_root=PROJECT_ROOT,
        **kwargs,
    )


def test_migrates_valid_legacy_database_and_keeps_source(tmp_path: Path) -> None:
    source = tmp_path / "legacy" / "app.db"
    destination = tmp_path / "production" / "app.db"
    source.parent.mkdir()
    create_database(source, "旧业务数据")

    result = make_service(source, destination).migrate_if_needed()

    assert result.status is LegacyDatabaseMigrationStatus.MIGRATED
    assert result.schema_version_before == HEAD_REVISION
    assert result.schema_version_after == HEAD_REVISION
    assert read_batch_name(destination) == "旧业务数据"
    assert source.is_file()
    assert read_batch_name(source) == "旧业务数据"


def test_skips_when_production_database_already_exists(tmp_path: Path) -> None:
    source = tmp_path / "legacy.db"
    destination = tmp_path / "production" / "app.db"
    create_database(source, "旧数据")
    create_database(destination, "现有生产数据")

    result = make_service(source, destination).migrate_if_needed()

    assert result.status is LegacyDatabaseMigrationStatus.DESTINATION_EXISTS
    assert read_batch_name(destination) == "现有生产数据"


def test_reports_missing_legacy_database_as_normal_first_install(tmp_path: Path) -> None:
    source = tmp_path / "missing.db"
    destination = tmp_path / "production" / "app.db"

    result = make_service(source, destination).migrate_if_needed()

    assert result.status is LegacyDatabaseMigrationStatus.NO_LEGACY_DATABASE
    assert not destination.exists()


def test_rejects_invalid_legacy_database_without_creating_destination(tmp_path: Path) -> None:
    source = tmp_path / "invalid.db"
    destination = tmp_path / "production" / "app.db"
    source.write_text("not sqlite", encoding="utf-8")

    with pytest.raises(LegacyDatabaseMigrationError, match="left unchanged"):
        make_service(source, destination).migrate_if_needed()

    assert not destination.exists()
    assert source.read_text(encoding="utf-8") == "not sqlite"


def test_upgrades_known_old_revision_before_publishing(tmp_path: Path) -> None:
    source = tmp_path / "legacy.db"
    destination = tmp_path / "production" / "app.db"
    create_database(source, "旧版本数据")
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import URL

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        URL.create("sqlite+pysqlite", database=str(source.resolve())).render_as_string(
            hide_password=False
        ),
    )
    command.downgrade(config, INITIAL_REVISION)

    result = make_service(source, destination).migrate_if_needed()

    assert result.status is LegacyDatabaseMigrationStatus.MIGRATED
    assert result.schema_version_before == INITIAL_REVISION
    assert result.schema_version_after == HEAD_REVISION
    assert read_batch_name(destination) == "旧版本数据"


def test_copy_failure_leaves_no_production_database(tmp_path: Path) -> None:
    source = tmp_path / "legacy.db"
    destination = tmp_path / "production" / "app.db"
    create_database(source, "旧数据")

    def fail_copy(_source: Path, _destination: Path) -> None:
        raise OSError("copy failed")

    with pytest.raises(LegacyDatabaseMigrationError):
        make_service(source, destination, backup_to=fail_copy).migrate_if_needed()

    assert not destination.exists()


def test_migration_failure_leaves_no_production_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "legacy.db"
    destination = tmp_path / "production" / "app.db"
    create_database(source, "旧数据")
    from reimbursement_manager.services import legacy_database_migration_service

    def fail_upgrade(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("upgrade failed")

    monkeypatch.setattr(legacy_database_migration_service, "upgrade_database", fail_upgrade)
    with closing(sqlite3.connect(source)) as connection:
        connection.execute("UPDATE alembic_version SET version_num = ?", (INITIAL_REVISION,))
        connection.commit()

    with pytest.raises(LegacyDatabaseMigrationError):
        make_service(source, destination).migrate_if_needed()

    assert not destination.exists()


def test_publish_failure_leaves_no_production_database(tmp_path: Path) -> None:
    source = tmp_path / "legacy.db"
    destination = tmp_path / "production" / "app.db"
    create_database(source, "旧数据")

    def fail_publish(_source: Path, _destination: Path) -> None:
        raise OSError("publish failed")

    with pytest.raises(LegacyDatabaseMigrationError):
        make_service(source, destination, publish_file=fail_publish).migrate_if_needed()

    assert not destination.exists()


def test_chinese_paths_migrate_normally(tmp_path: Path) -> None:
    source = tmp_path / "旧目录" / "报销数据.db"
    destination = tmp_path / "用户数据" / "生产数据.db"
    source.parent.mkdir()
    create_database(source, "中文路径数据")

    result = make_service(source, destination).migrate_if_needed()

    assert result.status is LegacyDatabaseMigrationStatus.MIGRATED
    assert read_batch_name(destination) == "中文路径数据"
