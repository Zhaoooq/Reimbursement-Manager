from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "create_release.py"


@pytest.fixture
def release_script():
    spec = importlib.util.spec_from_file_location("create_release_for_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_onedir(source: Path) -> None:
    (source / "ReimbursementManager.exe").parent.mkdir(parents=True)
    (source / "ReimbursementManager.exe").write_bytes(b"portable executable")
    (source / "_internal" / "reimbursement_manager" / "ui" / "styles").mkdir(
        parents=True
    )
    (source / "_internal" / "reimbursement_manager" / "ui" / "styles" / "base.qss").write_text(
        "QWidget {}", encoding="utf-8"
    )
    migrations = source / "_internal" / "reimbursement_manager" / "database" / "migrations"
    migrations.mkdir(parents=True)
    (migrations / "env.py").write_text("", encoding="utf-8")


def configure_paths(release_script, tmp_path: Path) -> Path:
    source = tmp_path / "dist" / "ReimbursementManager"
    release_script.SOURCE_DIRECTORY = source
    release_script.RELEASE_DIRECTORY = tmp_path / "release"
    return source


def test_create_release_copies_complete_onedir_and_writes_versioned_readme(
    release_script, tmp_path: Path
) -> None:
    source = configure_paths(release_script, tmp_path)
    make_onedir(source)
    (source / "_internal" / "runtime.dll").write_bytes(b"runtime")

    destination = release_script.create_release()

    assert destination == tmp_path / "release" / release_script.release_name()
    assert (destination / "ReimbursementManager.exe").read_bytes() == b"portable executable"
    assert (destination / "_internal" / "runtime.dll").is_file()
    readme = (destination / "README.txt").read_text(encoding="utf-8")
    assert release_script.__version__ in readme
    assert "%LOCALAPPDATA%\\ReimbursementManager\\data\\app.db" in readme


def test_create_release_refuses_existing_versioned_directory(release_script, tmp_path: Path) -> None:
    source = configure_paths(release_script, tmp_path)
    make_onedir(source)
    destination = release_script.RELEASE_DIRECTORY / release_script.release_name()
    destination.mkdir(parents=True)

    with pytest.raises(FileExistsError, match="Delete it explicitly"):
        release_script.create_release()


def test_create_release_rejects_user_data_in_onedir(release_script, tmp_path: Path) -> None:
    source = configure_paths(release_script, tmp_path)
    make_onedir(source)
    (source / "app.db").write_bytes(b"not a release artifact")

    with pytest.raises(RuntimeError, match="prohibited content"):
        release_script.create_release()

    assert not (release_script.RELEASE_DIRECTORY / release_script.release_name()).exists()
