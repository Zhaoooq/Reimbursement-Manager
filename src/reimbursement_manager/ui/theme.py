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
    """Small, shared visual vocabulary for the single supported light theme."""

    app_background: str = "#F5F5F7"
    surface: str = "#FFFFFF"
    secondary_surface: str = "#F2F2F7"
    primary_text: str = "#1D1D1F"
    secondary_text: str = "#6E6E73"
    tertiary_text: str = "#8E8E93"
    accent: str = "#007AFF"
    success: str = "#34C759"
    warning: str = "#FF9F0A"
    danger: str = "#FF3B30"
    border: str = "#D2D2D7"
    separator: str = "#E5E5EA"
    hover_surface: str = "#EAF3FF"
    selected_surface: str = "#E5F1FF"
    selected_border: str = "#B9DAFF"
    accent_hover: str = "#0066D6"
    accent_pressed: str = "#0056B3"
    accent_disabled: str = "#A8CFFF"
    success_surface: str = "#E9F9EE"
    success_border: str = "#A9E6B8"
    success_text: str = "#248A3D"
    warning_surface: str = "#FFF5E6"
    warning_border: str = "#FFD49A"
    warning_text: str = "#9A5B00"
    danger_surface: str = "#FFF0EF"
    danger_border: str = "#FFB7B1"
    font_family: str = '"Microsoft YaHei UI", "Segoe UI"'
    body_size: int = 14
    secondary_size: int = 13
    page_title_size: int = 24
    section_title_size: int = 17
    card_radius: int = 14
    control_radius: int = 10
    badge_radius: int = 8


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
