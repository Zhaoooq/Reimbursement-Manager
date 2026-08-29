from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
from tempfile import NamedTemporaryFile

from sqlalchemy import text

from reimbursement_manager.config.settings import AppSettings
from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.version import __version__


BACKUP_FILENAME_PREFIX = "reimbursement_backup"


@dataclass(frozen=True, slots=True)
class BackupResult:
    """Paths published by one complete database backup."""

    database_path: Path
    metadata_path: Path


class BackupService:
    """Create consistent SQLite backups without copying the live database file."""

    def __init__(
        self,
        database: DatabaseManager,
        settings: AppSettings,
        *,
        now_provider: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._database = database
        self._settings = settings
        self._now_provider = now_provider

    def create_backup(self, backup_directory: Path) -> BackupResult:
        """Back up the current database into ``backup_directory``.

        The SQLite backup API writes to a temporary database in the selected
        directory.  The final timestamped file is published only after the
        backup completes successfully.
        """
        destination_directory = Path(backup_directory).expanduser()
        destination_directory.mkdir(parents=True, exist_ok=True)
        if not destination_directory.is_dir():
            raise NotADirectoryError(
                f"Backup destination is not a directory: {destination_directory}"
            )

        backup_time = self._now_provider()
        destination = destination_directory / self._build_filename(backup_time)
        metadata_destination = destination.with_name(f"{destination.stem}_info.json")
        for path in (destination, metadata_destination):
            if path.exists():
                raise FileExistsError(f"Backup result already exists: {path}")

        temporary_database_path: Path | None = None
        temporary_metadata_path: Path | None = None
        database_published = False
        try:
            with NamedTemporaryFile(
                dir=destination_directory,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_database_path = Path(temporary_file.name)

            self._backup_to(temporary_database_path)
            os.replace(temporary_database_path, destination)
            temporary_database_path = None
            database_published = True

            with NamedTemporaryFile(
                dir=destination_directory,
                prefix=f".{metadata_destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_metadata_path = Path(temporary_file.name)

            self._write_metadata(
                temporary_metadata_path,
                {
                    "backup_time": backup_time.isoformat(),
                    "app_version": __version__,
                    "archive_root": str(self._settings.archive_root),
                    "database_schema_version": self._read_schema_version(destination),
                    "database_filename": destination.name,
                },
            )
            os.replace(temporary_metadata_path, metadata_destination)
            temporary_metadata_path = None
            return BackupResult(destination, metadata_destination)
        except Exception:
            if database_published and destination.exists():
                destination.unlink()
            raise
        finally:
            for temporary_path in (temporary_database_path, temporary_metadata_path):
                if temporary_path is not None and temporary_path.exists():
                    temporary_path.unlink()

    @staticmethod
    def _build_filename(backup_time: datetime) -> str:
        timestamp = backup_time.strftime("%Y-%m-%d_%H%M%S")
        return f"{BACKUP_FILENAME_PREFIX}_{timestamp}.db"

    @staticmethod
    def _write_metadata(destination: Path, metadata: dict[str, str]) -> None:
        with destination.open("w", encoding="utf-8") as metadata_file:
            json.dump(metadata, metadata_file, ensure_ascii=False, indent=2)
            metadata_file.write("\n")

    @staticmethod
    def _read_schema_version(backup_path: Path) -> str:
        with closing(sqlite3.connect(backup_path)) as connection:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        if row is None:
            raise RuntimeError("Backup database does not contain an Alembic version")
        return str(row[0])

    def _backup_to(self, destination: Path) -> None:
        if self._database.engine.dialect.name != "sqlite":
            raise ValueError("BackupService only supports SQLite databases")

        with closing(self._database.engine.raw_connection()) as source_proxy:
            source_connection = source_proxy.driver_connection
            if not isinstance(source_connection, sqlite3.Connection):
                raise TypeError("Expected a SQLite DB-API connection")

            with closing(sqlite3.connect(destination)) as destination_connection:
                source_connection.backup(destination_connection)
                destination_connection.commit()
