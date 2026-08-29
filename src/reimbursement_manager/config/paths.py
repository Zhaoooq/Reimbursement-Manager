"""Centralized runtime paths for development and packaged Windows builds."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys


APPLICATION_DIRECTORY_NAME = "ReimbursementManager"


class LocalAppDataUnavailableError(RuntimeError):
    """Raised when a packaged Windows runtime has no LOCALAPPDATA directory."""


def is_packaged_runtime(*, frozen: bool | None = None) -> bool:
    """Return whether this process is running from a frozen application bundle."""
    return getattr(sys, "frozen", False) if frozen is None else frozen


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Filesystem locations owned by the application runtime.

    Development keeps using the checkout's ``data`` directory.  A packaged
    runtime uses the per-user Windows LocalAppData location instead.
    """

    app_data_dir: Path
    data_dir: Path
    database_path: Path
    logs_dir: Path
    config_dir: Path
    backups_dir: Path

    @classmethod
    def for_development(cls, project_root: Path) -> "AppPaths":
        """Build paths compatible with the existing checkout-local layout."""
        root = Path(project_root).expanduser().resolve()
        data_dir = root / "data"
        return cls(
            app_data_dir=root,
            data_dir=data_dir,
            database_path=data_dir / "app.db",
            logs_dir=data_dir / "logs",
            config_dir=data_dir / "config",
            backups_dir=data_dir / "backups",
        )

    @classmethod
    def for_packaged(cls, *, local_app_data: Path | None = None) -> "AppPaths":
        """Build paths for a frozen Windows application without creating them."""
        local_app_data_root = local_app_data
        if local_app_data_root is None:
            configured_path = os.environ.get("LOCALAPPDATA")
            if not configured_path:
                raise LocalAppDataUnavailableError(
                    "LOCALAPPDATA is required for a packaged ReimbursementManager "
                    "runtime."
                )
            local_app_data_root = Path(configured_path)

        app_data_dir = (
            Path(local_app_data_root).expanduser().resolve()
            / APPLICATION_DIRECTORY_NAME
        )
        data_dir = app_data_dir / "data"
        return cls(
            app_data_dir=app_data_dir,
            data_dir=data_dir,
            database_path=data_dir / "app.db",
            logs_dir=app_data_dir / "logs",
            config_dir=app_data_dir / "config",
            backups_dir=app_data_dir / "backups",
        )

    @classmethod
    def for_current_runtime(
        cls,
        *,
        project_root: Path,
        local_app_data: Path | None = None,
        frozen: bool | None = None,
    ) -> "AppPaths":
        """Select the one path strategy for the active runtime."""
        if is_packaged_runtime(frozen=frozen):
            return cls.for_packaged(local_app_data=local_app_data)
        return cls.for_development(project_root)

    def ensure_app_directories(self) -> None:
        """Create application-owned runtime directories idempotently.

        Attachment storage is intentionally excluded: ``archive_root`` belongs
        to the user's independent archive configuration.
        """
        for directory in (
            self.data_dir,
            self.logs_dir,
            self.config_dir,
            self.backups_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
