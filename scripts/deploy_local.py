"""Build the app and deploy it to a stable local install directory.

The packaged runtime keeps user data in ``%LOCALAPPDATA%\\ReimbursementManager``
(see ``config/paths.py``), which is independent of the program directory.  That
separation makes an in-place program update safe: replacing the install folder
never touches the database, the log files, or the attachment archive.

Usage:
    python scripts/deploy_local.py                # build, then deploy
    python scripts/deploy_local.py --skip-build   # deploy the existing dist/
    python scripts/deploy_local.py --target D:\\Apps\\ReimbursementManager
"""

from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "build_windows.py"
SOURCE_DIRECTORY = PROJECT_ROOT / "dist" / "ReimbursementManager"
EXECUTABLE_NAME = "ReimbursementManager.exe"
SHORTCUT_NAME = "报销归档.lnk"

# Reuse the retrying directory removal that the in-app updater relies on; both
# paths fight the same transient Windows file locks.
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from reimbursement_manager.utils.filesystem import remove_directory

# Files whose absence means the build is incomplete or corrupted.
REQUIRED_ENTRIES = (
    EXECUTABLE_NAME,
    "_internal",
    "_internal/reimbursement_manager/ui/styles/base.qss",
    "_internal/reimbursement_manager/database/migrations/env.py",
)


class DeployError(RuntimeError):
    """Raised when a local deployment cannot be completed safely."""


def default_target() -> Path:
    """Return the per-user install directory used by default."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise DeployError(
            "LOCALAPPDATA 不可用，请用 --target 显式指定安装目录。"
        )
    return Path(local_app_data) / "Programs" / "ReimbursementManager"


def read_version() -> str:
    """Read the canonical version without importing the package."""
    version_file = PROJECT_ROOT / "src" / "reimbursement_manager" / "version.py"
    for line in version_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            return line.split("=", maxsplit=1)[1].strip().strip("\"'")
    return "unknown"


def run_build() -> None:
    """Run the existing PyInstaller build script."""
    if not BUILD_SCRIPT.is_file():
        raise DeployError(f"找不到构建脚本：{BUILD_SCRIPT}")
    print("[1/4] 正在构建应用（PyInstaller）...")
    subprocess.run(
        [sys.executable, str(BUILD_SCRIPT)],
        cwd=PROJECT_ROOT,
        check=True,
    )


def verify_directory(directory: Path, *, label: str) -> None:
    """Fail fast when a build or deployment is missing required files."""
    missing = [
        relative
        for relative in REQUIRED_ENTRIES
        if not (directory / relative).exists()
    ]
    if missing:
        raise DeployError(
            f"{label} 不完整，缺少：{', '.join(missing)}"
        )


def _remove_tree(path: Path) -> bool:
    """Remove a directory and report honestly when it is still locked."""
    if remove_directory(path):
        return True
    print(f"      警告：暂时无法清理 {path}，可手动删除。")
    return False


def _sweep_stale_siblings(target: Path) -> None:
    """Drop leftover staging/backup directories from an interrupted earlier run."""
    for pattern in (f".{target.name}.staging-*", f".{target.name}.backup-*"):
        for path in target.parent.glob(pattern):
            _remove_tree(path)


def deploy(source: Path, target: Path) -> None:
    """Replace ``target`` with ``source`` using a staging directory + rollback."""
    verify_directory(source, label="构建产物")

    target.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    staging = target.parent / f".{target.name}.staging-{os.getpid()}"
    backup = target.parent / f".{target.name}.backup-{stamp}"

    _sweep_stale_siblings(target)

    print(f"[3/4] 正在复制程序文件到 {target}")
    shutil.copytree(source, staging)
    verify_directory(staging, label="待发布目录")

    moved_existing = False
    try:
        if target.exists():
            try:
                target.rename(backup)
            except PermissionError as error:
                raise DeployError(
                    "目标目录被占用，请先关闭正在运行的“报销归档”，然后重新运行本脚本。"
                ) from error
            moved_existing = True
        staging.rename(target)
    except Exception:
        # Restore the previous installation if the swap did not complete.
        if moved_existing and backup.exists() and not target.exists():
            backup.rename(target)
        raise
    finally:
        _remove_tree(staging)

    if moved_existing:
        _remove_tree(backup)


def create_shortcut(target: Path) -> Path | None:
    """Create or overwrite the desktop shortcut that points at ``target``."""
    executable = target / EXECUTABLE_NAME
    script = f"""
$ErrorActionPreference = 'Stop'
# The Chinese desktop name must survive the pipe back to Python as UTF-8.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop '{SHORTCUT_NAME}'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = '{executable}'
$shortcut.WorkingDirectory = '{target}'
$shortcut.IconLocation = '{executable},0'
$shortcut.Description = '报销归档'
$shortcut.Save()
Write-Output $shortcutPath
"""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"      快捷方式创建失败（不影响使用）：{error}")
        return None

    output = result.stdout.strip().splitlines()
    if output:
        candidate = Path(output[-1])
        if candidate.is_file():
            return candidate

    # The COM call may have succeeded while the echoed path came back mangled;
    # fall back to the conventional location before reporting a failure.
    profile = os.environ.get("USERPROFILE")
    if profile:
        fallback = Path(profile) / "Desktop" / SHORTCUT_NAME
        if fallback.is_file():
            return fallback
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="构建并把最新版本部署到本机安装目录。"
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=None,
        help="安装目录；默认 %%LOCALAPPDATA%%\\Programs\\ReimbursementManager",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="跳过 PyInstaller，直接部署已有的 dist/ReimbursementManager",
    )
    parser.add_argument(
        "--no-shortcut",
        action="store_true",
        help="不创建桌面快捷方式",
    )
    args = parser.parse_args(argv)

    target = (args.target or default_target()).expanduser().resolve()
    version = read_version()

    try:
        if args.skip_build:
            print("[1/4] 跳过构建，使用现有 dist/ 产物")
            verify_directory(SOURCE_DIRECTORY, label="dist 构建产物")
        else:
            run_build()
            verify_directory(SOURCE_DIRECTORY, label="构建产物")

        print(f"[2/4] 版本 {version}，目标目录 {target}")
        deploy(SOURCE_DIRECTORY, target)

        shortcut = None
        if not args.no_shortcut:
            print("[4/4] 正在更新桌面快捷方式")
            shortcut = create_shortcut(target)
    except subprocess.CalledProcessError as error:
        print(f"\n构建失败（退出码 {error.returncode}），未改动现有安装。")
        return 1
    except DeployError as error:
        print(f"\n部署失败：{error}")
        return 1

    print()
    print(f"已更新到版本 {version}")
    print(f"程序目录：{target}")
    if shortcut is not None:
        print(f"桌面快捷方式：{shortcut}")
    print("用户数据：%LOCALAPPDATA%\\ReimbursementManager（未改动）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
