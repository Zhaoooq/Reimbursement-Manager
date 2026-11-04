"""Filesystem helpers shared by the updater and the deployment tooling."""

from __future__ import annotations

import shutil
import time
from pathlib import Path


DEFAULT_REMOVE_ATTEMPTS = 5
DEFAULT_REMOVE_DELAY_SECONDS = 0.3


def remove_directory(
    directory: Path,
    *,
    attempts: int = DEFAULT_REMOVE_ATTEMPTS,
    delay: float = DEFAULT_REMOVE_DELAY_SECONDS,
) -> bool:
    """Remove ``directory`` recursively, retrying while handles are released.

    A freshly written build directory is routinely held for a moment by the
    antivirus scanner or by the tail of a just-exited process, and
    ``shutil.rmtree`` aborts on the first locked file.  Swallowing that with
    ``ignore_errors=True`` hides a real failure and leaks a full copy of the
    application, so this retries and then reports honestly.

    Returns ``True`` when the directory is gone, ``False`` when the caller has
    to deal with the leftover.
    """
    if not directory.exists():
        return True

    for attempt in range(attempts):
        try:
            shutil.rmtree(directory)
            return True
        except OSError:
            if attempt == attempts - 1:
                return False
            time.sleep(delay * (attempt + 1))
    return False
