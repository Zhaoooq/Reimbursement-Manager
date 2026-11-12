"""R2 导航图标：资源存在、颜色与令牌一致、选中态联动、打包可见。"""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import pytest

from reimbursement_manager.ui.icons import (
    NAVIGATION_ICON_NAMES,
    icon_path,
    navigation_icon,
)
from reimbursement_manager.ui.theme import IOS_LIGHT_TOKENS
from reimbursement_manager.ui.windows import MainWindow
from reimbursement_manager.ui.windows.main_window import PAGE_TITLES

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_HEX_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}")


def _painted_pixels(icon, size: int = 18) -> int:
    """Count visible pixels of a rendered icon; 0 means it drew nothing."""
    image = icon.pixmap(size, size).toImage()
    return sum(
        1
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 0
    )


def test_every_navigation_icon_is_a_bundled_svg_file() -> None:
    for name in NAVIGATION_ICON_NAMES:
        for active in (False, True):
            path = icon_path(name, active=active)
            assert path.is_file()
            assert path.suffix == ".svg"
            assert "<svg" in path.read_text(encoding="utf-8")


def test_navigation_icons_only_use_theme_colours() -> None:
    """The two hex values in the SVGs must stay equal to the design tokens."""
    for name in NAVIGATION_ICON_NAMES:
        normal = icon_path(name).read_text(encoding="utf-8")
        active = icon_path(name, active=True).read_text(encoding="utf-8")

        assert set(_HEX_COLOUR.findall(normal)) == {IOS_LIGHT_TOKENS.secondary_text}
        assert set(_HEX_COLOUR.findall(active)) == {IOS_LIGHT_TOKENS.accent}


def test_navigation_icons_render_visible_glyphs() -> None:
    QApplication.instance() or QApplication([])
    for name in NAVIGATION_ICON_NAMES:
        assert _painted_pixels(navigation_icon(name)) > 20, name
        assert _painted_pixels(navigation_icon(name, active=True)) > 20, name


def test_sidebar_swaps_to_the_accent_icon_for_the_selected_row() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert window.navigation.count() == len(PAGE_TITLES)
        for row in range(window.navigation.count()):
            assert window.navigation.item(row).icon().isNull() is False

        def printed(row: int):
            return window.navigation.item(row).icon().pixmap(18, 18).toImage()

        assert printed(0) == navigation_icon("home", active=True).pixmap(18, 18).toImage()
        assert printed(1) == navigation_icon("batches").pixmap(18, 18).toImage()

        window.navigation.setCurrentRow(1)
        application.processEvents()

        assert printed(1) == navigation_icon(
            "batches", active=True
        ).pixmap(18, 18).toImage()
        assert printed(0) == navigation_icon("home").pixmap(18, 18).toImage()
    finally:
        window.close()


def test_pyinstaller_spec_bundles_the_icon_directory() -> None:
    """The frozen build must ship the icons at the path icons.py resolves."""
    spec = (PROJECT_ROOT / "ReimbursementManager.spec").read_text(encoding="utf-8")
    assert '"reimbursement_manager/ui/resources"' in spec
    assert (
        PROJECT_ROOT / "src" / "reimbursement_manager" / "ui" / "resources" / "icons"
    ).is_dir()


def test_missing_icon_file_degrades_to_text_only_navigation(monkeypatch) -> None:
    """A broken install must keep the sidebar usable instead of crashing."""
    QApplication.instance() or QApplication([])

    def missing(name: str, *, active: bool = False) -> Path:
        raise FileNotFoundError(name)

    monkeypatch.setattr("reimbursement_manager.ui.icons.icon_path", missing)

    assert navigation_icon("home").isNull() is True


def test_frozen_icon_path_targets_the_pyinstaller_layout(
    tmp_path: Path, monkeypatch
) -> None:
    """Frozen builds resolve icons under sys._MEIPASS, like the bundled QSS."""
    import shutil
    import sys as _sys

    bundle = tmp_path / "bundle"
    icon_dir = bundle / "reimbursement_manager" / "ui" / "resources" / "icons"
    icon_dir.mkdir(parents=True)
    shutil.copy(icon_path("home"), icon_dir / "nav-home.svg")

    monkeypatch.setattr(_sys, "_MEIPASS", str(bundle), raising=False)

    assert icon_path("home", frozen=True) == icon_dir / "nav-home.svg"
    assert icon_path("home", active=False) == icon_path("home")


def test_frozen_runtime_without_bundle_degrades_instead_of_raising(monkeypatch) -> None:
    import sys as _sys

    QApplication.instance() or QApplication([])

    def frozen_only(*, frozen: bool | None = None) -> bool:
        return True

    monkeypatch.setattr(
        "reimbursement_manager.ui.icons.is_packaged_runtime", frozen_only
    )
    monkeypatch.delattr(_sys, "_MEIPASS", raising=False)

    with pytest.raises(RuntimeError):
        icon_path("home")
    assert navigation_icon("home").isNull() is True
