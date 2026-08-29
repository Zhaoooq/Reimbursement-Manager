from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import URL

from reimbursement_manager.config.runtime_resources import (
    alembic_config_path,
    migration_scripts_path,
)


def upgrade_database(*, project_root: Path, database_path: Path) -> None:
    """Apply all Alembic migrations to a SQLite database path."""
    resolved_database_path = Path(database_path).expanduser().resolve()
    resolved_database_path.parent.mkdir(parents=True, exist_ok=True)

    config_path = alembic_config_path()
    migration_path = migration_scripts_path()
    config = Config(str(config_path))
    config.set_main_option("script_location", str(migration_path))
    database_url = URL.create(
        "sqlite+pysqlite", database=str(resolved_database_path)
    )
    config.set_main_option(
        "sqlalchemy.url", database_url.render_as_string(hide_password=False)
    )
    command.upgrade(config, "head")
