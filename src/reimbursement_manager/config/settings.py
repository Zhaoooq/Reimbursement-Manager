from dataclasses import dataclass
from pathlib import Path

from reimbursement_manager.config.paths import AppPaths


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Filesystem settings for a local application instance."""

    paths: AppPaths
    archive_root: Path
    migration_project_root: Path | None = None

    @classmethod
    def default_project_root(cls) -> Path:
        """Return the source checkout root used by the Phase 1 local runtime."""
        return Path(__file__).resolve().parents[3]

    @classmethod
    def from_project_root(cls, project_root: Path) -> "AppSettings":
        root = Path(project_root).expanduser().resolve()
        paths = AppPaths.for_development(root)
        return cls(
            paths=paths,
            archive_root=paths.data_dir / "archive",
            migration_project_root=root,
        )

    @classmethod
    def from_paths(
        cls, paths: AppPaths, *, migration_project_root: Path
    ) -> "AppSettings":
        """Build settings for a runtime-selected data directory.

        The migration source remains the application project root.  Runtime data
        paths must not be used as Alembic's source tree in packaged mode.
        """
        return cls(
            paths=paths,
            archive_root=paths.data_dir / "archive",
            migration_project_root=Path(migration_project_root).expanduser().resolve(),
        )

    def ensure_directories(self) -> None:
        """Create application-owned runtime directories before services start."""
        self.paths.ensure_app_directories()

    @property
    def project_root(self) -> Path:
        """Return the development source root retained for migration tooling."""
        return self.migration_project_root or self.paths.app_data_dir

    @property
    def data_dir(self) -> Path:
        return self.paths.data_dir

    @property
    def database_path(self) -> Path:
        return self.paths.database_path

    @property
    def log_dir(self) -> Path:
        """Compatibility alias for the centralized logs directory."""
        return self.paths.logs_dir
