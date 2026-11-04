"""Apply a downloaded update to the running portable installation.

Windows keeps a running executable locked, so an application cannot replace its
own program directory.  The update therefore runs in two processes:

1. the running application unpacks the new build into a staging directory and
   launches *that* build with ``--apply-update``;
2. the new build waits for the old process to exit, swaps the program directory
   (staging + backup + rollback), records the outcome and starts itself again.

Because the updater runs from the staging directory, and nothing is running from
the installation directory once the old process exits, the swap can be a plain
directory rename — the same approach ``scripts/deploy_local.py`` uses.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import argparse
import ctypes
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from reimbursement_manager.config.paths import (
    AppPaths,
    LocalAppDataUnavailableError,
)
from reimbursement_manager.utils.filesystem import remove_directory
from reimbursement_manager.utils.logging import configure_logging


logger = logging.getLogger(__name__)

UPDATE_FLAG = "--apply-update"
EXECUTABLE_NAME = "ReimbursementManager.exe"
REQUIRED_ENTRIES = (EXECUTABLE_NAME, "_internal")
DEFAULT_WAIT_TIMEOUT_SECONDS = 180.0
UPDATE_RESULT_FILE_NAME = "update-result.json"

_PROCESS_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0x00000000


class UpdateApplyError(RuntimeError):
    """Raised when a staged update cannot be installed safely."""


@dataclass(frozen=True, slots=True)
class UpdateResult:
    """Outcome recorded by the updater for the restarted application."""

    success: bool
    version: str
    message: str
    timestamp: float


def is_update_invocation(arguments: Sequence[str]) -> bool:
    """Return whether these command-line arguments ask to install an update."""
    return UPDATE_FLAG in arguments


def current_install_directory() -> Path:
    """Return the program directory of the executable being served."""
    return Path(sys.executable).resolve().parent


def wait_for_process(pid: int, timeout: float = DEFAULT_WAIT_TIMEOUT_SECONDS) -> bool:
    """Block until ``pid`` exits; return ``False`` only on timeout."""
    if pid <= 0:
        return True
    if os.name != "nt":
        return _wait_by_polling(pid, timeout)

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(_PROCESS_SYNCHRONIZE, False, pid)
    if not handle:
        # The process is already gone.
        return True
    try:
        result = kernel32.WaitForSingleObject(handle, int(timeout * 1000))
    finally:
        kernel32.CloseHandle(handle)
    return result == _WAIT_OBJECT_0


def _wait_by_polling(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        time.sleep(0.2)
    return False


def _require_program_directory(directory: Path) -> None:
    missing = [entry for entry in REQUIRED_ENTRIES if not (directory / entry).exists()]
    if missing:
        raise UpdateApplyError(
            f"{directory} 不是完整程序目录，缺少：{', '.join(missing)}"
        )


def replace_installation(source: Path, target: Path) -> None:
    """Replace ``target`` with ``source``, restoring the old build on failure."""
    _require_program_directory(source)
    target.parent.mkdir(parents=True, exist_ok=True)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    staging = target.parent / f".{target.name}.staging-{os.getpid()}"
    backup = target.parent / f".{target.name}.backup-{stamp}"

    if not remove_directory(staging):
        raise UpdateApplyError(f"无法清理临时目录：{staging}")

    print(f"        正在准备新版本：{staging}")
    shutil.copytree(source, staging)
    _require_program_directory(staging)

    moved_existing = False
    try:
        if target.exists():
            try:
                target.rename(backup)
            except PermissionError as error:
                raise UpdateApplyError(
                    "安装目录仍被占用，更新已取消。请关闭程序后重试。"
                ) from error
            moved_existing = True
        staging.rename(target)
    except Exception:
        if moved_existing and backup.exists() and not target.exists():
            backup.rename(target)
        raise
    finally:
        remove_directory(staging)

    if moved_existing and not remove_directory(backup):
        logger.warning("Previous installation left behind at %s", backup)


def launch_application(target: Path) -> None:
    """Start the freshly installed executable."""
    executable = target / EXECUTABLE_NAME
    if not executable.is_file():
        raise UpdateApplyError("更新后没有找到主程序。")
    try:
        subprocess.Popen(  # noqa: S603 - fixed, verified path
            [str(executable)],
            cwd=str(target),
            close_fds=True,
        )
    except OSError as error:
        raise UpdateApplyError(f"无法启动更新后的程序：{error}") from error


def cleanup_update_workspace(updates_directory: Path) -> None:
    """Remove archives and staged builds left behind by a finished update.

    The updater itself runs from the staging directory, so it cannot delete its
    own files.  The application that the update just restarted does it instead;
    anything still locked is retried on the next launch.
    """
    if not updates_directory.is_dir():
        return
    for entry in updates_directory.iterdir():
        if entry.is_dir():
            if not remove_directory(entry):
                logger.warning("Could not remove the staged build at %s", entry)
            continue
        try:
            entry.unlink()
        except OSError as error:
            logger.warning("Could not remove %s: %s", entry, error)


def _result_path() -> Path | None:
    try:
        return AppPaths.for_packaged().config_dir / UPDATE_RESULT_FILE_NAME
    except LocalAppDataUnavailableError:
        return None


def write_result(result: UpdateResult) -> None:
    """Record the outcome so the restarted application can report it once."""
    path = _result_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "success": result.success,
                    "version": result.version,
                    "message": result.message,
                    "timestamp": result.timestamp,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError as error:
        logger.warning("Could not record the update result: %s", error)


def consume_update_result() -> UpdateResult | None:
    """Read and clear the recorded outcome, if the updater left one."""
    path = _result_path()
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        logger.warning("Could not read the update result: %s", error)
        path.unlink(missing_ok=True)
        return None
    finally:
        path.unlink(missing_ok=True)

    if not isinstance(payload, dict):
        return None
    return UpdateResult(
        success=bool(payload.get("success")),
        version=str(payload.get("version") or ""),
        message=str(payload.get("message") or ""),
        timestamp=float(payload.get("timestamp") or 0.0),
    )


def apply_update(
    *,
    source: Path,
    target: Path,
    wait_pid: int = 0,
    version: str = "",
    wait_timeout: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    """Install the staged build in ``source`` over ``target`` and restart it."""
    _require_program_directory(source)

    if not wait_for_process(wait_pid, wait_timeout):
        raise UpdateApplyError("旧版本进程没有按时退出，更新已取消。")

    replace_installation(source, target)
    write_result(
        UpdateResult(
            success=True,
            version=version,
            message="更新完成。",
            timestamp=time.time(),
        )
    )
    launch_application(target)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"{EXECUTABLE_NAME} {UPDATE_FLAG}",
        description="安装已下载的更新并重新启动。",
    )
    parser.add_argument(UPDATE_FLAG, action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--from", dest="source", type=Path, required=True)
    parser.add_argument("--to", dest="target", type=Path, required=True)
    parser.add_argument("--wait-pid", type=int, default=0)
    parser.add_argument("--version", default="")
    return parser


def run_from_command_line(arguments: Sequence[str]) -> int:
    """Install an update from command-line arguments; called before Qt starts."""
    options = build_argument_parser().parse_args(list(arguments))

    try:
        configure_logging(AppPaths.for_packaged().logs_dir)
    except LocalAppDataUnavailableError:
        logger.warning("LOCALAPPDATA is unavailable; continuing without a log file")

    source = options.source.expanduser().resolve()
    target = options.target.expanduser().resolve()
    logger.info("Applying update from %s to %s", source, target)

    try:
        apply_update(
            source=source,
            target=target,
            wait_pid=options.wait_pid,
            version=options.version,
        )
    except UpdateApplyError as error:
        logger.exception("Update failed")
        write_result(
            UpdateResult(
                success=False,
                version=options.version,
                message=str(error),
                timestamp=time.time(),
            )
        )
        # Bring the previous version back up so the user is not left with nothing.
        try:
            launch_application(target)
        except UpdateApplyError:
            logger.exception("Could not restart the previous version")
        return 1

    logger.info("Update to %s finished", options.version)
    return 0
