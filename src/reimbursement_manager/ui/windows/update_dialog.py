"""Settings-page block that checks for, downloads, and applies an update.

The widget owns the whole lifecycle so ``main_window`` only has to drop it into
the settings page.  Network and disk work runs in ``QThread`` workers because the
rest of the application is synchronous and a 54 MB download must not freeze the
window.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import subprocess

from PySide6.QtCore import QThread, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from reimbursement_manager.services.update_service import (
    EXECUTABLE_NAME,
    UpdateError,
    UpdateInfo,
    UpdateService,
)
from reimbursement_manager.updater import UPDATE_FLAG


logger = logging.getLogger(__name__)

STARTUP_CHECK_DELAY_MS = 2500


@dataclass(frozen=True, slots=True)
class UpdateContext:
    """Everything the settings page needs to update this installation."""

    service: UpdateService
    current_version: str
    install_directory: Path
    updates_directory: Path


class UpdateCheckWorker(QThread):
    """Ask the release feed whether a newer build exists."""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        service: UpdateService,
        current_version: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._current_version = current_version

    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            info = self._service.check_for_update(self._current_version)
        except UpdateError as error:
            logger.warning("Update check failed: %s", error)
            self.failed.emit(str(error))
            return
        self.succeeded.emit(info)


class UpdateDownloadWorker(QThread):
    """Download and unpack the new build, reporting byte progress."""

    progress = Signal(int, int)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        service: UpdateService,
        info: UpdateInfo,
        updates_directory: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._info = info
        self._updates_directory = updates_directory

    def run(self) -> None:  # noqa: D102 - QThread entry point
        staging = self._updates_directory / f"staging-{self._info.version}"
        try:
            archive = self._service.download(
                self._info,
                self._updates_directory / self._info.asset_name,
                progress=self.progress.emit,
            )
            program_directory = self._service.extract(archive, staging)
        except UpdateError as error:
            logger.warning("Update download failed: %s", error)
            self.failed.emit(str(error))
            return
        self.succeeded.emit(program_directory)


class UpdateDialog(QDialog):
    """Offer one available version and download it on request."""

    def __init__(
        self,
        info: UpdateInfo,
        service: UpdateService,
        updates_directory: Path,
        *,
        current_version: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._info = info
        self._service = service
        self._updates_directory = updates_directory
        self._current_version = current_version
        self._worker: UpdateDownloadWorker | None = None
        self.program_directory: Path | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        self.setObjectName("standardDialog")
        self.setWindowTitle("发现新版本")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(16)

        title = QLabel(f"新版本 v{self._info.version}")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            f"当前版本 {self._current_version} · 更新包约 {self._info.size_megabytes:.1f} MB"
        )
        subtitle.setObjectName("dialogHint")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.notes_view = QTextBrowser()
        self.notes_view.setObjectName("updateNotes")
        self.notes_view.setOpenExternalLinks(True)
        self.notes_view.setMinimumHeight(180)
        self.notes_view.setMarkdown(self._info.notes or "该版本没有提供更新说明。")
        layout.addWidget(self.notes_view)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("updateProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel()
        self.status_label.setObjectName("dialogHint")
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        layout.addWidget(self.status_label)

        self.buttons = QDialogButtonBox()
        self.later_button = self.buttons.addButton(
            "稍后", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.update_button = self.buttons.addButton(
            "立即更新", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.later_button.setObjectName("secondaryButton")
        self.update_button.setObjectName("primaryButton")
        self.buttons.rejected.connect(self.reject)
        self.update_button.clicked.connect(self._start_download)
        layout.addWidget(self.buttons)

    def _start_download(self) -> None:
        self.update_button.setEnabled(False)
        self.later_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.status_label.setText("正在下载更新包…")
        self.status_label.show()

        self._worker = UpdateDownloadWorker(
            self._service, self._info, self._updates_directory, self
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.succeeded.connect(self._on_downloaded)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, received: int, total: int) -> None:
        if total <= 0:
            self.progress_bar.setRange(0, 0)
            return
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(min(100, int(received * 100 / total)))

    def _on_downloaded(self, program_directory: object) -> None:
        self.program_directory = Path(str(program_directory))
        self.status_label.setText("准备完成，即将重启以安装新版本…")
        # Let the worker leave run() before the dialog is destroyed with it.
        if self._worker is not None:
            self._worker.wait(2000)
            self._worker = None
        self.accept()

    def _on_failed(self, message: str) -> None:
        self.progress_bar.hide()
        self.status_label.setText(f"更新失败：{message}")
        self.update_button.setEnabled(True)
        self.later_button.setEnabled(True)


class UpdateSection(QFrame):
    """The "应用更新" block shown on the settings page."""

    def __init__(self, context: UpdateContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._check_worker: UpdateCheckWorker | None = None
        self._download_dialog: UpdateDialog | None = None
        self._build_ui()
        QTimer.singleShot(STARTUP_CHECK_DELAY_MS, self._check_for_update)

    def _build_ui(self) -> None:
        self.setObjectName("settingsGroupSurface")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        title = QLabel("应用更新")
        title.setObjectName("settingsSectionTitle")
        layout.addWidget(title)

        description = QLabel("更新只替换程序文件，数据库与附件不受影响。")
        description.setObjectName("settingsSectionDescription")
        description.setWordWrap(True)
        layout.addWidget(description)

        self.check_button = QPushButton("检查更新")
        self.check_button.setObjectName("secondaryButton")
        self.check_button.clicked.connect(self._check_for_update)
        layout.addWidget(self.check_button, alignment=Qt.AlignmentFlag.AlignLeft)

        self.status_label = QLabel()
        self.status_label.setObjectName("settingsRowDetail")
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        layout.addWidget(self.status_label)

    def _set_status(self, message: str) -> None:
        self.status_label.setText(message)
        self.status_label.show()

    def _check_for_update(self) -> None:
        if self._check_worker is not None and self._check_worker.isRunning():
            return
        self.check_button.setEnabled(False)
        self._set_status("正在检查更新…")

        self._check_worker = UpdateCheckWorker(
            self._context.service, self._context.current_version, self
        )
        self._check_worker.succeeded.connect(self._on_checked)
        self._check_worker.failed.connect(self._on_check_failed)
        self._check_worker.finished.connect(
            lambda: self.check_button.setEnabled(True)
        )
        self._check_worker.start()

    def _on_checked(self, info: object) -> None:
        if info is None:
            self._set_status(f"已是最新版本（{self._context.current_version}）。")
            return

        update_info = info if isinstance(info, UpdateInfo) else None
        if update_info is None:
            self._set_status("更新信息异常，请稍后重试。")
            return

        self._set_status(f"发现新版本 v{update_info.version}。")
        self._show_dialog(update_info)

    def _on_check_failed(self, message: str) -> None:
        self._set_status(f"检查更新失败：{message}")

    def _show_dialog(self, info: UpdateInfo) -> None:
        dialog = UpdateDialog(
            info,
            self._context.service,
            self._context.updates_directory,
            current_version=self._context.current_version,
            parent=self,
        )
        self._download_dialog = dialog
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        program_directory = dialog.program_directory
        self._download_dialog = None
        if not accepted or program_directory is None:
            self._set_status(f"已取消更新到 v{info.version}。")
            return
        self._restart_for_update(program_directory, info.version)

    def _restart_for_update(self, program_directory: Path, version: str) -> None:
        executable = program_directory / EXECUTABLE_NAME
        if not executable.is_file():
            QMessageBox.warning(
                self, "无法完成更新", "更新包中没有找到主程序，请手动重新安装。"
            )
            return

        command = [
            str(executable),
            UPDATE_FLAG,
            "--from",
            str(program_directory),
            "--to",
            str(self._context.install_directory),
            "--wait-pid",
            str(os.getpid()),
            "--version",
            version,
        ]
        try:
            subprocess.Popen(  # noqa: S603 - fixed, verified path
                command, cwd=str(program_directory), close_fds=True
            )
        except OSError as error:
            logger.exception("Could not start the updater")
            QMessageBox.warning(
                self, "无法完成更新", f"启动更新程序失败：{error}"
            )
            return

        self._set_status("正在重启以安装新版本…")
        application = QApplication.instance()
        if application is not None:
            application.quit()
