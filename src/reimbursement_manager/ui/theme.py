"""Shared visual theme for the desktop UI."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib.resources import files

from PySide6.QtCore import QLibraryInfo, QTranslator
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

_TRANSLATOR: QTranslator | None = None


@dataclass(frozen=True)
class ThemeTokens:
    """Small, shared visual vocabulary for the single supported light theme.

    Three layers, deliberately flat:

    * colour — one value per meaning, never a shade invented at the call site.
    * metrics — the only spacing / size numbers UI code may use.
    * type    — six sizes, no intermediate steps.
    """

    # Colour: surfaces
    app_background: str = "#F5F5F7"
    surface: str = "#FFFFFF"
    secondary_surface: str = "#F2F2F7"
    hover_surface: str = "#EAF3FF"
    selected_surface: str = "#E5F1FF"

    # Colour: text
    primary_text: str = "#1D1D1F"
    secondary_text: str = "#6E6E73"
    tertiary_text: str = "#8E8E93"

    # Colour: borders
    border: str = "#D2D2D7"
    separator: str = "#E5E5EA"
    selected_border: str = "#B9DAFF"

    # Colour: accent
    accent: str = "#007AFF"
    accent_hover: str = "#0066D6"
    accent_pressed: str = "#0056B3"
    accent_disabled: str = "#A8CFFF"
    info_surface: str = "#E8F1FF"
    info_border: str = "#C9E2FF"

    # Colour: success
    success: str = "#34C759"
    success_surface: str = "#E9F9EE"
    success_border: str = "#A9E6B8"
    success_text: str = "#248A3D"

    # Colour: warning
    warning: str = "#FF9F0A"
    warning: str = "#FF9F0A"
    warning_surface: str = "#FFF5E6"
    warning_surface_soft: str = "#FFF7E8"
    warning_border: str = "#FFD49A"
    warning_border_soft: str = "#FFE0AD"
    warning_text: str = "#9A5B00"

    # Colour: danger
    danger: str = "#FF3B30"
    danger_text: str = "#B3261E"
    danger_surface: str = "#FFF0EF"
    danger_hover_surface: str = "#FFE4E2"
    danger_pressed_surface: str = "#FFD4D0"
    danger_border: str = "#FFB7B1"
    danger_zone_surface: str = "#FFFAFA"
    danger_zone_border: str = "#F0D9D6"

    # Colour: scrollbar
    scroll_handle: str = "#C7C7CC"
    scroll_handle_hover: str = "#AEAEB2"

    # Metrics: spacing scale — the only spacing values UI code may use.
    space_1: int = 4
    space_2: int = 8
    space_3: int = 12
    space_4: int = 16
    space_5: int = 20
    space_6: int = 24
    space_8: int = 32

    # Metrics: component sizing
    control_height: int = 34
    table_header_height: int = 34
    table_row_height: int = 52
    nav_item_height: int = 38
    sidebar_width: int = 210
    icon_size: int = 18
    thumbnail_width: int = 160
    thumbnail_height: int = 104

    # Typography: family and the six allowed sizes.
    font_family: str = '"Microsoft YaHei UI", "Segoe UI"'
    badge_size: int = 12
    secondary_size: int = 13
    body_size: int = 14
    section_title_size: int = 17
    page_title_size: int = 24
    metric_size: int = 28

    # Shape
    radius_bar: int = 4
    badge_radius: int = 8
    control_radius: int = 10
    radius_nested: int = 12
    card_radius: int = 14


IOS_LIGHT_TOKENS = ThemeTokens()


def load_stylesheet(tokens: ThemeTokens = IOS_LIGHT_TOKENS) -> str:
    """Return the tokenized QSS without relying on the working directory."""
    stylesheet = files("reimbursement_manager.ui.styles").joinpath("base.qss").read_text(
        encoding="utf-8"
    )
    for name, value in asdict(tokens).items():
        stylesheet = stylesheet.replace(f"@{name.upper()}@", str(value))
    return stylesheet


def apply_light_theme(application: QApplication) -> None:
    """Apply the single supported application-wide theme."""
    _install_chinese_translations(application)
    application.setFont(QFont("Microsoft YaHei UI", 9))
    application.setStyleSheet(load_stylesheet())


def _install_chinese_translations(application: QApplication) -> None:
    """Localize Qt's own dialog buttons (Yes/No/OK/Cancel) to Chinese.

    Without this the app shows English standard buttons inside an otherwise
    Chinese interface.  Missing translation files are not fatal: the UI simply
    falls back to Qt's built-in English strings.
    """
    global _TRANSLATOR
    if _TRANSLATOR is not None:
        return
    translator = QTranslator(application)
    translations_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load("qtbase_zh_CN", translations_path):
        application.installTranslator(translator)
        _TRANSLATOR = translator
