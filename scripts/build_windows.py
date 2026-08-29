"""Create the Task 8 Windows onedir PyInstaller build."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_DIRECTORY = PROJECT_ROOT / "build"
DIST_DIRECTORY = PROJECT_ROOT / "dist"
SPEC_FILE = PROJECT_ROOT / "ReimbursementManager.spec"
EXECUTABLE_PATH = DIST_DIRECTORY / "ReimbursementManager" / "ReimbursementManager.exe"


def _clean_artifact_directory(directory: Path) -> None:
    """Remove a generated PyInstaller directory, allowing for Windows scans."""
    for attempt in range(10):
        try:
            shutil.rmtree(directory)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(1)


def main() -> int:
    """Clean artifacts, build the root spec, and verify the onedir executable."""
    if not SPEC_FILE.is_file():
        raise FileNotFoundError(f"PyInstaller spec was not found: {SPEC_FILE}")

    for artifact_directory in (BUILD_DIRECTORY, DIST_DIRECTORY):
        if artifact_directory.exists():
            _clean_artifact_directory(artifact_directory)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(SPEC_FILE),
    ]
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)

    if not EXECUTABLE_PATH.is_file():
        raise RuntimeError(f"PyInstaller build did not create: {EXECUTABLE_PATH}")

    print(f"Build completed: {EXECUTABLE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
