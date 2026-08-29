from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import URL, create_engine, inspect, text

from reimbursement_manager.database.models import Base


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_ROOT = (
    PROJECT_ROOT / "src" / "reimbursement_manager" / "database" / "migrations"
)
BUSINESS_TABLES = {
    "attachments",
    "items",
    "material_requirements",
    "material_types",
    "reimbursement_batches",
    "template_materials",
    "templates",
}


def migration_config(database_path: Path) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(MIGRATION_ROOT))
    database_url = URL.create(
        "sqlite+pysqlite", database=str(database_path.resolve())
    ).render_as_string(hide_password=False)
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_upgrade_head_creates_all_business_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "fresh.db"
    config = migration_config(database_path)

    command.upgrade(config, "head")

    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        assert BUSINESS_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_head_is_repeatable_and_records_current_revision(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "repeat.db"
    config = migration_config(database_path)

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        with engine.connect() as connection:
            current_revision = connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        expected_revision = ScriptDirectory.from_config(config).get_current_head()
        assert current_revision == expected_revision
    finally:
        engine.dispose()


def test_migrated_schema_matches_model_metadata(tmp_path: Path) -> None:
    database_path = tmp_path / "compare.db"
    config = migration_config(database_path)
    command.upgrade(config, "head")

    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            differences = compare_metadata(context, Base.metadata)

        assert differences == []
    finally:
        engine.dispose()


def test_initial_revision_can_downgrade_to_base(tmp_path: Path) -> None:
    database_path = tmp_path / "downgrade.db"
    config = migration_config(database_path)
    command.upgrade(config, "head")

    command.downgrade(config, "base")

    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        remaining_tables = set(inspect(engine).get_table_names())
        assert BUSINESS_TABLES.isdisjoint(remaining_tables)
    finally:
        engine.dispose()
