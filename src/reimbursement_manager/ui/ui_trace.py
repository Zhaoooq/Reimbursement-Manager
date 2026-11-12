"""UI 诊断：把提示气泡与顶层窗口事件写进日志，用于定位"小框"来源。

只在环境变量 ``RM_UI_TRACE=1`` 时启用，正常运行完全不加载。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)

TRACE_ENV_VAR = "RM_UI_TRACE"


TRACE_FLAG_FILE = "ui-trace.flag"


def trace_enabled() -> bool:
    """环境变量、exe 同目录、或启动目录存在标记文件时开启。

    三种方式都认，避免"双击位置不同导致开关失效"。
    """
    if os.environ.get(TRACE_ENV_VAR) == "1":
        return True
    candidates = [Path.cwd()]
    executable = Path(sys.executable).resolve().parent
    if executable not in candidates:
        candidates.append(executable)
    return any((folder / TRACE_FLAG_FILE).is_file() for folder in candidates)


def trace_log_path() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    base = Path(root) / "ReimbursementManager" / "logs" if root else Path.cwd() / "logs"
    base.mkdir(parents=True, exist_ok=True)
    return base / "ui-trace.log"


class _UiTrace(QObject):
    """记录 tooltip 是谁弹的、以及何时出现新的顶层窗口。"""

    def __init__(self, application: QApplication) -> None:
        super().__init__(application)
        self._path = trace_log_path()
        self._write("=== 开始记录 ===")

    def _write(self, message: str) -> None:
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")

    @staticmethod
    def _describe(widget: QWidget | None) -> str:
        if widget is None:
            return "<None>"
        name = widget.objectName() or "-"
        text = ""
        if hasattr(widget, "text"):
            try:
                text = str(widget.text())[:40]
            except Exception:  # pragma: no cover - 仅诊断用
                text = ""
        return f"{type(widget).__name__}({name}) {text!r}"

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        kind = event.type()
        if kind == QEvent.Type.ToolTip:
            cursor = QCursor.pos()
            hovered = QApplication.widgetAt(cursor)
            tip = ""
            if hasattr(event, "tip"):
                tip = str(event.tip())[:60]
            self._write(
                f"TOOLTIP {self._describe(hovered)} tip={tip!r} "
                f"cursor=({cursor.x()},{cursor.y()}) target={watched.objectName() or type(watched).__name__}"
            )
        elif kind == QEvent.Type.Show and isinstance(watched, QWidget):
            if watched.isWindow() and watched.parentWidget() is None:
                self._write(
                    f"WINDOW-SHOW {type(watched).__name__} "
                    f"name={watched.objectName() or '-'} title={watched.windowTitle()!r}"
                )
        return False


_TRACE: _UiTrace | None = None


def install_trace(application: QApplication) -> None:
    """按需安装全局事件过滤器。"""
    global _TRACE
    if not trace_enabled() or _TRACE is not None:
        return
    _TRACE = _UiTrace(application)
    application.installEventFilter(_TRACE)
    logger.info("UI trace enabled, writing to %s", trace_log_path())


__all__ = [
    "install_trace",
    "trace_enabled",
    "trace_log_path",
    "TRACE_ENV_VAR",
    "TRACE_FLAG_FILE",
]
