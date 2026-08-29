from __future__ import annotations

from datetime import date
from pathlib import Path, PurePosixPath, PureWindowsPath

from reimbursement_manager.services.naming_service import NamingService


MAX_DIRECTORY_COMPONENT_LENGTH = 120


class StoragePathService:
    """Build relocatable archive paths without performing filesystem writes."""

    def __init__(
        self,
        archive_root: Path,
        *,
        naming_service: NamingService | None = None,
    ) -> None:
        self._archive_root = Path(archive_root).expanduser().resolve()
        self._naming_service = naming_service or NamingService()

    @property
    def archive_root(self) -> Path:
        return self._archive_root

    def get_batch_directory(self, *, batch_name: str, batch_date: date) -> Path:
        return self._archive_root / self._build_batch_directory_name(
            batch_name=batch_name, batch_date=batch_date
        )

    def get_item_directory(
        self,
        *,
        batch_name: str,
        batch_date: date,
        sequence_number: int,
        item_name: str,
    ) -> Path:
        batch_directory = self.get_batch_directory(
            batch_name=batch_name, batch_date=batch_date
        )
        return batch_directory / self._build_item_directory_name(
            sequence_number=sequence_number, item_name=item_name
        )

    def get_attachment_relative_path(
        self,
        *,
        batch_name: str,
        batch_date: date,
        sequence_number: int,
        item_name: str,
        stored_filename: str,
    ) -> PurePosixPath:
        self._validate_stored_filename(stored_filename)
        return PurePosixPath(
            self._build_batch_directory_name(
                batch_name=batch_name, batch_date=batch_date
            ),
            self._build_item_directory_name(
                sequence_number=sequence_number, item_name=item_name
            ),
            stored_filename,
        )

    def get_attachment_path(
        self,
        *,
        batch_name: str,
        batch_date: date,
        sequence_number: int,
        item_name: str,
        stored_filename: str,
    ) -> Path:
        relative_path = self.get_attachment_relative_path(
            batch_name=batch_name,
            batch_date=batch_date,
            sequence_number=sequence_number,
            item_name=item_name,
            stored_filename=stored_filename,
        )
        return self.resolve_relative_path(relative_path)

    def get_attachment_trash_path(
        self,
        *,
        attachment_id: int,
        relative_path: str | PurePosixPath,
    ) -> Path:
        if attachment_id <= 0:
            raise ValueError("attachment_id must be greater than zero")
        normalized_relative_path = self._normalize_relative_path(relative_path)
        return self._archive_root.joinpath(
            ".trash",
            f"{attachment_id:08d}",
            *normalized_relative_path.parts,
        )

    def resolve_relative_path(
        self, relative_path: str | PurePosixPath
    ) -> Path:
        normalized_relative_path = self._normalize_relative_path(relative_path)
        resolved = self._archive_root.joinpath(
            *normalized_relative_path.parts
        ).resolve()
        if not resolved.is_relative_to(self._archive_root):
            raise ValueError("relative_path must remain inside archive_root")
        return resolved

    def _build_batch_directory_name(
        self, *, batch_name: str, batch_date: date
    ) -> str:
        prefix = f"{batch_date:%Y-%m}_"
        safe_name = self._naming_service.sanitize_component(
            batch_name,
            fallback="未命名批次",
            max_length=MAX_DIRECTORY_COMPONENT_LENGTH - len(prefix),
        )
        return f"{prefix}{safe_name}"

    def _build_item_directory_name(
        self, *, sequence_number: int, item_name: str
    ) -> str:
        if sequence_number <= 0:
            raise ValueError("sequence_number must be greater than zero")
        prefix = f"{sequence_number:03d}_"
        component_budget = MAX_DIRECTORY_COMPONENT_LENGTH - len(prefix)
        if component_budget <= 0:
            raise ValueError("sequence_number is too long for a directory name")
        safe_name = self._naming_service.sanitize_component(
            item_name,
            fallback="未命名物品",
            max_length=component_budget,
        )
        return f"{prefix}{safe_name}"

    def _validate_stored_filename(self, stored_filename: str) -> None:
        if not stored_filename or "/" in stored_filename or "\\" in stored_filename:
            raise ValueError("stored_filename must be one safe path component")
        windows_path = PureWindowsPath(stored_filename)
        if windows_path.drive or windows_path.is_absolute():
            raise ValueError("stored_filename must be one safe path component")
        sanitized = self._naming_service.sanitize_component(
            stored_filename, fallback="invalid"
        )
        if sanitized != stored_filename:
            raise ValueError("stored_filename must already be Windows-safe")

    @staticmethod
    def _normalize_relative_path(
        relative_path: str | PurePosixPath,
    ) -> PurePosixPath:
        raw_path = str(relative_path)
        if not raw_path:
            raise ValueError("relative_path cannot be blank")

        windows_path = PureWindowsPath(raw_path)
        if windows_path.drive or windows_path.is_absolute():
            raise ValueError("relative_path must not contain a drive or UNC root")

        portable_path = raw_path.replace("\\", "/")
        if portable_path.startswith("/"):
            raise ValueError("relative_path must not be absolute")
        parts = portable_path.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("relative_path contains an unsafe path segment")
        return PurePosixPath(*parts)
