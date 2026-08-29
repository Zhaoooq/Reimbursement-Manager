from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sqlite3
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4

from reimbursement_manager.config.settings import AppSettings
from reimbursement_manager.database import DatabaseManager, upgrade_database
from reimbursement_manager.services.backup_service import BackupResult, BackupService


logger = logging.getLogger(__name__)

REQUIRED_TABLES = frozenset(
    {
        "reimbursement_batches",
        "items",
        "material_types",
        "material_requirements",
        "attachments",
        "templates",
        "template_materials",
    }
)
ALEMBIC_VERSION_TABLE = "alembic_version"
SAFETY_BACKUP_DIRECTORY_NAME = "backups"


class RestoreServiceError(RuntimeError):
    """Base error for a database restore that was not completed."""


class InvalidBackupDatabaseError(RestoreServiceError):
    """The selected file is not a usable reimbursement database backup."""


class UnknownSchemaRevisionError(InvalidBackupDatabaseError):
    """The backup's Alembic revision is not known by this application."""


class SafetyBackupError(RestoreServiceError):
    """The current database could not be safely backed up before restore."""


class DatabaseReplacementError(RestoreServiceError):
    """The replacement failed and the original database was restored when possible."""


@dataclass(frozen=True, slots=True)
class RestoreResult:
    """Details of one successfully completed database restore."""

    restored_database_path: Path
    source_backup_path: Path
    safety_backup_path: Path
    schema_version: str


class RestoreService:
    """Safely replace the active SQLite database with a verified backup.

    The service deliberately only replaces the database file.  Attachment
    archives remain under the user's control and are never moved or deleted.
    Callers must not keep open sessions or transactions while invoking it.
    """

    def __init__(
        self,
        database: DatabaseManager,
        settings: AppSettings,
        *,
        backup_service: BackupService | None = None,
        replace_file: Callable[[Path, Path], None] = os.replace,
    ) -> None:
        self._database = database
        self._settings = settings
        self._backup_service = backup_service or BackupService(database, settings)
        self._replace_file = replace_file

    def restore_database(self, backup_db_path: Path) -> RestoreResult:
        """Restore ``backup_db_path`` after validation and a safety backup.

        The original file is retained as a rollback file until the replacement
        has itself passed the same SQLite/schema validation.
        """
        source_path = Path(backup_db_path).expanduser().resolve()
        target_path = self._settings.database_path.expanduser().resolve()
        logger.info("Database restore started from %s", source_path)

        schema_version = self._validate_database(source_path)
        self._validate_metadata_if_present(source_path, schema_version)
        self._validate_current_database_path(target_path)
        self._ensure_no_checked_out_connections()

        try:
            safety_backup = self._backup_service.create_backup(
                self._settings.data_dir / SAFETY_BACKUP_DIRECTORY_NAME
            )
        except Exception as error:
            logger.exception("Database restore safety backup failed")
            raise SafetyBackupError(
                "Current database safety backup failed; restore was not started."
            ) from error

        temporary_path: Path | None = None
        rollback_path: Path | None = None
        original_moved = False
        replacement_published = False
        preserve_rollback_file = False
        try:
            self._database.dispose()
            temporary_path = self._copy_to_temporary(source_path, target_path.parent)
            self._validate_database(temporary_path)

            rollback_path = target_path.with_name(
                f".{target_path.name}.{uuid4().hex}.rollback"
            )
            self._replace_file(target_path, rollback_path)
            original_moved = True
            self._replace_file(temporary_path, target_path)
            temporary_path = None
            replacement_published = True

            restored_schema_version = self._migrate_replacement(
                target_path, schema_version
            )
            self._validate_replacement(target_path)
            rollback_path.unlink()
            rollback_path = None
        except Exception as error:
            logger.exception("Database restore replacement failed")
            rollback_error = self._rollback(
                target_path=target_path,
                rollback_path=rollback_path,
                original_moved=original_moved,
                replacement_published=replacement_published,
            )
            if rollback_error is not None:
                logger.exception("Database restore rollback failed", exc_info=rollback_error)
                preserve_rollback_file = True
                raise DatabaseReplacementError(
                    "Database restore failed and the original database could not be restored."
                ) from error
            logger.warning("Database restore rolled back to the original database")
            raise DatabaseReplacementError(
                "Database restore failed; the original database was restored."
            ) from error
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
            if (
                not preserve_rollback_file
                and rollback_path is not None
                and rollback_path.exists()
            ):
                rollback_path.unlink()

        logger.info("Database restore completed successfully")
        return RestoreResult(
            restored_database_path=target_path,
            source_backup_path=source_path,
            safety_backup_path=safety_backup.database_path,
            schema_version=restored_schema_version,
        )

    @staticmethod
    def _copy_to_temporary(source_path: Path, destination_directory: Path) -> Path:
        with NamedTemporaryFile(
            dir=destination_directory,
            prefix=f".{source_path.stem}.",
            suffix=".restore.tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
        try:
            shutil.copyfile(source_path, temporary_path)
        except Exception:
            if temporary_path.exists():
                temporary_path.unlink()
            raise
        return temporary_path

    def _validate_replacement(self, database_path: Path) -> None:
        self._validate_database(database_path)

    def _migrate_replacement(
        self, database_path: Path, schema_version: str
    ) -> str:
        current_schema_revision = self._current_schema_revision()
        if schema_version != current_schema_revision:
            upgrade_database(
                project_root=self._settings.project_root,
                database_path=database_path,
            )
        restored_schema_version = self._validate_database(database_path)
        if restored_schema_version != current_schema_revision:
            raise DatabaseReplacementError(
                "Restored database was not migrated to the current schema revision."
            )
        return restored_schema_version

    @classmethod
    def _validate_database(cls, database_path: Path) -> str:
        if not database_path.exists():
            logger.warning("Database restore backup validation failed: file is missing")
            raise InvalidBackupDatabaseError("Backup database file does not exist.")
        if not database_path.is_file():
            logger.warning("Database restore backup validation failed: not a regular file")
            raise InvalidBackupDatabaseError("Backup database path is not a regular file.")

        try:
            with closing(sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)) as connection:
                integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
                if integrity_row != ("ok",):
                    raise InvalidBackupDatabaseError("Backup database integrity check failed.")
                table_rows = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
                table_names = {str(row[0]) for row in table_rows}
                missing_tables = REQUIRED_TABLES - table_names
                if missing_tables:
                    raise InvalidBackupDatabaseError(
                        "Backup database is missing required tables: "
                        + ", ".join(sorted(missing_tables))
                    )
                if ALEMBIC_VERSION_TABLE not in table_names:
                    raise InvalidBackupDatabaseError(
                        "Backup database is missing the Alembic version table."
                    )
                revisions = connection.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchall()
        except InvalidBackupDatabaseError:
            logger.warning("Database restore backup validation failed")
            raise
        except sqlite3.Error as error:
            logger.warning("Database restore backup validation failed", exc_info=True)
            raise InvalidBackupDatabaseError(
                "Backup database cannot be opened as SQLite."
            ) from error

        if len(revisions) != 1 or not revisions[0][0]:
            raise InvalidBackupDatabaseError(
                "Backup database has an invalid Alembic schema revision."
            )
        schema_version = str(revisions[0][0])
        if schema_version not in cls._known_schema_revisions():
            raise UnknownSchemaRevisionError(
                f"Backup database schema revision is not supported: {schema_version}"
            )
        return schema_version

    @staticmethod
    def _known_schema_revisions() -> frozenset[str]:
        versions_directory = (
            Path(__file__).resolve().parents[1]
            / "database"
            / "migrations"
            / "versions"
        )
        revisions: set[str] = set()
        for migration_path in versions_directory.glob("*.py"):
            match = re.search(
                r'^revision:\s*str\s*=\s*["\']([^"\']+)["\']',
                migration_path.read_text(encoding="utf-8"),
                flags=re.MULTILINE,
            )
            if match is not None:
                revisions.add(match.group(1))
        return frozenset(revisions)

    @classmethod
    def _current_schema_revision(cls) -> str:
        versions_directory = (
            Path(__file__).resolve().parents[1]
            / "database"
            / "migrations"
            / "versions"
        )
        revisions = cls._known_schema_revisions()
        parent_revisions: set[str] = set()
        for migration_path in versions_directory.glob("*.py"):
            match = re.search(
                r'^down_revision:\s*str\s*\|\s*None\s*=\s*["\']([^"\']+)["\']',
                migration_path.read_text(encoding="utf-8"),
                flags=re.MULTILINE,
            )
            if match is not None:
                parent_revisions.add(match.group(1))
        heads = revisions - parent_revisions
        if len(heads) != 1:
            raise RestoreServiceError(
                "Application migrations do not define exactly one current schema revision."
            )
        return next(iter(heads))

    @staticmethod
    def _validate_current_database_path(database_path: Path) -> None:
        if not database_path.exists() or not database_path.is_file():
            raise RestoreServiceError("Current database file is unavailable for restore.")

    def _ensure_no_checked_out_connections(self) -> None:
        checked_out = getattr(self._database.engine.pool, "checkedout", None)
        if checked_out is not None and checked_out() > 0:
            raise RestoreServiceError(
                "Database has active connections; finish current work before restoring."
            )

    @staticmethod
    def _validate_metadata_if_present(source_path: Path, schema_version: str) -> None:
        metadata_path = source_path.with_name(f"{source_path.stem}_info.json")
        if not metadata_path.exists():
            return
        try:
            metadata: Any = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise InvalidBackupDatabaseError("Backup metadata JSON is invalid.") from error
        if not isinstance(metadata, dict):
            raise InvalidBackupDatabaseError("Backup metadata JSON must contain an object.")
        database_filename = metadata.get("database_filename")
        if database_filename is not None and database_filename != source_path.name:
            raise InvalidBackupDatabaseError(
                "Backup metadata database filename does not match the selected file."
            )
        metadata_schema_version = metadata.get("database_schema_version")
        if (
            metadata_schema_version is not None
            and metadata_schema_version != schema_version
        ):
            raise InvalidBackupDatabaseError(
                "Backup metadata schema version does not match the database."
            )

    def _rollback(
        self,
        *,
        target_path: Path,
        rollback_path: Path | None,
        original_moved: bool,
        replacement_published: bool,
    ) -> Exception | None:
        if not original_moved or rollback_path is None or not rollback_path.exists():
            return None
        try:
            if replacement_published and target_path.exists():
                target_path.unlink()
            self._replace_file(rollback_path, target_path)
        except Exception as error:
            return error
        return None
