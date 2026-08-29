from pathlib import Path

import pytest

from reimbursement_manager.config import AppPaths, LocalAppDataUnavailableError


def test_development_paths_keep_the_existing_project_data_directory(
    tmp_path: Path,
) -> None:
    paths = AppPaths.for_current_runtime(project_root=tmp_path, frozen=False)

    assert paths.app_data_dir == tmp_path.resolve()
    assert paths.database_path == tmp_path.resolve() / "data" / "app.db"


def test_packaged_paths_use_local_app_data_environment_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    local_app_data = tmp_path / "中文 LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))

    paths = AppPaths.for_current_runtime(
        project_root=tmp_path / "unused-project-root",
        frozen=True,
    )

    expected_root = local_app_data.resolve() / "ReimbursementManager"
    assert paths.app_data_dir == expected_root
    assert paths.database_path == expected_root / "data" / "app.db"
    assert paths.logs_dir == expected_root / "logs"
    assert paths.config_dir == expected_root / "config"
    assert paths.backups_dir == expected_root / "backups"
    assert not expected_root.exists()


def test_ensure_app_directories_creates_only_application_owned_directories(
    tmp_path: Path,
) -> None:
    paths = AppPaths.for_packaged(local_app_data=tmp_path / "用户数据")

    paths.ensure_app_directories()

    assert paths.data_dir.is_dir()
    assert paths.logs_dir.is_dir()
    assert paths.config_dir.is_dir()
    assert paths.backups_dir.is_dir()
    assert not (paths.app_data_dir / "archive").exists()


def test_ensure_app_directories_is_idempotent(tmp_path: Path) -> None:
    paths = AppPaths.for_packaged(local_app_data=tmp_path)

    paths.ensure_app_directories()
    paths.ensure_app_directories()

    assert paths.database_path.parent.is_dir()


def test_packaged_paths_raise_clear_error_without_local_app_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    with pytest.raises(LocalAppDataUnavailableError, match="LOCALAPPDATA"):
        AppPaths.for_current_runtime(project_root=tmp_path, frozen=True)
