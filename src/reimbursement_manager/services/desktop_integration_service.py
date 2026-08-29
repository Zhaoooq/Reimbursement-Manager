from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path


class DesktopIntegrationError(OSError):
    """Raised when the operating system cannot open a desktop target."""


class DesktopIntegrationService:
    """Open local files and folders through the Windows shell."""

    def __init__(
        self, *, startfile: Callable[[str], None] | None = None
    ) -> None:
        self._startfile = startfile or getattr(os, "startfile", None)

    def open_file(self, path: Path) -> None:
        target = Path(path)
        if not target.is_file():
            raise FileNotFoundError(target)
        self._open(target)

    def open_folder(self, path: Path) -> None:
        target = Path(path)
        if not target.is_dir():
            raise FileNotFoundError(target)
        self._open(target)

    def _open(self, target: Path) -> None:
        if self._startfile is None:
            raise DesktopIntegrationError("Windows shell integration is unavailable.")
        try:
            self._startfile(str(target))
        except OSError as error:
            raise DesktopIntegrationError(f"Unable to open {target}.") from error
