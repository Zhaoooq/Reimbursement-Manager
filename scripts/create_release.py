"""Create a versioned Portable Windows release from an existing onedir build."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRECTORY = PROJECT_ROOT / "dist" / "ReimbursementManager"
RELEASE_DIRECTORY = PROJECT_ROOT / "release"
EXECUTABLE_NAME = "ReimbursementManager.exe"
PLATFORM_NAME = "win64"

# The release script is deliberately runnable as ``python scripts/create_release.py``
# without requiring an installed development package.
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from reimbursement_manager.version import __version__


def release_name(version: str = __version__) -> str:
    """Return the portable directory name for one application version."""
    return f"ReimbursementManager-{version}-{PLATFORM_NAME}"


def build_readme(version: str = __version__) -> str:
    """Return the UTF-8 user-facing release instructions."""
    return f"""报销归档 / ReimbursementManager
版本：{version}

这是 Portable（便携）版本。

如何启动
双击 ReimbursementManager.exe 即可启动。
不需要安装 Python、VS Code 或开发环境。

软件数据库
默认保存在：
%LOCALAPPDATA%\\ReimbursementManager\\data\\app.db

程序目录和用户数据库是分离的。删除 Portable 程序目录不会自动删除数据库。

报销附件
图片、PDF、合并支付截图等报销附件保存在软件中配置的归档目录，而不是程序目录。

备份与恢复
软件“设置”页面提供备份数据库和恢复数据库功能。
数据库备份不包含报销附件。若需完整备份，请同时备份：
1. 数据库备份文件
2. 实际报销附件归档目录

恢复数据库会替换当前数据库；系统会在恢复前自动备份当前数据库。恢复不会恢复图片、PDF 等附件文件。

自动更新
在“设置 → 应用更新”中检查新版本。
更新会下载完整程序包，并在重启后替换程序目录；数据库与报销附件不受影响。

Portable 说明
可以把整个 ReimbursementManager-{version}-{PLATFORM_NAME} 目录复制到其他位置。
但用户业务数据仍保存在 LocalAppData 和用户附件归档目录，因此复制程序目录不等于复制全部用户数据。
"""


def _assert_required_files(directory: Path) -> None:
    required_paths = (
        directory / EXECUTABLE_NAME,
        directory / "README.txt",
        directory
        / "_internal"
        / "reimbursement_manager"
        / "ui"
        / "styles"
        / "base.qss",
        directory
        / "_internal"
        / "reimbursement_manager"
        / "database"
        / "migrations"
        / "env.py",
    )
    missing = [str(path.relative_to(directory)) for path in required_paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"Release verification failed; required files are missing: {', '.join(missing)}")


def _assert_no_user_data(directory: Path) -> None:
    prohibited_suffixes = {".db", ".jpg", ".jpeg", ".png", ".pdf"}
    prohibited_directories = {".trash", "backups", "logs", "tests", "src", ".venv"}
    prohibited_files = {"pyproject.toml", "agents.md", "reimbursementmanager.spec"}
    prohibited = []
    for path in directory.rglob("*"):
        relative_path = path.relative_to(directory)
        if any(part.lower() in prohibited_directories for part in relative_path.parts):
            prohibited.append(relative_path)
        elif path.is_file() and (
            path.suffix.lower() in prohibited_suffixes
            or path.name.lower() in prohibited_files
        ):
            prohibited.append(relative_path)
    if prohibited:
        paths = ", ".join(str(path) for path in prohibited)
        raise RuntimeError(f"Release verification failed; prohibited content found: {paths}")


def _validate_release(directory: Path, version: str) -> None:
    _assert_required_files(directory)
    _assert_no_user_data(directory)
    readme = (directory / "README.txt").read_text(encoding="utf-8")
    if version not in readme:
        raise RuntimeError("Release verification failed; README version does not match the app version.")


def _restore_release_inheritance(directory: Path) -> None:
    """Make the staged release inherit the ACL of the release root on Windows."""
    try:
        subprocess.run(
            ["icacls", str(directory), "/reset", "/T", "/C"],
            check=True,
            capture_output=True,
            text=True,
            # icacls writes in the console code page, not in UTF-8.  Without an
            # explicit encoding the reader thread fails on Chinese output and the
            # failure is easy to miss.
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError(
            "Release ACL reset failed; the staged release was not published."
        ) from error


def _publish(directory: Path, destination: Path) -> None:
    """Rename the staged directory into place, retrying while handles clear.

    A freshly written 125 MB tree is briefly held by the antivirus scanner, and
    a single ``os.replace`` then fails with WinError 5 even though nothing is
    actually wrong.
    """
    for attempt in range(5):
        try:
            directory.replace(destination)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.5 * (attempt + 1))


def create_release() -> Path:
    """Copy the verified onedir build into a new versioned release directory."""
    source_executable = SOURCE_DIRECTORY / EXECUTABLE_NAME
    if not source_executable.is_file():
        raise FileNotFoundError(f"PyInstaller onedir executable was not found: {source_executable}")

    destination = RELEASE_DIRECTORY / release_name()
    if destination.exists():
        raise FileExistsError(
            f"Release directory already exists: {destination}. Delete it explicitly before creating a new release."
        )

    RELEASE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    temporary_directory = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.", dir=RELEASE_DIRECTORY)
    )
    try:
        shutil.copytree(SOURCE_DIRECTORY, temporary_directory, dirs_exist_ok=True)
        (temporary_directory / "README.txt").write_text(build_readme(), encoding="utf-8")
        _validate_release(temporary_directory, __version__)
        _restore_release_inheritance(temporary_directory)
        _publish(temporary_directory, destination)
    except Exception:
        shutil.rmtree(temporary_directory, ignore_errors=True)
        raise

    return destination


def main() -> int:
    """Create and report the final Portable release path."""
    destination = create_release()
    print(f"Release created: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
