from pathlib import Path
import sys

from reimbursement_manager.config.runtime_resources import (
    alembic_config_path,
    application_resource_root,
    migration_scripts_path,
)


def test_development_resource_paths_use_project_checkout() -> None:
    root = application_resource_root(frozen=False)

    assert alembic_config_path(frozen=False) == root / "alembic.ini"
    assert migration_scripts_path(frozen=False) == (
        root / "src" / "reimbursement_manager" / "database" / "migrations"
    )


def test_frozen_resource_paths_use_pyinstaller_bundle(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert application_resource_root(frozen=True) == tmp_path.resolve()
    assert alembic_config_path(frozen=True) == tmp_path / "alembic.ini"
    assert migration_scripts_path(frozen=True) == (
        tmp_path / "reimbursement_manager" / "database" / "migrations"
    )
