from pathlib import Path

from reimbursement_manager.config import AppSettings


def test_settings_use_project_relative_data_paths(tmp_path: Path) -> None:
    settings = AppSettings.from_project_root(tmp_path)

    assert settings.project_root == tmp_path.resolve()
    assert settings.data_dir == tmp_path.resolve() / "data"
    assert settings.database_path == tmp_path.resolve() / "data" / "app.db"
    assert settings.log_dir == tmp_path.resolve() / "data" / "logs"
    assert settings.archive_root == tmp_path.resolve() / "data" / "archive"


def test_ensure_directories_creates_runtime_directories(tmp_path: Path) -> None:
    settings = AppSettings.from_project_root(tmp_path)

    settings.ensure_directories()

    assert settings.data_dir.is_dir()
    assert settings.log_dir.is_dir()
    assert not settings.archive_root.exists()
