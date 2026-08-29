"""Safe one-time migration of the explicit development database to production."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from enum import StrEnum
import logging
import os
from pathlib import Path
import sqlite3
from tempfile import NamedTemporaryFile

from reimbursement_manager.database import upgrade_database
from reimbursement_manager.services.restore_service import RestoreService


logger = logging.getLogger(__name__)


class LegacyDatabaseMigrationStatus(StrEnum):
    """Outcomes that do not represent a migration error."""

    MIGRATED = "migrated"
    NO_LEGACY_DATABASE = "no_legacy_database"
    DESTINATION_EXISTS = "destination_exists"


class LegacyDatabaseMigrationError(RuntimeError):
    """A legacy database was found but could not be safely migrated."""


@dataclass(frozen=True, slots=True)
class LegacyDatabaseMigrationResult:
    """Details of a checked legacy migration attempt."""

    status: LegacyDatabaseMigrationStatus
    source_path: Path
    destination_path: Path
    schema_version_before: str | None = None
    schema_version_after: str | None = None


class LegacyDatabaseMigrationService:
    """Copy one explicit legacy SQLite database into the production location.

    This deliberately never searches for candidates and never moves the source
    database.  A destination database is published only after its copy and
    Alembic upgrade have passed the same validation used by database restore.
    """

    def __init__(
        self,
        *,
        legacy_database_path: Path,
        destination_database_path: Path,
        migration_project_root: Path,
        backup_to: Callable[[Path, Path], None] | None = None,
        publish_file: Callable[[Path, Path], None] = os.link,
    ) -> None:
        self._legacy_database_path = Path(legacy_database_path).expanduser().resolve()
        self._destination_database_path = (
            Path(destination_database_path).expanduser().resolve()
        )
        self._migration_project_root = Path(migration_project_root).expanduser().resolve()
        self._backup_to = backup_to or self._sqlite_backup_to
        self._publish_file = publish_file

    def migrate_if_needed(self) -> LegacyDatabaseMigrationResult:
        """Migrate only if the explicit source exists and destination is absent."""
        source_path = self._legacy_database_path
        destination_path = self._destination_database_path
        if destination_path.exists():
            logger.info("Legacy database migration skipped: production database exists")
            return LegacyDatabaseMigrationResult(
                LegacyDatabaseMigrationStatus.DESTINATION_EXISTS,
                source_path,
                destination_path,
            )
        if not source_path.exists():
            logger.info("Legacy database migration skipped: no legacy database")
            return LegacyDatabaseMigrationResult(
                LegacyDatabaseMigrationStatus.NO_LEGACY_DATABASE,
                source_path,
                destination_path,
            )

        logger.info("Legacy database migration started from %s", source_path)
        temporary_path: Path | None = None
        try:
            schema_version_before = RestoreService._validate_database(source_path)
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self._create_temporary_path(destination_path)
            self._backup_to(source_path, temporary_path)
            copied_schema_version = RestoreService._validate_database(temporary_path)
            if copied_schema_version != schema_version_before:
                raise LegacyDatabaseMigrationError(
                    "Copied legacy database schema version did not match its source."
                )

            current_schema_revision = RestoreService._current_schema_revision()
            if copied_schema_version != current_schema_revision:
                upgrade_database(
                    project_root=self._migration_project_root,
                    database_path=temporary_path,
                )
            schema_version_after = RestoreService._validate_database(temporary_path)
            if schema_version_after != current_schema_revision:
                raise LegacyDatabaseMigrationError(
                    "Migrated production database is not at the current schema revision."
                )
            if destination_path.exists():
                raise LegacyDatabaseMigrationError(
                    "Production database appeared during legacy migration; it was not overwritten."
                )
            self._publish_file(temporary_path, destination_path)
            temporary_path.unlink()
            temporary_path = None
        except Exception as error:
            logger.exception("Legacy database migration failed")
            if isinstance(error, LegacyDatabaseMigrationError):
                raise
            raise LegacyDatabaseMigrationError(
                "Legacy database migration failed; the legacy database was left unchanged."
            ) from error
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

        logger.info("Legacy database migration completed successfully")
        return LegacyDatabaseMigrationResult(
            LegacyDatabaseMigrationStatus.MIGRATED,
            source_path,
            destination_path,
            schema_version_before,
            schema_version_after,
        )

    @staticmethod
    def _create_temporary_path(destination_path: Path) -> Path:
        with NamedTemporaryFile(
            dir=destination_path.parent,
            prefix=f".{destination_path.name}.",
            suffix=".legacy-migration.tmp",
            delete=False,
        ) as temporary_file:
            return Path(temporary_file.name)

    @staticmethod
    def _sqlite_backup_to(source_path: Path, destination_path: Path) -> None:
        source_uri = f"file:{source_path.as_posix()}?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True)) as source_connection:
            with closing(sqlite3.connect(destination_path)) as destination_connection:
                source_connection.backup(destination_connection)
                destination_connection.commit()
