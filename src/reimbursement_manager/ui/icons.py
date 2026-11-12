"""Bundled line icons for the sidebar navigation.

The icons are plain SVG files shipped as package data:

* inside the checkout they live in ``ui/resources/icons``;
* in a PyInstaller build the spec copies that folder to
  ``reimbursement_manager/ui/resources`` below ``sys._MEIPASS``.

Paths therefore go through the same resolution rule as ``base.qss`` and the
Alembic scripts, so the frozen layout stays aligned with
:mod:`reimbursement_manager.config.runtime_resources`.

Each icon has two colour variants — muted (``secondary_text``) and accent
(``accent``) — because a QListWidget item keeps one icon and Qt's SVG icon
engine cannot recolour it from QSS. ``tests/ui/test_r2_navigation_icons.py``
keeps the two hex values in sync with :class:`~reimbursement_manager.ui.theme.ThemeTokens`.
"""

from __future__ import annotations

import logging
import sys
from importlib.resources import files
from pathlib import Path

from PySide6.QtGui import QIcon

from reimbursement_manager.config.paths import is_packaged_runtime

NAVIGATION_ICON_NAMES: tuple[str, ...] = (
    "home",
    "batches",
    "items",
    "pending",
    "templates",
    "settings",
)

logger = logging.getLogger(__name__)


def icon_directory(*, frozen: bool | None = None) -> Path:
    """Return the directory that holds the bundled navigation icons."""
    if is_packaged_runtime(frozen=frozen):
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root is None:
            raise RuntimeError("Frozen application resources are unavailable.")
        return Path(bundle_root) / "reimbursement_manager" / "ui" / "resources" / "icons"
    return Path(str(files("reimbursement_manager.ui"))) / "resources" / "icons"


def icon_path(name: str, *, active: bool = False, frozen: bool | None = None) -> Path:
    """Return the readable path of one bundled navigation icon."""
    filename = f"nav-{name}-active.svg" if active else f"nav-{name}.svg"
    path = icon_directory(frozen=frozen) / filename
    if not path.is_file():
        raise FileNotFoundError(f"缺少导航图标资源：{filename}")
    return path


def navigation_icon(name: str, *, active: bool = False) -> QIcon:
    """Load one navigation icon, degrading to text-only navigation on failure."""
    try:
        return QIcon(str(icon_path(name, active=active)))
    except (FileNotFoundError, OSError, RuntimeError):
        logger.exception("Failed to load navigation icon %s", name)
        return QIcon()
