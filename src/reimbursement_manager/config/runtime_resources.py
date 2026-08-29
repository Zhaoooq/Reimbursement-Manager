"""Locations of static application resources in source and frozen runtimes."""

from __future__ import annotations

from pathlib import Path
import sys

from reimbursement_manager.config.paths import is_packaged_runtime


def application_resource_root(*, frozen: bool | None = None) -> Path:
    """Return the root containing bundled static resources.

    Development resources remain in the project checkout.  PyInstaller exposes
    collected data files below ``sys._MEIPASS`` for the lifetime of the frozen
    process, so no source checkout is needed at runtime.
    """
    if is_packaged_runtime(frozen=frozen):
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root is None:
            raise RuntimeError("Frozen application resources are unavailable.")
        return Path(bundle_root).resolve()
    return Path(__file__).resolve().parents[3]


def alembic_config_path(*, frozen: bool | None = None) -> Path:
    """Return the bundled Alembic configuration file."""
    return application_resource_root(frozen=frozen) / "alembic.ini"


def migration_scripts_path(*, frozen: bool | None = None) -> Path:
    """Return the directory containing the Alembic migration environment."""
    root = application_resource_root(frozen=frozen)
    if is_packaged_runtime(frozen=frozen):
        return root / "reimbursement_manager" / "database" / "migrations"
    return root / "src" / "reimbursement_manager" / "database" / "migrations"
