from __future__ import annotations

import inspect
from pathlib import Path
import tomllib

import reimbursement_manager
from reimbursement_manager.services import backup_service
from reimbursement_manager.version import __version__


def test_package_public_version_uses_the_canonical_version() -> None:
    assert __version__ == "0.2.0"
    assert reimbursement_manager.__version__ == __version__


def test_pyproject_build_version_uses_the_canonical_version() -> None:
    project_root = Path(__file__).resolve().parents[1]
    with (project_root / "pyproject.toml").open("rb") as project_file:
        pyproject = tomllib.load(project_file)

    assert "version" not in pyproject["project"]
    assert pyproject["project"]["dynamic"] == ["version"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "reimbursement_manager.version.__version__"
    }


def test_backup_service_imports_the_canonical_version() -> None:
    source = inspect.getsource(backup_service)

    assert "from reimbursement_manager.version import __version__" in source
    assert '"0.1.0"' not in source
