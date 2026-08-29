"""Shared visual theme for the desktop UI."""

from __future__ import annotations

from importlib.resources import files

from PySide6.QtWidgets import QApplication


def load_stylesheet() -> str:
    """Return the bundled light-theme QSS without relying on a working directory."""
    return files("reimbursement_manager.ui.styles").joinpath("base.qss").read_text(
        encoding="utf-8"
    )


def apply_light_theme(application: QApplication) -> None:
    """Apply the single supported application-wide theme."""
    application.setStyleSheet(load_stylesheet())
