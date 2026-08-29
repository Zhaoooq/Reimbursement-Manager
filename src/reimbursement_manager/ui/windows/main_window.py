from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QFormLayout,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QLineEdit,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import SQLAlchemyError

from reimbursement_manager.database.models import Attachment, Item
from reimbursement_manager.services.backup_service import BackupService
from reimbursement_manager.services.restore_service import (
    DatabaseReplacementError,
    InvalidBackupDatabaseError,
    RestoreService,
    RestoreServiceError,
    SafetyBackupError,
    UnknownSchemaRevisionError,
)
from reimbursement_manager.ui.theme import apply_light_theme

from reimbursement_manager.services import (
    AttachmentNotFoundError,
    AttachmentServiceError,
    AttachmentService,
    BatchExportResult,
    BatchSubmissionMaterialsIncompleteError,
    BatchListEntry,
    BatchService,
    CompletenessService,
    DashboardData,
    DashboardService,
    DesktopIntegrationError,
    DesktopIntegrationService,
    DuplicateAttachmentError,
    ExportService,
    ExportServiceError,
    ExportTargetExistsError,
    EmptyBatchExportError,
    IncompleteDashboardItem,
    ItemNotFoundError,
    ItemService,
    ItemServiceError,
    MaterialRequirementNotFoundError,
    PaymentScreenshotMergeError,
    PaymentScreenshotMergeService,
    PendingMaterialsService,
    SubmissionMaterialsIncompleteError,
    SubmissionReadinessService,
    TemplateService,
    TemplateServiceError,
)
from reimbursement_manager.services.payment_screenshot_merge_service import (
    PAYMENT_SCREENSHOT_CODE,
    is_merged_payment_screenshot,
)


PAGE_TITLES = (
    "首页",
    "报销批次",
    "所有物品",
    "待补材料",
    "模板管理",
    "设置",
)

BATCH_LIST_PAGE_INDEX = 1
ALL_ITEMS_PAGE_INDEX = 2
PENDING_MATERIALS_PAGE_INDEX = 3
TEMPLATE_MANAGEMENT_PAGE_INDEX = 4
BATCH_DETAIL_PAGE_INDEX = len(PAGE_TITLES)
ITEM_DETAIL_PAGE_INDEX = BATCH_DETAIL_PAGE_INDEX + 1

ITEM_STATUS_LABELS = {
    "collecting": "收集中",
    "submitted": "已提交",
    "reimbursed": "已报销",
    "archived": "已归档",
}

logger = logging.getLogger(__name__)


_IMAGE_ATTACHMENT_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png"})
_THUMBNAIL_SIZE = QSize(180, 120)
_ATTACHMENT_CARDS_PER_ROW = 3


def _configure_dialog(dialog: QDialog, title: str, *, minimum_width: int = 500) -> QVBoxLayout:
    """Apply the shared layout used by the application's form dialogs."""
    dialog.setObjectName("standardDialog")
    dialog.setWindowTitle(title)
    dialog.setMinimumWidth(minimum_width)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(24, 24, 24, 20)
    layout.setSpacing(16)
    heading = QLabel(title)
    heading.setObjectName("dialogTitle")
    layout.addWidget(heading)
    return layout


def _configure_dialog_buttons(
    buttons: QDialogButtonBox, *, save_text: str
) -> None:
    """Give save/cancel actions stable labels and visual hierarchy."""
    save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
    if save_button is not None:
        save_button.setText(save_text)
        save_button.setObjectName("primaryButton")
    cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
    if cancel_button is not None:
        cancel_button.setText("取消")


def _configure_message_dialog(dialog: QMessageBox) -> None:
    """Keep confirmation and choice dialogs aligned with form dialogs."""
    dialog.setObjectName("standardMessageDialog")
    dialog.setMinimumWidth(420)


class NewBatchDialog(QDialog):
    """Collect the small set of fields needed to create a reimbursement batch."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = _configure_dialog(self, "新建报销批次")

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("例如：2026 年 8 月实验耗材")
        self.reimburser_input = QLineEdit()
        self.project_name_input = QLineEdit()
        self.notes_input = QTextEdit()
        self.notes_input.setFixedHeight(80)
        form.addRow("名称 *", self.name_input)
        form.addRow("报销人", self.reimburser_input)
        form.addRow("项目名称", self.project_name_input)
        form.addRow("备注", self.notes_input)
        layout.addLayout(form)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        _configure_dialog_buttons(self.buttons, save_text="创建批次")
        self.buttons.rejected.connect(self.reject)
        self.buttons.accepted.connect(self.accept)
        layout.addWidget(self.buttons)


class NewItemDialog(QDialog):
    """Collect one Item for the batch currently open in the detail page."""

    def __init__(self, batch_name: str, templates: list[object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = _configure_dialog(self, "新增物品", minimum_width=560)
        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.name_input = QLineEdit()
        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText("例如：23.45（留空为 0.00）")
        self.purchase_date_input = QLineEdit()
        self.purchase_date_input.setPlaceholderText("YYYY-MM-DD（可选）")
        self.platform_input = QLineEdit()
        self.merchant_input = QLineEdit()
        self.order_number_input = QLineEdit()
        self.template_input = QComboBox()
        for template in templates:
            self.template_input.addItem(template.name, template.id)
        self.batch_input = QLineEdit(batch_name)
        self.batch_input.setReadOnly(True)
        self.notes_input = QTextEdit()
        self.notes_input.setFixedHeight(80)
        form.addRow("物品名称 *", self.name_input)
        form.addRow("金额", self.amount_input)
        form.addRow("购买日期", self.purchase_date_input)
        form.addRow("平台", self.platform_input)
        form.addRow("商家", self.merchant_input)
        form.addRow("订单号", self.order_number_input)
        form.addRow("模板 *", self.template_input)
        form.addRow("批次", self.batch_input)
        form.addRow("备注", self.notes_input)
        layout.addLayout(form)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        _configure_dialog_buttons(self.buttons, save_text="创建物品")
        self.buttons.rejected.connect(self.reject)
        self.buttons.accepted.connect(self._accept_if_valid)
        layout.addWidget(self.buttons)

    def _accept_if_valid(self) -> None:
        try:
            self.total_amount_cents()
            self.purchase_date()
            if not self.name_input.text().strip():
                raise ValueError("物品名称不能为空。")
            if not isinstance(self.template_input.currentData(), int):
                raise ValueError("请选择模板。")
        except ValueError as error:
            QMessageBox.warning(self, "无法创建物品", str(error))
            return
        self.accept()

    def total_amount_cents(self) -> int:
        text = self.amount_input.text().strip()
        if not text:
            return 0
        try:
            amount = Decimal(text)
        except InvalidOperation as error:
            raise ValueError("金额必须是有效的十进制数。") from error
        if not amount.is_finite() or amount < 0:
            raise ValueError("金额必须大于或等于 0。")
        cents = amount * 100
        if cents != cents.to_integral_value():
            raise ValueError("金额最多保留两位小数。")
        return int(cents)

    def purchase_date(self) -> date | None:
        text = self.purchase_date_input.text().strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text)
        except ValueError as error:
            raise ValueError("购买日期请使用 YYYY-MM-DD 格式。") from error

    def template_id(self) -> int:
        template_id = self.template_input.currentData()
        if not isinstance(template_id, int):
            raise ValueError("请选择模板。")
        return template_id


class TemplateEditorDialog(QDialog):
    """Edit the collection-material snapshot used for future Items."""

    def __init__(
        self,
        template_service: TemplateService,
        material_types: list[object],
        template: object | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._template_service = template_service
        self._template = template
        self.template_id: int | None = None
        dialog_title = "编辑模板" if template is not None else "新建模板"
        layout = _configure_dialog(self, dialog_title, minimum_width=540)
        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.name_input = QLineEdit(getattr(template, "name", ""))
        self.description_input = QTextEdit(getattr(template, "description", "") or "")
        self.description_input.setFixedHeight(80)
        form.addRow("模板名称 *", self.name_input)
        form.addRow("描述", self.description_input)
        layout.addLayout(form)
        material_title = QLabel("模板材料")
        material_title.setObjectName("dialogSectionTitle")
        layout.addWidget(material_title)
        material_hint = QLabel("勾选“加入模板”后，可设置该材料是否必需。")
        material_hint.setObjectName("dialogHint")
        layout.addWidget(material_hint)

        material_list = QFrame()
        material_list.setObjectName("templateMaterialList")
        material_list_layout = QVBoxLayout(material_list)
        material_list_layout.setContentsMargins(12, 8, 12, 8)
        material_list_layout.setSpacing(4)

        selected = {
            value.material_type.code: value.required
            for value in getattr(template, "materials", ())
        }
        self.material_inputs: dict[str, tuple[QCheckBox, QCheckBox]] = {}
        for material_type in material_types:
            material_layout = QHBoxLayout()
            included = QCheckBox(material_type.name)
            included.setText(f"加入模板：{material_type.name}")
            included.setChecked(material_type.code in selected)
            required = QCheckBox("必需")
            required.setChecked(selected.get(material_type.code, True))
            required.setEnabled(included.isChecked())
            included.toggled.connect(required.setEnabled)
            material_layout.addWidget(included)
            material_layout.addWidget(required)
            material_layout.addStretch()
            material_list_layout.addLayout(material_layout)
            self.material_inputs[material_type.code] = (included, required)
        layout.addWidget(material_list)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        _configure_dialog_buttons(
            self.buttons, save_text="保存模板" if template is not None else "创建模板"
        )
        self.buttons.rejected.connect(self.reject)
        self.buttons.accepted.connect(self._save)
        layout.addWidget(self.buttons)

    def _save(self) -> None:
        selected = [
            (code, required.isChecked())
            for code, (included, required) in self.material_inputs.items()
            if included.isChecked()
        ]
        if not self.name_input.text().strip():
            QMessageBox.warning(self, "无法保存模板", "模板名称不能为空。")
            return
        if not selected:
            QMessageBox.warning(self, "无法保存模板", "请至少选择一项材料。")
            return

        try:
            if self._template is None:
                saved_template = self._template_service.create_template(
                    self.name_input.text(), self.description_input.toPlainText()
                )
                existing_codes: set[str] = set()
            else:
                saved_template = self._template_service.update_template(
                    self._template.id,
                    name=self.name_input.text(),
                    description=self.description_input.toPlainText(),
                )
                existing_codes = {
                    value.material_type.code for value in saved_template.materials
                }

            selected_codes = {code for code, _required in selected}
            for code in existing_codes - selected_codes:
                self._template_service.remove_material(saved_template.id, code)
            for sort_order, (code, required) in enumerate(selected, start=1):
                if code in existing_codes:
                    self._template_service.set_material_required(
                        saved_template.id, code, required=required
                    )
                else:
                    self._template_service.add_material(
                        saved_template.id,
                        code,
                        required=required,
                        sort_order=sort_order,
                    )
            self.template_id = saved_template.id
        except (TemplateServiceError, ValueError, SQLAlchemyError) as error:
            logger.exception("Failed to save template")
            QMessageBox.warning(self, "无法保存模板", str(error))
            return
        self.accept()


class MainWindow(QMainWindow):
    """The Phase 2 main window with a small, service-backed Dashboard."""

    def __init__(
        self,
        dashboard_service: DashboardService | None = None,
        batch_service: BatchService | None = None,
        item_service: ItemService | None = None,
        completeness_service: CompletenessService | None = None,
        template_service: TemplateService | None = None,
        attachment_service: AttachmentService | None = None,
        payment_screenshot_merge_service: PaymentScreenshotMergeService | None = None,
        submission_readiness_service: SubmissionReadinessService | None = None,
        export_service: ExportService | None = None,
        desktop_integration_service: DesktopIntegrationService | None = None,
        pending_materials_service: PendingMaterialsService | None = None,
        backup_service: BackupService | None = None,
        restore_service: RestoreService | None = None,
    ) -> None:
        super().__init__()
        self._dashboard_service = dashboard_service
        self._batch_service = batch_service
        self._item_service = item_service
        self._completeness_service = completeness_service
        self._template_service = template_service
        self._attachment_service = attachment_service
        self._payment_screenshot_merge_service = payment_screenshot_merge_service
        self._submission_readiness_service = submission_readiness_service
        self._export_service = export_service
        self._pending_materials_service = pending_materials_service
        self._backup_service = backup_service
        self._restore_service = restore_service
        self._desktop_integration_service = (
            desktop_integration_service or DesktopIntegrationService()
        )
        self._dashboard_data = (
            dashboard_service.get_data()
            if dashboard_service is not None
            else DashboardData(0, 0, 0, 0, ())
        )
        self.setWindowTitle("报销材料管理器")
        application = QApplication.instance()
        if application is not None:
            apply_light_theme(application)
        self.resize(1100, 700)
        self.setMinimumSize(1100, 700)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("appRoot")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.pages = self._build_pages()
        layout.addWidget(self._build_sidebar())
        layout.addWidget(self.pages, 1)
        self.setCentralWidget(root)

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame(self)
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(224)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 20)
        layout.setSpacing(12)

        title = QLabel("报销材料管理器")
        title.setObjectName("appTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setIconSize(QSize(18, 18))
        self.navigation.setSpacing(4)
        navigation_icons = (
            QStyle.StandardPixmap.SP_ComputerIcon,
            QStyle.StandardPixmap.SP_FileDialogDetailedView,
            QStyle.StandardPixmap.SP_FileIcon,
            QStyle.StandardPixmap.SP_MessageBoxWarning,
            QStyle.StandardPixmap.SP_DirIcon,
            QStyle.StandardPixmap.SP_FileDialogContentsView,
        )
        for page_title, icon_type in zip(PAGE_TITLES, navigation_icons, strict=True):
            self.navigation.addItem(QListWidgetItem(self.style().standardIcon(icon_type), page_title))
        self.navigation.setCurrentRow(0)
        self.navigation.currentRowChanged.connect(self._show_navigation_page)
        layout.addWidget(self.navigation, 1)
        return sidebar

    def _build_pages(self) -> QStackedWidget:
        pages = QStackedWidget(self)
        pages.setObjectName("pageStack")
        pages.addWidget(self._build_dashboard_page())
        pages.addWidget(self._build_batch_list_page())
        pages.addWidget(self._build_all_items_page())
        pages.addWidget(self._build_pending_materials_page())
        pages.addWidget(self._build_template_management_page())
        pages.addWidget(self._build_settings_page())
        pages.addWidget(self._build_batch_detail_page())
        pages.addWidget(self._build_item_detail_page())
        for page_index in range(pages.count()):
            pages.widget(page_index).setObjectName("contentPage")
        return pages

    def _show_navigation_page(self, page_index: int) -> None:
        if page_index == 0:
            self.refresh_dashboard()
        elif page_index == PENDING_MATERIALS_PAGE_INDEX:
            self.refresh_pending_materials()
        elif page_index == TEMPLATE_MANAGEMENT_PAGE_INDEX:
            self.refresh_template_list()
        self.pages.setCurrentIndex(page_index)

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("设置")
        title.setObjectName("settingsPageTitle")
        layout.addWidget(title)

        backup_section = QFrame()
        backup_section.setObjectName("databaseBackupSection")
        backup_layout = QVBoxLayout(backup_section)
        backup_layout.setContentsMargins(20, 20, 20, 20)
        backup_layout.setSpacing(10)

        section_title = QLabel("数据备份")
        section_title.setObjectName("settingsSectionTitle")
        backup_layout.addWidget(section_title)

        description = QLabel("备份将保存当前数据库及备份元信息，不包含附件文件。")
        description.setWordWrap(True)
        backup_layout.addWidget(description)

        archive_hint = QLabel("附件归档目录不会包含在本次数据库备份中。")
        archive_hint.setWordWrap(True)
        backup_layout.addWidget(archive_hint)

        self.backup_database_button = QPushButton("备份数据库")
        self.backup_database_button.setObjectName("backupDatabaseButton")
        self.backup_database_button.setEnabled(self._backup_service is not None)
        self.backup_database_button.clicked.connect(self._backup_database)
        backup_layout.addWidget(self.backup_database_button, alignment=Qt.AlignmentFlag.AlignLeft)

        self.backup_result_label = QLabel()
        self.backup_result_label.setObjectName("backupResult")
        self.backup_result_label.setWordWrap(True)
        self.backup_result_label.hide()
        backup_layout.addWidget(self.backup_result_label)

        layout.addWidget(backup_section)

        restore_section = QFrame()
        restore_section.setObjectName("databaseRestoreSection")
        restore_layout = QVBoxLayout(restore_section)
        restore_layout.setContentsMargins(20, 20, 20, 20)
        restore_layout.setSpacing(10)

        restore_title = QLabel("恢复数据库")
        restore_title.setObjectName("settingsSectionTitle")
        restore_layout.addWidget(restore_title)

        restore_description = QLabel(
            "恢复数据库会替换当前数据库。恢复前系统会自动备份当前数据库。"
            "附件文件不会被恢复或删除。"
        )
        restore_description.setWordWrap(True)
        restore_layout.addWidget(restore_description)

        self.restore_database_button = QPushButton("恢复数据库")
        self.restore_database_button.setObjectName("restoreDatabaseButton")
        self.restore_database_button.setEnabled(self._restore_service is not None)
        self.restore_database_button.clicked.connect(self._restore_database)
        restore_layout.addWidget(
            self.restore_database_button, alignment=Qt.AlignmentFlag.AlignLeft
        )

        self.restore_result_label = QLabel()
        self.restore_result_label.setObjectName("restoreResult")
        self.restore_result_label.setWordWrap(True)
        self.restore_result_label.hide()
        restore_layout.addWidget(self.restore_result_label)

        layout.addWidget(restore_section)
        layout.addStretch()
        return page

    def _backup_database(self) -> None:
        backup_directory = QFileDialog.getExistingDirectory(self, "选择数据库备份目录")
        if not backup_directory or self._backup_service is None:
            return

        try:
            result = self._backup_service.create_backup(Path(backup_directory))
        except Exception:
            logger.exception("Failed to back up database")
            QMessageBox.warning(self, "数据库备份失败", "数据库备份失败，请检查目录权限后重试。")
            return

        self.backup_result_label.setText(
            "数据库备份完成。\n"
            f"数据库：{result.database_path}\n"
            f"元信息：{result.metadata_path}"
        )
        self.backup_result_label.show()

    def _restore_database(self) -> None:
        backup_db_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择数据库备份",
            "",
            "SQLite Database (*.db)",
        )
        if not backup_db_path or self._restore_service is None:
            return

        if not self._confirm_restore_database(
            "确定恢复这个数据库吗？",
            "当前数据库会被替换。\n"
            "系统会先自动备份当前数据库。\n"
            "附件目录不会被修改。\n"
            "恢复后建议重新启动应用。",
            "继续恢复",
        ):
            return
        if not self._confirm_restore_database(
            "即将替换当前数据库。是否继续？",
            "当前数据库将被替换，附件目录不会被修改。",
            "确认恢复",
        ):
            return

        try:
            result = self._restore_service.restore_database(Path(backup_db_path))
        except UnknownSchemaRevisionError:
            logger.warning("Restore rejected because the backup schema is incompatible")
            QMessageBox.warning(
                self, "无法恢复数据库", "该备份数据库版本无法被当前应用识别。"
            )
        except InvalidBackupDatabaseError:
            logger.warning("Restore rejected because the selected file is invalid")
            QMessageBox.warning(
                self, "无法恢复数据库", "选择的文件不是有效的报销数据库。"
            )
        except SafetyBackupError:
            logger.exception("Restore cancelled because the safety backup failed")
            QMessageBox.warning(
                self, "无法恢复数据库", "恢复前备份当前数据库失败，恢复已取消。"
            )
        except DatabaseReplacementError:
            logger.exception("Database restore failed after replacement was attempted")
            QMessageBox.warning(
                self, "无法恢复数据库", "数据库恢复失败，原数据库已恢复。"
            )
        except RestoreServiceError:
            logger.exception("Database restore failed")
            QMessageBox.warning(self, "无法恢复数据库", "数据库恢复失败，请检查日志后重试。")
        except Exception:
            logger.exception("Unexpected database restore failure")
            QMessageBox.warning(self, "无法恢复数据库", "数据库恢复失败，请检查日志后重试。")
        else:
            self.restore_result_label.setText(
                "数据库恢复成功。\n"
                f"恢复来源：{result.source_backup_path}\n"
                f"当前数据库：{result.restored_database_path}\n"
                f"恢复前安全备份：{result.safety_backup_path}\n\n"
                "数据库已恢复。请重新启动应用以加载恢复后的全部数据。\n"
                "数据库恢复不会恢复附件文件。如果旧数据库引用的附件当前不存在，"
                "软件会将其显示为文件缺失。"
            )
            self.restore_result_label.show()

    def _confirm_restore_database(
        self, title: str, text: str, confirm_label: str
    ) -> bool:
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle(title)
        dialog.setText(text)
        cancel_button = dialog.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        confirm_button = dialog.addButton(
            confirm_label, QMessageBox.ButtonRole.AcceptRole
        )
        confirm_button.setObjectName("dangerButton")
        dialog.setDefaultButton(cancel_button)
        dialog.exec()
        return dialog.clickedButton() is confirm_button

    def _build_template_management_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("模板管理")
        title.setObjectName("templatePageTitle")
        header.addWidget(title)
        header.addStretch()
        self.new_template_button = QPushButton("+ 新建模板")
        self.new_template_button.setObjectName("primaryButton")
        self.new_template_button.clicked.connect(self._open_new_template_dialog)
        header.addWidget(self.new_template_button)
        layout.addLayout(header)

        self.template_table = QTableWidget(0, 3)
        self.template_table.setHorizontalHeaderLabels(
            ("模板名称", "材料数量", "必需材料数量")
        )
        self.template_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.template_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.template_table.setObjectName("templateTable")
        self.template_table.setAlternatingRowColors(True)
        self.template_table.setShowGrid(False)
        self.template_table.verticalHeader().setVisible(False)
        self.template_table.verticalHeader().setDefaultSectionSize(42)
        self.template_table.cellDoubleClicked.connect(self._open_template_editor)
        self.template_table.horizontalHeader().setStretchLastSection(False)
        self.template_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.template_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.template_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        layout.addWidget(self.template_table, 1)

        self.template_empty_state = QFrame()
        self.template_empty_state.setObjectName("templateEmptyState")
        empty_layout = QVBoxLayout(self.template_empty_state)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.setSpacing(8)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_title = QLabel("暂无报销模板")
        empty_title.setObjectName("emptyStateTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_description = QLabel("创建模板后，新建物品时可以快速生成材料清单。")
        empty_description.setObjectName("emptyStateDescription")
        empty_description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_new_template_button = QPushButton("+ 新建模板")
        self.empty_new_template_button.setObjectName("primaryButton")
        self.empty_new_template_button.clicked.connect(self._open_new_template_dialog)
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_description)
        empty_layout.addSpacing(8)
        empty_layout.addWidget(self.empty_new_template_button, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.template_empty_state)
        self.refresh_template_list()
        return page

    def refresh_template_list(self) -> None:
        """Render template counts supplied by TemplateService."""
        self.template_table.setRowCount(0)
        if self._template_service is None:
            self.template_empty_state.setVisible(True)
            self.template_table.setVisible(False)
            return
        try:
            templates = self._template_service.list_templates()
        except (TemplateServiceError, SQLAlchemyError):
            logger.exception("Failed to list templates")
            self.template_empty_state.setVisible(True)
            self.template_table.setVisible(False)
            return
        for template in templates:
            row = self.template_table.rowCount()
            self.template_table.insertRow(row)
            values = (
                template.name,
                str(len(template.materials)),
                str(sum(value.required for value in template.materials)),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, template.id)
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                else:
                    item.setData(
                        Qt.ItemDataRole.TextAlignmentRole,
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    )
                self.template_table.setItem(row, column, item)
        is_empty = self.template_table.rowCount() == 0
        self.template_empty_state.setVisible(is_empty)
        self.template_table.setVisible(not is_empty)

    def _open_new_template_dialog(self) -> None:
        self._open_template_dialog()

    def _open_template_editor(self, row: int, _column: int) -> None:
        item = self.template_table.item(row, 0)
        if item is None:
            return
        template_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(template_id, int):
            self._open_template_dialog(template_id)

    def _open_template_dialog(self, template_id: int | None = None) -> None:
        if self._template_service is None:
            return
        try:
            template = (
                self._template_service.get_template(template_id)
                if template_id is not None
                else None
            )
            dialog = TemplateEditorDialog(
                self._template_service,
                self._template_service.list_material_types(),
                template,
                self,
            )
        except (TemplateServiceError, SQLAlchemyError) as error:
            logger.exception("Failed to open template editor")
            QMessageBox.warning(self, "无法打开模板", str(error))
            return
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_template_list()

    def _build_pending_materials_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("pendingMaterialsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title_layout = QVBoxLayout()
        title_layout.setSpacing(4)
        title = QLabel("待补材料")
        title.setObjectName("pageTitle")
        title_layout.addWidget(title)
        self.pending_materials_summary_label = QLabel()
        self.pending_materials_summary_label.setObjectName("pendingMaterialsSummary")
        title_layout.addWidget(self.pending_materials_summary_label)
        header.addLayout(title_layout)
        header.addStretch()
        self.refresh_pending_materials_button = QPushButton("刷新")
        self.refresh_pending_materials_button.clicked.connect(
            self.refresh_pending_materials
        )
        header.addWidget(self.refresh_pending_materials_button)
        layout.addLayout(header)

        self.pending_materials_table = QTableWidget(0, 6)
        self.pending_materials_table.setObjectName("pendingMaterialsTable")
        self.pending_materials_table.setHorizontalHeaderLabels(
            ("物品名称", "所属批次", "材料收集", "缺失原始材料", "提交材料", "缺失提交材料")
        )
        self.pending_materials_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.pending_materials_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.pending_materials_table.setAlternatingRowColors(True)
        self.pending_materials_table.setShowGrid(False)
        self.pending_materials_table.cellDoubleClicked.connect(
            self._open_pending_material_item_detail
        )
        self.pending_materials_table.verticalHeader().setVisible(False)
        self.pending_materials_table.verticalHeader().setDefaultSectionSize(42)
        self.pending_materials_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in range(1, self.pending_materials_table.columnCount()):
            self.pending_materials_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        layout.addWidget(self.pending_materials_table, 1)

        self.pending_materials_empty_state = QFrame()
        self.pending_materials_empty_state.setObjectName("pendingMaterialsEmptyState")
        empty_layout = QVBoxLayout(self.pending_materials_empty_state)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.setSpacing(8)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pending_materials_empty_title = QLabel(
            "当前没有待补材料或待生成提交材料的物品。"
        )
        self.pending_materials_empty_title.setObjectName("emptyStateTitle")
        self.pending_materials_empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.pending_materials_empty_title)
        empty_description = QLabel("所有物品的提交材料都已准备完成。")
        empty_description.setObjectName("emptyStateDescription")
        empty_description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_description)
        layout.addWidget(self.pending_materials_empty_state)
        self.refresh_pending_materials()
        return page

    def refresh_pending_materials(self) -> None:
        """Render pending entries supplied by the application service."""
        self.pending_materials_table.setRowCount(0)
        if self._pending_materials_service is None:
            self.pending_materials_summary_label.setText("还有 0 个物品需要处理")
            self.pending_materials_table.setVisible(False)
            self.pending_materials_empty_state.setVisible(True)
            return

        pending_items = self._pending_materials_service.list_pending_items()
        self.pending_materials_summary_label.setText(
            f"还有 {len(pending_items)} 个物品需要处理"
        )
        for entry in pending_items:
            row = self.pending_materials_table.rowCount()
            self.pending_materials_table.insertRow(row)
            values = (
                entry.item_name,
                entry.batch_name,
                self._pending_progress_text(
                    entry.collection_completed_count,
                    entry.collection_required_count,
                    complete=not entry.missing_collection_materials,
                ),
                self._pending_missing_text(
                    entry.missing_collection_materials, complete_text="材料完整"
                ),
                self._pending_progress_text(
                    entry.submission_completed_count,
                    entry.submission_required_count,
                    complete=not entry.missing_submission_materials,
                ),
                self._pending_missing_text(
                    entry.missing_submission_materials, complete_text="可提交"
                ),
            )
            for column, value in enumerate(values):
                table_item = QTableWidgetItem(value)
                if column == 0:
                    table_item.setData(Qt.ItemDataRole.UserRole, entry.item_id)
                if column in (3, 5):
                    table_item.setForeground(
                        QColor("#4d7b5b") if value in {"材料完整", "可提交"} else QColor("#8a4c08")
                    )
                    if value not in {"材料完整", "可提交"}:
                        table_item.setFont(QFont("", -1, QFont.Weight.DemiBold))
                self.pending_materials_table.setItem(row, column, table_item)
        has_pending_items = self.pending_materials_table.rowCount() > 0
        self.pending_materials_table.setVisible(has_pending_items)
        self.pending_materials_empty_state.setVisible(not has_pending_items)

    @staticmethod
    def _pending_progress_text(completed: int, required: int, *, complete: bool) -> str:
        return f"{completed} / {required}{' ✓' if complete else ''}"

    @staticmethod
    def _pending_missing_text(
        missing_materials: tuple[str, ...], *, complete_text: str
    ) -> str:
        return complete_text if not missing_materials else f"缺：{'、'.join(missing_materials)}"

    def _build_all_items_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("allItemsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        self.all_items_title = QLabel("所有物品")
        self.all_items_title.setObjectName("pageTitle")
        header.addWidget(self.all_items_title)
        header.addStretch()
        self.all_items_search_input = QLineEdit()
        self.all_items_search_input.setObjectName("allItemsSearchInput")
        self.all_items_search_input.setPlaceholderText("搜索物品、商家或订单号")
        self.all_items_search_input.setMinimumWidth(280)
        self.all_items_search_input.setMaximumWidth(360)
        self.all_items_search_input.textChanged.connect(self.refresh_all_items)
        header.addWidget(self.all_items_search_input)
        layout.addLayout(header)

        self.all_items_table = QTableWidget(0, 8)
        self.all_items_table.setObjectName("allItemsTable")
        self.all_items_table.setHorizontalHeaderLabels(
            (
                "物品",
                "批次",
                "金额",
                "日期",
                "平台",
                "材料",
                "缺失材料",
                "报销状态",
            )
        )
        self.all_items_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.all_items_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.all_items_table.setAlternatingRowColors(True)
        self.all_items_table.setShowGrid(False)
        self.all_items_table.verticalHeader().setVisible(False)
        self.all_items_table.verticalHeader().setDefaultSectionSize(42)
        self.all_items_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in range(1, self.all_items_table.columnCount()):
            self.all_items_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.all_items_table.cellDoubleClicked.connect(self._open_item_detail)
        layout.addWidget(self.all_items_table, 1)

        self.all_items_empty_state = QFrame()
        self.all_items_empty_state.setObjectName("allItemsEmptyState")
        empty_layout = QVBoxLayout(self.all_items_empty_state)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.setSpacing(8)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.all_items_empty_title = QLabel()
        self.all_items_empty_title.setObjectName("emptyStateTitle")
        self.all_items_empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.all_items_empty_title)
        self.all_items_empty_description = QLabel()
        self.all_items_empty_description.setObjectName("emptyStateDescription")
        self.all_items_empty_description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.all_items_empty_description)
        layout.addWidget(self.all_items_empty_state, 1)
        self.refresh_all_items()
        return page

    def refresh_all_items(self, _query: str | None = None) -> None:
        """Refresh the all-items list through application services only."""
        self.all_items_table.setRowCount(0)
        if self._item_service is None or self._completeness_service is None:
            self._set_all_items_empty_state(is_search_result=False)
            return

        batch_names = (
            {batch.id: batch.name for batch in self._batch_service.list_batches()}
            if self._batch_service is not None
            else {}
        )
        query = self.all_items_search_input.text()
        for item in self._item_service.search_items(query):
            completeness = self._completeness_service.calculate(item.id)
            missing_materials = "、".join(
                material.name for material in completeness.missing
            )
            row = self.all_items_table.rowCount()
            self.all_items_table.insertRow(row)
            values = (
                item.name,
                batch_names.get(item.batch_id, "—"),
                self._format_cents(item.total_amount_cents),
                item.purchase_date.isoformat() if item.purchase_date else "—",
                item.platform or "—",
                (
                    f"{completeness.completed_count} / "
                    f"{completeness.required_count} ✓"
                    if completeness.is_complete
                    else (
                        f"{completeness.completed_count} / "
                        f"{completeness.required_count}"
                    )
                ),
                missing_materials or "材料完整",
                ITEM_STATUS_LABELS.get(str(item.status), str(item.status)),
            )
            for column, value in enumerate(values):
                table_item = QTableWidgetItem(value)
                if column == 0:
                    table_item.setData(Qt.ItemDataRole.UserRole, item.id)
                if column == 2:
                    table_item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.all_items_table.setItem(row, column, table_item)
        self._set_all_items_empty_state(
            is_search_result=bool(query.strip())
            and self.all_items_table.rowCount() == 0
        )

    def _set_all_items_empty_state(self, *, is_search_result: bool) -> None:
        """Show the empty state appropriate to the current all-items query."""
        is_empty = self.all_items_table.rowCount() == 0
        self.all_items_table.setVisible(not is_empty)
        self.all_items_empty_state.setVisible(is_empty)
        if not is_empty:
            return
        if is_search_result:
            self.all_items_empty_title.setText("没有找到匹配的物品")
            self.all_items_empty_description.setText("请尝试其他物品、商家或订单号关键词。")
            return
        self.all_items_empty_title.setText("暂无报销物品")
        self.all_items_empty_description.setText(
            "创建报销批次并添加物品后，它们会出现在这里。"
        )

    def _build_batch_list_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("batchListPage")
        self.batch_list_page = page
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("报销批次")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch()
        self.new_batch_button = QPushButton("+ 新建批次")
        self.new_batch_button.setObjectName("primaryButton")
        self.new_batch_button.clicked.connect(self._open_new_batch_dialog)
        header.addWidget(self.new_batch_button)
        layout.addLayout(header)

        self.batch_table = QTableWidget(0, 4)
        self.batch_table.setObjectName("batchTable")
        self.batch_table.setHorizontalHeaderLabels(
            ("批次名称", "创建日期", "物品数量", "总金额")
        )
        self.batch_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.batch_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.batch_table.setAlternatingRowColors(True)
        self.batch_table.setShowGrid(False)
        self.batch_table.verticalHeader().setVisible(False)
        self.batch_table.verticalHeader().setDefaultSectionSize(42)
        self.batch_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in (1, 2, 3):
            self.batch_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.batch_table.cellDoubleClicked.connect(self._open_batch_detail)
        layout.addWidget(self.batch_table, 1)

        self.batch_empty_state = QFrame()
        self.batch_empty_state.setObjectName("batchListEmptyState")
        empty_layout = QVBoxLayout(self.batch_empty_state)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.setSpacing(8)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_title = QLabel("暂无报销批次")
        empty_title.setObjectName("emptyStateTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_title)
        empty_description = QLabel("创建一个批次开始整理报销材料。")
        empty_description.setObjectName("emptyStateDescription")
        empty_description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_description)
        self.empty_new_batch_button = QPushButton("新建批次")
        self.empty_new_batch_button.setObjectName("primaryButton")
        self.empty_new_batch_button.clicked.connect(self._open_new_batch_dialog)
        empty_layout.addWidget(self.empty_new_batch_button, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.batch_empty_state, 1)
        self.refresh_batch_list()
        return page

    def _build_item_detail_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("itemDetailPage")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)

        self.item_detail_scroll_area = QScrollArea()
        self.item_detail_scroll_area.setObjectName("itemDetailScrollArea")
        self.item_detail_scroll_area.setWidgetResizable(True)
        self.item_detail_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        page_layout.addWidget(self.item_detail_scroll_area)

        content = QWidget()
        content.setObjectName("itemDetailContent")
        self.item_detail_scroll_area.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        self.back_to_all_items_button = QPushButton("← 所有物品")
        self.back_to_all_items_button.setObjectName("itemDetailBackButton")
        self.back_to_all_items_button.clicked.connect(self._show_item_detail_return_page)
        layout.addWidget(self.back_to_all_items_button, 0, Qt.AlignmentFlag.AlignLeft)

        headline = QFrame()
        headline.setObjectName("itemDetailHeadline")
        headline_layout = QHBoxLayout(headline)
        headline_layout.setContentsMargins(0, 0, 0, 0)
        headline_layout.setSpacing(16)
        self.item_detail_name_label = QLabel()
        self.item_detail_name_label.setObjectName("itemDetailName")
        self.item_detail_name_label.setWordWrap(True)
        headline_layout.addWidget(self.item_detail_name_label, 1)
        self.item_detail_amount_label = QLabel()
        self.item_detail_amount_label.setObjectName("itemDetailAmount")
        headline_layout.addWidget(self.item_detail_amount_label)
        layout.addWidget(headline)

        details_frame = QFrame()
        details_frame.setObjectName("itemDetailMetadata")
        details = QFormLayout(details_frame)
        details.setContentsMargins(16, 14, 16, 14)
        details.setHorizontalSpacing(28)
        details.setVerticalSpacing(8)
        self.item_detail_purchase_date_label = QLabel()
        self.item_detail_platform_label = QLabel()
        self.item_detail_merchant_label = QLabel()
        self.item_detail_order_number_label = QLabel()
        self.item_detail_batch_label = QLabel()
        self.item_detail_status_label = QLabel()
        details.addRow("平台", self.item_detail_platform_label)
        details.addRow("购买日期", self.item_detail_purchase_date_label)
        details.addRow("商家", self.item_detail_merchant_label)
        details.addRow("订单号", self.item_detail_order_number_label)
        details.addRow("所属批次", self.item_detail_batch_label)
        details.addRow("报销状态", self.item_detail_status_label)
        layout.addWidget(details_frame)

        status_layout = QHBoxLayout()
        status_layout.setSpacing(16)
        collection_card = QFrame()
        collection_card.setObjectName("itemDetailStatusCard")
        collection_layout = QVBoxLayout(collection_card)
        collection_layout.setContentsMargins(16, 14, 16, 14)
        collection_layout.setSpacing(8)
        collection_title = QLabel("材料收集")
        collection_title.setObjectName("itemDetailStatusTitle")
        collection_layout.addWidget(collection_title)
        self.item_detail_completeness_label = QLabel()
        self.item_detail_completeness_label.setObjectName("itemDetailStatusText")
        collection_layout.addWidget(self.item_detail_completeness_label)
        self.item_detail_collection_progress = QProgressBar()
        self.item_detail_collection_progress.setObjectName("itemDetailProgress")
        self.item_detail_collection_progress.setTextVisible(False)
        collection_layout.addWidget(self.item_detail_collection_progress)
        status_layout.addWidget(collection_card, 1)

        submission_card = QFrame()
        submission_card.setObjectName("itemDetailStatusCard")
        submission_layout = QVBoxLayout(submission_card)
        submission_layout.setContentsMargins(16, 14, 16, 14)
        submission_layout.setSpacing(8)
        submission_title = QLabel("提交材料")
        submission_title.setObjectName("itemDetailStatusTitle")
        submission_layout.addWidget(submission_title)
        self.item_detail_submission_readiness_label = QLabel()
        self.item_detail_submission_readiness_label.setObjectName("itemDetailStatusText")
        submission_layout.addWidget(self.item_detail_submission_readiness_label)
        self.item_detail_submission_progress = QProgressBar()
        self.item_detail_submission_progress.setObjectName("itemDetailProgress")
        self.item_detail_submission_progress.setTextVisible(False)
        submission_layout.addWidget(self.item_detail_submission_progress)
        status_layout.addWidget(submission_card, 1)
        layout.addLayout(status_layout)

        action_frame = QFrame()
        action_frame.setObjectName("itemDetailPrimaryActions")
        action_layout = QHBoxLayout(action_frame)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)
        self.export_submission_materials_button = QPushButton("导出提交材料")
        self.export_submission_materials_button.setObjectName("primaryButton")
        self.export_submission_materials_button.clicked.connect(
            self._export_submission_materials
        )
        action_layout.addWidget(self.export_submission_materials_button)
        action_layout.addStretch()
        layout.addWidget(action_frame)

        self.merged_payment_section = QFrame()
        self.merged_payment_section.setObjectName("mergedPaymentSection")
        self.merged_payment_section_layout = QVBoxLayout(self.merged_payment_section)
        self.merged_payment_section_layout.setContentsMargins(16, 16, 16, 16)
        self.merged_payment_section_layout.setSpacing(12)
        layout.addWidget(self.merged_payment_section)

        materials_title = QLabel("材料")
        materials_title.setObjectName("sectionTitle")
        layout.addWidget(materials_title)
        self.item_detail_materials_tree = QTreeWidget()
        self.item_detail_materials_tree.setObjectName("itemDetailMaterialsTree")
        self.item_detail_materials_tree.setHeaderLabels(
            ("材料要求", "附件", "操作")
        )
        self.item_detail_materials_tree.setRootIsDecorated(True)
        header = self.item_detail_materials_tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.item_detail_materials_tree.setColumnWidth(2, 120)
        self.item_detail_materials_tree.setMinimumHeight(280)
        layout.addWidget(self.item_detail_materials_tree)

        danger_frame = QFrame()
        danger_frame.setObjectName("itemDetailDangerZone")
        danger_layout = QHBoxLayout(danger_frame)
        danger_layout.setContentsMargins(16, 12, 16, 12)
        danger_layout.setSpacing(12)
        danger_layout.addWidget(QLabel("危险操作"))
        danger_layout.addStretch()
        self.delete_item_button = QPushButton("删除物品")
        self.delete_item_button.setObjectName("dangerButton")
        self.delete_item_button.clicked.connect(self._delete_current_item)
        danger_layout.addWidget(self.delete_item_button)
        layout.addWidget(danger_frame)
        layout.addStretch()
        return page

    def _open_item_detail(self, row: int, _column: int) -> None:
        self._open_item_detail_from_table(
            self.all_items_table, row, ALL_ITEMS_PAGE_INDEX
        )

    def _open_pending_material_item_detail(self, row: int, _column: int) -> None:
        self._open_item_detail_from_table(
            self.pending_materials_table, row, PENDING_MATERIALS_PAGE_INDEX
        )

    def _open_item_detail_from_table(
        self, table: QTableWidget, row: int, return_page_index: int
    ) -> None:
        item_id_item = table.item(row, 0)
        if item_id_item is None:
            return
        item_id = item_id_item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(item_id, int):
            return
        self._item_detail_return_page_index = return_page_index
        self._populate_item_detail(item_id)
        self.pages.setCurrentIndex(ITEM_DETAIL_PAGE_INDEX)

    def _populate_item_detail(self, item_id: int) -> None:
        if self._item_service is None or self._completeness_service is None:
            return
        item = self._item_service.get_item(item_id)
        completeness = self._completeness_service.calculate(item_id)
        attachments_by_material: dict[int, list[Attachment]] = {}
        if self._attachment_service is not None:
            for attachment in self._attachment_service.list_attachments(item_id):
                attachments_by_material.setdefault(
                    attachment.material_type_id, []
                ).append(attachment)

        self.item_detail_name_label.setText(item.name)
        self.item_detail_amount_label.setText(
            self._format_cents(item.total_amount_cents)
        )
        self.item_detail_purchase_date_label.setText(
            item.purchase_date.isoformat() if item.purchase_date else "\u2014"
        )
        self.item_detail_platform_label.setText(item.platform or "\u2014")
        self.item_detail_merchant_label.setText(item.merchant or "\u2014")
        self.item_detail_order_number_label.setText(item.order_number or "\u2014")
        self.item_detail_batch_label.setText(item.batch.name)
        self.item_detail_status_label.setText(
            ITEM_STATUS_LABELS.get(str(item.status), str(item.status))
        )
        if completeness.is_complete:
            completeness_text = (
                f"\u6750\u6599\u5b8c\u6574\u5ea6\uff1a{completeness.completed_count} / "
                f"{completeness.required_count}\n{completeness.percentage}%\n\u6750\u6599\u5b8c\u6574"
            )
        else:
            missing = "\u3001".join(material.name for material in completeness.missing)
            completeness_text = (
                f"\u6750\u6599\u5b8c\u6574\u5ea6\uff1a{completeness.completed_count} / "
                f"{completeness.required_count}\n{completeness.percentage}%\n\u7f3a\u5c11\uff1a{missing}"
            )
        self.item_detail_completeness_label.setText(completeness_text)
        self.item_detail_collection_progress.setRange(0, 100)
        self.item_detail_collection_progress.setValue(completeness.percentage)
        if self._submission_readiness_service is not None:
            submission = self._submission_readiness_service.calculate(item_id)
            if submission.is_ready:
                submission_text = (
                    f"\u63d0\u4ea4\u6750\u6599\uff1a{submission.completed_count} / "
                    f"{submission.required_count} \u2705\n\u53ef\u63d0\u4ea4"
                )
            else:
                missing = "\u3001".join(material.name for material in submission.missing)
                submission_text = (
                    f"\u63d0\u4ea4\u6750\u6599\uff1a{submission.completed_count} / "
                    f"{submission.required_count}\n\u7f3a\uff1a{missing}"
                )
            self.item_detail_submission_readiness_label.setText(submission_text)
            submission_percentage = (
                round(submission.completed_count * 100 / submission.required_count)
                if submission.required_count
                else 100
            )
            self.item_detail_submission_progress.setRange(0, 100)
            self.item_detail_submission_progress.setValue(submission_percentage)
            self.export_submission_materials_button.setEnabled(
                submission.is_ready and self._export_service is not None
            )
            self.export_submission_materials_button.setToolTip(
                "" if submission.is_ready else f"提交材料未完整，缺少：{missing}"
            )
        else:
            self.item_detail_submission_readiness_label.clear()
            self.item_detail_submission_progress.setRange(0, 100)
            self.item_detail_submission_progress.setValue(0)
            self.export_submission_materials_button.setEnabled(False)
            self.export_submission_materials_button.setToolTip("提交材料状态当前不可用。")
        self._current_item_detail_id = item_id

        self.item_detail_materials_tree.clear()
        for requirement in item.requirements:
            attachments = attachments_by_material.get(
                requirement.material_type_id, []
            )
            fulfilled = any(not attachment.is_derived for attachment in attachments)
            marker = "✅" if fulfilled else ("❌" if requirement.required else "○")
            requirement_label = "必需" if requirement.required else "可选"
            attachment_count = len(attachments)
            parent = QTreeWidgetItem(
                [
                    f"{marker} {requirement.material_type.name}",
                    f"{attachment_count} 个附件 · {requirement_label}",
                ]
            )
            self.item_detail_materials_tree.addTopLevelItem(parent)
            add_attachment_button = QPushButton("+ 添加附件")
            add_attachment_button.setObjectName("itemDetailAddAttachmentButton")
            add_attachment_button.setMinimumWidth(
                add_attachment_button.sizeHint().width()
            )
            parent.setSizeHint(2, add_attachment_button.sizeHint())
            add_attachment_button.clicked.connect(
                lambda _checked=False, material_type_id=requirement.material_type_id: self._select_and_add_attachment(
                    item_id, material_type_id
                )
            )
            self.item_detail_materials_tree.setItemWidget(
                parent, 2, add_attachment_button
            )
            if attachments:
                attachment_grid = self._build_attachment_grid(attachments)
                child = QTreeWidgetItem(["", ""])
                child.setFirstColumnSpanned(True)
                parent.addChild(child)
                self.item_detail_materials_tree.setItemWidget(child, 0, attachment_grid)
                attachment_grid.layout().activate()
                child.setSizeHint(0, attachment_grid.sizeHint())
            else:
                empty_text = "缺少材料" if requirement.required else "暂未添加（可选）"
                parent.addChild(QTreeWidgetItem(["", empty_text]))
            parent.setExpanded(True)

        self._populate_merged_payment_section(item_id, attachments_by_material, item)

    def _populate_merged_payment_section(
        self,
        item_id: int,
        attachments_by_material: dict[int, list[Attachment]],
        item: Item,
    ) -> None:
        """Render the payment-merge workflow using the merge service's selection rule."""
        self._clear_layout(self.merged_payment_section_layout)

        title = QLabel("合并支付截图")
        title.setObjectName("mergedPaymentSectionTitle")
        self.merged_payment_section_layout.addWidget(title)

        material_type_ids = {
            requirement.material_type.code: requirement.material_type_id
            for requirement in item.requirements
        }
        order_id = material_type_ids.get("order_screenshot")
        payment_id = material_type_ids.get(PAYMENT_SCREENSHOT_CODE)
        order_attachment = self._latest_usable_merge_source(
            attachments_by_material.get(order_id, []) if order_id is not None else []
        )
        payment_attachment = self._latest_usable_merge_source(
            attachments_by_material.get(payment_id, []) if payment_id is not None else []
        )

        source_layout = QHBoxLayout()
        source_layout.setSpacing(12)
        source_layout.addWidget(
            self._build_merge_source_card(
                "订单截图",
                attachments_by_material.get(order_id, []) if order_id is not None else [],
                order_attachment,
                "mergeOrderSource",
            ),
            1,
        )
        relation = QLabel("+")
        relation.setObjectName("mergedPaymentRelation")
        relation.setAlignment(Qt.AlignmentFlag.AlignCenter)
        source_layout.addWidget(relation)
        source_layout.addWidget(
            self._build_merge_source_card(
                "支付截图",
                attachments_by_material.get(payment_id, []) if payment_id is not None else [],
                payment_attachment,
                "mergePaymentSource",
            ),
            1,
        )
        self.merged_payment_section_layout.addLayout(source_layout)

        arrow = QLabel("↓  订单截图 + 支付截图 → 合并支付截图")
        arrow.setObjectName("mergedPaymentFlow")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.merged_payment_section_layout.addWidget(arrow)

        result = QFrame()
        result.setObjectName("mergedPaymentResult")
        result_layout = QVBoxLayout(result)
        result_layout.setContentsMargins(12, 12, 12, 12)
        result_layout.setSpacing(8)
        result_title = QLabel("合并支付截图")
        result_title.setObjectName("mergedPaymentResultTitle")
        result_layout.addWidget(result_title)
        latest_result = self._latest_usable_merged_payment(
            attachments_by_material.get(payment_id, []) if payment_id is not None else [],
            payment_id,
        )
        if latest_result is None:
            empty = QLabel("尚未生成合并支付截图")
            empty.setObjectName("mergedPaymentEmpty")
            result_layout.addWidget(empty)
        else:
            result_layout.addWidget(self._build_attachment_card(latest_result))
        self.merged_payment_section_layout.addWidget(result)

        self.generate_merged_payment_screenshot_button = QPushButton(
            "重新生成" if latest_result is not None else "生成合并支付截图"
        )
        self.generate_merged_payment_screenshot_button.setObjectName("primaryButton")
        self.generate_merged_payment_screenshot_button.clicked.connect(
            self._generate_merged_payment_screenshot
        )
        availability = (
            self._payment_screenshot_merge_service.get_availability(item_id)
            if self._payment_screenshot_merge_service is not None
            else None
        )
        self.generate_merged_payment_screenshot_button.setEnabled(
            availability is not None and availability.can_generate
        )
        self.generate_merged_payment_screenshot_button.setToolTip(
            availability.message if availability is not None else "合并服务当前不可用。"
        )
        self.merged_payment_section_layout.addWidget(
            self.generate_merged_payment_screenshot_button,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )

    @staticmethod
    def _clear_layout(layout: QLayout) -> None:
        while layout.count():
            child = layout.takeAt(0)
            child_layout = child.layout()
            if child_layout is not None:
                MainWindow._clear_layout(child_layout)
            widget = child.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _latest_usable_merge_source(
        self, attachments: list[Attachment]
    ) -> Attachment | None:
        for attachment in reversed(attachments):
            if attachment.is_derived or attachment.file_extension.lower() not in _IMAGE_ATTACHMENT_EXTENSIONS:
                continue
            if self._get_attachment_display_path(attachment.id) is not None:
                return attachment
        return None

    def _build_merge_source_card(
        self,
        title: str,
        attachments: list[Attachment],
        selected_attachment: Attachment | None,
        object_name: str,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName(object_name)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("mergedPaymentSourceTitle")
        layout.addWidget(heading)
        if selected_attachment is not None:
            path = self._get_attachment_display_path(selected_attachment.id)
            assert path is not None
            self._add_image_thumbnail(
                layout,
                selected_attachment.id,
                path,
                selected_attachment.stored_filename,
            )
            filename = QLabel(selected_attachment.stored_filename)
            filename.setObjectName("mergedPaymentSourceFilename")
            filename.setWordWrap(True)
            layout.addWidget(filename)
        elif not any(not attachment.is_derived for attachment in attachments):
            missing = QLabel(f"缺少{title}")
            missing.setObjectName("mergedPaymentSourceMissing")
            layout.addWidget(missing)
        else:
            unsupported = QLabel("当前附件不是可直接合并的图片")
            unsupported.setObjectName("mergedPaymentSourceUnsupported")
            unsupported.setWordWrap(True)
            layout.addWidget(unsupported)
        return card

    def _latest_usable_merged_payment(
        self, attachments: list[Attachment], payment_material_type_id: int | None
    ) -> Attachment | None:
        if payment_material_type_id is None:
            return None
        for attachment in reversed(attachments):
            if (
                is_merged_payment_screenshot(
                    attachment, payment_material_type_id=payment_material_type_id
                )
                and self._get_attachment_display_path(attachment.id) is not None
            ):
                return attachment
        return None

    def _build_attachment_grid(self, attachments: list[Attachment]) -> QWidget:
        """Build the current material's compact, wrapping attachment cards."""
        grid_widget = QWidget()
        grid_widget.setObjectName("attachmentGrid")
        layout = QGridLayout(grid_widget)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        for index, attachment in enumerate(attachments):
            layout.addWidget(
                self._build_attachment_card(attachment),
                index // _ATTACHMENT_CARDS_PER_ROW,
                index % _ATTACHMENT_CARDS_PER_ROW,
            )
        return grid_widget

    def _build_attachment_card(self, attachment: Attachment) -> QFrame:
        """Render an attachment using only its existing stored archive file."""
        card = QFrame()
        card.setObjectName("attachmentCard")
        card.setFixedWidth(250)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        attachment_id = attachment.id
        stored_filename = attachment.stored_filename
        is_derived = attachment.is_derived
        display_name = (
            f"{stored_filename}\uff08\u5408\u5e76\u63d0\u4ea4\u6587\u4ef6\uff09"
            if is_derived
            else stored_filename
        )
        attachment_path = self._get_attachment_display_path(attachment_id)
        if attachment_path is None:
            missing_label = QLabel("\u6587\u4ef6\u7f3a\u5931")
            missing_label.setObjectName("attachmentMissingFile")
            layout.addWidget(missing_label)
        else:
            has_thumbnail = self._add_image_thumbnail(
                layout, attachment_id, attachment_path, stored_filename
            )
            if not has_thumbnail and Path(stored_filename).suffix.lower() == ".pdf":
                pdf_label = QLabel("PDF")
                pdf_label.setObjectName("attachmentPdfBadge")
                layout.addWidget(pdf_label, 0, Qt.AlignmentFlag.AlignLeft)
                layout.addWidget(
                    QLabel(self._format_file_size(attachment.file_size))
                )
            elif not has_thumbnail:
                file_label = QLabel("\u6587\u4ef6")
                file_label.setObjectName("attachmentFileBadge")
                layout.addWidget(file_label, 0, Qt.AlignmentFlag.AlignLeft)

        filename_label = QLabel(display_name)
        filename_label.setObjectName("attachmentFilename")
        filename_label.setWordWrap(True)
        filename_label.setToolTip(display_name)
        layout.addWidget(filename_label)
        layout.addStretch()
        layout.addWidget(self._build_attachment_actions(attachment_id))
        return card

    def _get_attachment_display_path(self, attachment_id: int) -> Path | None:
        if self._attachment_service is None:
            return None
        try:
            path = self._attachment_service.get_attachment_path(attachment_id)
        except (AttachmentNotFoundError, OSError, ValueError):
            logger.warning("Could not resolve attachment %s for display", attachment_id)
            return None
        return path if path.is_file() else None

    def _add_image_thumbnail(
        self,
        layout: QVBoxLayout,
        attachment_id: int,
        attachment_path: Path,
        stored_filename: str,
    ) -> bool:
        if Path(stored_filename).suffix.lower() not in _IMAGE_ATTACHMENT_EXTENSIONS:
            return False
        pixmap = QPixmap(str(attachment_path))
        if pixmap.isNull():
            return False
        scaled = pixmap.scaled(
            _THUMBNAIL_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        thumbnail_button = QPushButton()
        thumbnail_button.setObjectName("attachmentThumbnail")
        thumbnail_button.setAccessibleName(f"\u6253\u5f00\u56fe\u7247 {stored_filename}")
        thumbnail_button.setToolTip("\u70b9\u51fb\u4f7f\u7528\u7cfb\u7edf\u9ed8\u8ba4\u7a0b\u5e8f\u6253\u5f00\u539f\u56fe")
        thumbnail_button.setIcon(QIcon(scaled))
        thumbnail_button.setIconSize(scaled.size())
        thumbnail_button.setFixedSize(_THUMBNAIL_SIZE)
        thumbnail_button.clicked.connect(
            lambda _checked=False: self._open_attachment(attachment_id)
        )
        layout.addWidget(thumbnail_button, 0, Qt.AlignmentFlag.AlignLeft)
        return True

    @staticmethod
    def _format_file_size(file_size: int) -> str:
        if file_size < 1024:
            return f"{file_size} B"
        if file_size < 1024 * 1024:
            return f"{file_size / 1024:.1f} KB"
        return f"{file_size / (1024 * 1024):.1f} MB"

    def _build_attachment_actions(self, attachment_id: int) -> QWidget:
        widget = QWidget()
        widget.setObjectName("attachmentActions")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        open_button = QPushButton("\u6253\u5f00")
        open_button.clicked.connect(
            lambda _checked=False: self._open_attachment(attachment_id)
        )
        layout.addWidget(open_button)
        open_folder_button = QPushButton("\u6253\u5f00\u6240\u5728\u6587\u4ef6\u5939")
        open_folder_button.clicked.connect(
            lambda _checked=False: self._open_attachment_folder(attachment_id)
        )
        layout.addWidget(open_folder_button)
        remove_button = QPushButton("\u5220\u9664")
        remove_button.setObjectName("dangerButton")
        remove_button.clicked.connect(
            lambda _checked=False: self._remove_attachment(attachment_id)
        )
        layout.addWidget(remove_button)
        return widget

    def _open_attachment(self, attachment_id: int) -> None:
        self._run_attachment_desktop_action(attachment_id, open_folder=False)

    def _open_attachment_folder(self, attachment_id: int) -> None:
        self._run_attachment_desktop_action(attachment_id, open_folder=True)

    def _run_attachment_desktop_action(
        self, attachment_id: int, *, open_folder: bool
    ) -> None:
        if self._attachment_service is None:
            QMessageBox.warning(self, "无法打开附件", "附件服务当前不可用。")
            return
        try:
            path = self._attachment_service.get_attachment_path(attachment_id)
            if open_folder:
                self._desktop_integration_service.open_folder(path.parent)
            else:
                self._desktop_integration_service.open_file(path)
        except AttachmentNotFoundError:
            QMessageBox.warning(self, "无法打开附件", "附件记录不存在或已被删除。")
        except FileNotFoundError:
            QMessageBox.warning(self, "无法打开附件", "附件文件不存在或已被移动。")
        except (DesktopIntegrationError, OSError, ValueError):
            logger.exception("Failed to open attachment %s", attachment_id)
            QMessageBox.warning(self, "无法打开附件", "打开附件失败，请稍后重试。")
        except Exception:
            logger.exception("Unexpected failure opening attachment %s", attachment_id)
            QMessageBox.warning(self, "无法打开附件", "打开附件失败，请稍后重试。")

    def _remove_attachment(self, attachment_id: int) -> None:
        if self._attachment_service is None:
            QMessageBox.warning(self, "无法删除附件", "附件服务当前不可用。")
            return
        confirmed = QMessageBox.question(
            self,
            "删除附件",
            "确定删除这个附件吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        try:
            self._attachment_service.remove_attachment(attachment_id)
            if hasattr(self, "_current_item_detail_id"):
                self._populate_item_detail(self._current_item_detail_id)
        except AttachmentNotFoundError:
            QMessageBox.warning(self, "无法删除附件", "附件记录不存在或已被删除。")
        except (AttachmentServiceError, OSError, SQLAlchemyError):
            logger.exception("Failed to remove attachment %s", attachment_id)
            QMessageBox.warning(self, "无法删除附件", "删除附件失败，请稍后重试。")
        except Exception:
            logger.exception("Unexpected failure removing attachment %s", attachment_id)
            QMessageBox.warning(self, "无法删除附件", "删除附件失败，请稍后重试。")

    def _delete_current_item(self) -> None:
        if self._item_service is None or not hasattr(self, "_current_item_detail_id"):
            return
        item_id = self._current_item_detail_id
        attachment_count = 0
        if self._attachment_service is not None:
            try:
                attachment_count = len(self._attachment_service.list_attachments(item_id))
            except (AttachmentServiceError, ItemNotFoundError, SQLAlchemyError):
                logger.exception("Failed to inspect attachments before deleting item %s", item_id)
                QMessageBox.warning(self, "无法删除物品", "无法读取物品附件，请刷新后重试。")
                return

        message = "确定删除这个物品吗？"
        if attachment_count:
            message = (
                f"该物品包含 {attachment_count} 个附件。删除后附件将移动到应用回收目录，"
                "不会直接永久删除。\n\n确定删除这个物品吗？"
            )
        confirmed = QMessageBox.question(
            self,
            "删除物品",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        try:
            self._item_service.delete_item(item_id)
        except (ItemServiceError, OSError, SQLAlchemyError) as error:
            logger.exception("Failed to delete item %s", item_id)
            QMessageBox.warning(self, "无法删除物品", str(error))
            return
        self.refresh_all_items()
        self.refresh_pending_materials()
        self.refresh_dashboard()
        self.refresh_batch_list()
        self._refresh_current_batch_detail()
        self._show_all_items()

    def _generate_merged_payment_screenshot(self) -> None:
        if (
            self._payment_screenshot_merge_service is None
            or not hasattr(self, "_current_item_detail_id")
        ):
            return
        try:
            self._payment_screenshot_merge_service.generate(
                self._current_item_detail_id
            )
            self._populate_item_detail(self._current_item_detail_id)
        except PaymentScreenshotMergeError as error:
            QMessageBox.warning(self, "无法生成合并支付截图", str(error))
        except Exception:
            logger.exception(
                "Failed to generate merged payment screenshot for item %s",
                self._current_item_detail_id,
            )
            QMessageBox.warning(
                self,
                "无法生成合并支付截图",
                "生成合并支付截图失败，请确认截图文件可访问后重试。",
            )

    def _export_submission_materials(self) -> None:
        if (
            self._export_service is None
            or not hasattr(self, "_current_item_detail_id")
        ):
            QMessageBox.warning(self, "无法导出提交材料", "导出服务当前不可用。")
            return

        destination = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not destination:
            return

        try:
            result = self._export_service.export_item(
                self._current_item_detail_id, Path(destination)
            )
        except ExportTargetExistsError:
            QMessageBox.warning(
                self,
                "无法导出提交材料",
                "目标导出目录已存在，请选择其他目录或先处理旧导出结果。",
            )
        except SubmissionMaterialsIncompleteError as error:
            QMessageBox.warning(
                self,
                "无法导出提交材料",
                "提交材料未完整，缺少："
                + "、".join(error.missing_material_names),
            )
        except (ExportServiceError, OSError, SQLAlchemyError):
            logger.exception(
                "Failed to export submission materials for item %s",
                self._current_item_detail_id,
            )
            QMessageBox.warning(
                self, "无法导出提交材料", "导出失败，请确认附件可访问后重试。"
            )
        except Exception:
            logger.exception(
                "Unexpected submission export failure for item %s",
                self._current_item_detail_id,
            )
            QMessageBox.warning(self, "无法导出提交材料", "导出失败，请稍后重试。")
        else:
            QMessageBox.information(
                self,
                "导出完成",
                f"提交材料导出成功。\n已导出到：{result.output_directory}",
            )

    def _select_and_add_attachment(
        self, item_id: int, material_type_id: int
    ) -> None:
        if self._attachment_service is None:
            QMessageBox.warning(self, "无法添加附件", "附件服务当前不可用。")
            return

        source_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择附件",
            "",
            "支持的文件 (*.jpg *.jpeg *.png *.pdf)",
        )
        if not source_path:
            return

        try:
            self._attachment_service.add_attachment(
                item_id=item_id,
                material_type_id=material_type_id,
                source_path=Path(source_path),
            )
            self._populate_item_detail(item_id)
        except DuplicateAttachmentError:
            QMessageBox.warning(
                self, "无法添加附件", "该文件已经添加到这个报销物品。"
            )
        except ItemNotFoundError:
            QMessageBox.warning(
                self, "无法添加附件", "当前报销物品不存在或已失效。"
            )
        except MaterialRequirementNotFoundError:
            QMessageBox.warning(
                self, "无法添加附件", "当前材料要求已失效，请刷新后重试。"
            )
        except (AttachmentServiceError, OSError, SQLAlchemyError):
            logger.exception("Failed to add attachment to item %s", item_id)
            QMessageBox.warning(
                self, "无法添加附件", "添加附件失败，请确认文件可访问后重试。"
            )
        except Exception:
            logger.exception("Unexpected attachment upload failure for item %s", item_id)
            QMessageBox.warning(
                self, "无法添加附件", "添加附件失败，请稍后重试。"
            )

    def _show_all_items(self) -> None:
        self.navigation.setCurrentRow(ALL_ITEMS_PAGE_INDEX)
        self.pages.setCurrentIndex(ALL_ITEMS_PAGE_INDEX)

    def _show_item_detail_return_page(self) -> None:
        page_index = getattr(
            self, "_item_detail_return_page_index", ALL_ITEMS_PAGE_INDEX
        )
        self.navigation.setCurrentRow(page_index)
        self.pages.setCurrentIndex(page_index)

    def refresh_batch_list(self) -> None:
        """Refresh displayed batch summaries through the application service."""
        self.batch_table.setRowCount(0)
        self._batch_entries: dict[int, BatchListEntry] = {}
        if self._batch_service is not None:
            for entry in self._batch_service.list_batch_entries():
                self._batch_entries[entry.id] = entry
                self._append_batch_entry(entry)
        has_entries = self.batch_table.rowCount() > 0
        self.batch_table.setVisible(has_entries)
        self.batch_empty_state.setVisible(not has_entries)

    def _append_batch_entry(self, entry: BatchListEntry) -> None:
        row = self.batch_table.rowCount()
        self.batch_table.insertRow(row)
        values = (
            entry.name,
            entry.created_at.strftime("%Y-%m-%d"),
            str(entry.item_count),
            self._format_cents(entry.total_amount_cents),
        )
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 0:
                item.setData(Qt.ItemDataRole.UserRole, entry.id)
                font = QFont(item.font())
                font.setBold(True)
                item.setFont(font)
            elif column in (2, 3):
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            else:
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.batch_table.setItem(row, column, item)

    def _build_batch_detail_page_legacy(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        self.back_to_batch_list_button = QPushButton("返回批次列表")
        self.back_to_batch_list_button.clicked.connect(self._show_batch_list)
        header.addWidget(self.back_to_batch_list_button)
        header.addStretch()
        self.new_item_button = QPushButton("新增物品")
        self.new_item_button.clicked.connect(self._open_new_item_dialog)
        header.addWidget(self.new_item_button)
        self.export_batch_materials_button = QPushButton("导出报销材料")
        self.export_batch_materials_button.clicked.connect(
            self._export_batch_materials
        )
        self.export_batch_materials_button.setEnabled(self._export_service is not None)
        header.addWidget(self.export_batch_materials_button)
        layout.addLayout(header)

        self.batch_detail_name_label = QLabel()
        self.batch_detail_total_amount_label = QLabel()
        self.batch_detail_item_count_label = QLabel()
        layout.addWidget(self.batch_detail_name_label)
        layout.addWidget(self.batch_detail_total_amount_label)
        layout.addWidget(self.batch_detail_item_count_label)

        self.batch_detail_table = QTableWidget(0, 4)
        self.batch_detail_table.setHorizontalHeaderLabels(
            ("物品名称", "金额", "材料完整度", "缺失材料")
        )
        self.batch_detail_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.batch_detail_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.batch_detail_table.setAlternatingRowColors(True)
        self.batch_detail_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.batch_detail_table, 1)
        return page

    def _build_batch_detail_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("batchDetailPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        self.back_to_batch_list_button = QPushButton("\u2190 \u62a5\u9500\u6279\u6b21")
        self.back_to_batch_list_button.setObjectName("batchDetailBackButton")
        self.back_to_batch_list_button.clicked.connect(self._show_batch_list)
        layout.addWidget(self.back_to_batch_list_button, 0, Qt.AlignmentFlag.AlignLeft)

        header = QHBoxLayout()
        header.setSpacing(12)
        batch_information = QVBoxLayout()
        batch_information.setSpacing(4)
        self.batch_detail_name_label = QLabel()
        self.batch_detail_name_label.setObjectName("pageTitle")
        batch_information.addWidget(self.batch_detail_name_label)
        self.batch_detail_summary_label = QLabel()
        self.batch_detail_summary_label.setObjectName("batchDetailSummary")
        batch_information.addWidget(self.batch_detail_summary_label)
        # Retain these public labels as compatibility state for existing callers;
        # the combined summary above is the only visible batch metadata.
        self.batch_detail_total_amount_label = QLabel()
        self.batch_detail_item_count_label = QLabel()
        header.addLayout(batch_information)
        header.addStretch()
        self.new_item_button = QPushButton("+ \u65b0\u589e\u7269\u54c1")
        self.new_item_button.setObjectName("primaryButton")
        self.new_item_button.clicked.connect(self._open_new_item_dialog)
        header.addWidget(self.new_item_button)
        self.export_batch_materials_button = QPushButton("\u5bfc\u51fa\u62a5\u9500\u6750\u6599")
        self.export_batch_materials_button.clicked.connect(
            self._export_batch_materials
        )
        self.export_batch_materials_button.setEnabled(self._export_service is not None)
        header.addWidget(self.export_batch_materials_button)
        self.delete_batch_button = QPushButton("删除批次")
        self.delete_batch_button.setObjectName("dangerButton")
        self.delete_batch_button.clicked.connect(self._delete_current_batch)
        header.addWidget(self.delete_batch_button)
        layout.addLayout(header)

        items_title = QLabel("\u7269\u54c1")
        items_title.setObjectName("sectionTitle")
        layout.addWidget(items_title)

        self.batch_detail_table = QTableWidget(0, 4)
        self.batch_detail_table.setObjectName("batchDetailTable")
        self.batch_detail_table.setHorizontalHeaderLabels(
            ("\u7269\u54c1\u540d\u79f0", "\u91d1\u989d", "\u6750\u6599\u5b8c\u6574\u5ea6", "\u7f3a\u5931\u6750\u6599")
        )
        self.batch_detail_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.batch_detail_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.batch_detail_table.setAlternatingRowColors(True)
        self.batch_detail_table.setShowGrid(False)
        self.batch_detail_table.verticalHeader().setVisible(False)
        self.batch_detail_table.verticalHeader().setDefaultSectionSize(42)
        header_view = self.batch_detail_table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            header_view.setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.batch_detail_table.cellDoubleClicked.connect(
            self._open_batch_detail_item
        )
        layout.addWidget(self.batch_detail_table, 1)

        self.batch_detail_empty_state = QFrame()
        self.batch_detail_empty_state.setObjectName("batchDetailEmptyState")
        empty_layout = QVBoxLayout(self.batch_detail_empty_state)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.setSpacing(8)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_title = QLabel("\u8fd9\u4e2a\u6279\u6b21\u8fd8\u6ca1\u6709\u7269\u54c1")
        empty_title.setObjectName("emptyStateTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_title)
        empty_description = QLabel("\u6dfb\u52a0\u7b2c\u4e00\u4e2a\u62a5\u9500\u7269\u54c1\u5f00\u59cb\u6574\u7406\u6750\u6599\u3002")
        empty_description.setObjectName("emptyStateDescription")
        empty_description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_description)
        self.empty_new_item_button = QPushButton("+ \u65b0\u589e\u7269\u54c1")
        self.empty_new_item_button.setObjectName("primaryButton")
        self.empty_new_item_button.clicked.connect(self._open_new_item_dialog)
        empty_layout.addWidget(
            self.empty_new_item_button, 0, Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(self.batch_detail_empty_state, 1)
        return page

    def _open_batch_detail(self, row: int, _column: int) -> None:
        batch_id_item = self.batch_table.item(row, 0)
        if batch_id_item is None:
            return
        batch_id = batch_id_item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(batch_id, int):
            return
        entry = self._batch_entries.get(batch_id)
        if entry is None:
            return
        self._populate_batch_detail(entry)
        self.pages.setCurrentIndex(BATCH_DETAIL_PAGE_INDEX)

    def _populate_batch_detail_legacy(self, entry: BatchListEntry) -> None:
        self._current_batch_entry = entry
        self.batch_detail_name_label.setText(entry.name)
        self.batch_detail_total_amount_label.setText(
            f"\u603b\u91d1\u989d\uff1a{self._format_cents(entry.total_amount_cents)}"
        )
        self.batch_detail_item_count_label.setText(f"\u7269\u54c1\u6570\u91cf\uff1a{entry.item_count}")
        self.batch_detail_table.setRowCount(0)
        if self._item_service is None or self._completeness_service is None:
            return

        for item in self._item_service.list_items_by_batch(entry.id):
            completeness = self._completeness_service.calculate(item.id)
            missing_materials = "\u3001".join(
                material.name for material in completeness.missing
            )
            row = self.batch_detail_table.rowCount()
            self.batch_detail_table.insertRow(row)
            values = (
                item.name,
                self._format_cents(item.total_amount_cents),
                f"{completeness.completed_count}/{completeness.required_count}",
                missing_materials or "\u2014",
            )
            for column, value in enumerate(values):
                self.batch_detail_table.setItem(
                    row, column, QTableWidgetItem(value)
                )

    def _populate_batch_detail(self, entry: BatchListEntry) -> None:
        self._current_batch_entry = entry
        self.batch_detail_name_label.setText(entry.name)
        self.batch_detail_summary_label.setText(
            f"{entry.item_count} \u4e2a\u7269\u54c1 \u00b7 {self._format_cents(entry.total_amount_cents)}"
        )
        self.batch_detail_total_amount_label.setText(
            f"\u603b\u91d1\u989d\uff1a{self._format_cents(entry.total_amount_cents)}"
        )
        self.batch_detail_item_count_label.setText(
            f"\u7269\u54c1\u6570\u91cf\uff1a{entry.item_count}"
        )
        self.batch_detail_table.setRowCount(0)
        if self._item_service is not None and self._completeness_service is not None:
            for item in self._item_service.list_items_by_batch(entry.id):
                completeness = self._completeness_service.calculate(item.id)
                missing_materials = "\u3001".join(
                    material.name for material in completeness.missing
                )
                row = self.batch_detail_table.rowCount()
                self.batch_detail_table.insertRow(row)
                values = (
                    item.name,
                    self._format_cents(item.total_amount_cents),
                    f"{completeness.completed_count}/{completeness.required_count}",
                    missing_materials or "\u6750\u6599\u5b8c\u6574",
                )
                for column, value in enumerate(values):
                    table_item = QTableWidgetItem(value)
                    if column == 0:
                        table_item.setData(Qt.ItemDataRole.UserRole, item.id)
                        font = QFont(table_item.font())
                        font.setBold(True)
                        table_item.setFont(font)
                    elif column == 1:
                        table_item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight
                            | Qt.AlignmentFlag.AlignVCenter
                        )
                    elif column == 2:
                        table_item.setTextAlignment(
                            Qt.AlignmentFlag.AlignCenter
                            | Qt.AlignmentFlag.AlignVCenter
                        )
                    if column == 3 and missing_materials:
                        table_item.setForeground(QColor("#8a4c08"))
                    self.batch_detail_table.setItem(row, column, table_item)

        has_items = self.batch_detail_table.rowCount() > 0
        self.batch_detail_table.setVisible(has_items)
        self.batch_detail_empty_state.setVisible(not has_items)

    def _open_batch_detail_item(self, row: int, _column: int) -> None:
        self._open_item_detail_from_table(
            self.batch_detail_table, row, BATCH_DETAIL_PAGE_INDEX
        )

    def _delete_current_batch(self) -> None:
        if self._batch_service is None or not hasattr(self, "_current_batch_entry"):
            return
        entry = self._current_batch_entry
        current_entry = next(
            (
                value
                for value in self._batch_service.list_batch_entries()
                if value.id == entry.id
            ),
            None,
        )
        if current_entry is None:
            QMessageBox.warning(self, "无法删除批次", "当前报销批次不存在或已被删除。")
            return
        if current_entry.item_count:
            QMessageBox.warning(
                self,
                "无法删除批次",
                f"该批次仍包含 {current_entry.item_count} 个物品，请先删除或转移这些物品后再删除批次。",
            )
            return
        confirmed = QMessageBox.question(
            self,
            "删除批次",
            "确定删除这个报销批次吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        try:
            self._batch_service.delete_batch(current_entry.id)
        except (ValueError, LookupError, SQLAlchemyError) as error:
            logger.exception("Failed to delete batch %s", current_entry.id)
            QMessageBox.warning(self, "无法删除批次", str(error))
            return
        self.refresh_batch_list()
        self.refresh_dashboard()
        self.refresh_pending_materials()
        del self._current_batch_entry
        self._show_batch_list()

    def _export_batch_materials(self) -> None:
        if self._export_service is None or not hasattr(self, "_current_batch_entry"):
            QMessageBox.warning(self, "无法导出报销材料", "导出服务当前不可用。")
            return

        export_format = self._choose_batch_export_format()
        if export_format is None:
            return
        destination = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not destination:
            return

        batch_id = self._current_batch_entry.id
        try:
            result = self._export_batch_with_format(
                batch_id, Path(destination), export_format
            )
        except BatchSubmissionMaterialsIncompleteError as error:
            details = "\n\n".join(
                f"{item.item_name}\n缺：{'、'.join(item.missing_material_names)}"
                for item in error.incomplete_items
            )
            if not self._confirm_force_batch_export(details):
                return
            try:
                result = self._export_batch_with_format(
                    batch_id, Path(destination), export_format, force=True
                )
            except EmptyBatchExportError:
                QMessageBox.warning(
                    self, "无法导出报销材料", "当前批次没有可导出的物品。"
                )
                return
            except ExportTargetExistsError:
                QMessageBox.warning(
                    self,
                    "无法导出报销材料",
                    "目标批次导出目录已存在，请选择其他目录或先处理旧导出结果。",
                )
                return
            except (ExportServiceError, OSError, SQLAlchemyError):
                logger.exception("Failed to force-export reimbursement batch %s", batch_id)
                QMessageBox.warning(
                    self, "无法导出报销材料", "导出失败，请确认附件可访问后重试。"
                )
                return
            except Exception:
                logger.exception("Unexpected force-export failure for batch %s", batch_id)
                QMessageBox.warning(self, "无法导出报销材料", "导出失败，请稍后重试。")
                return
            self._show_batch_export_success(result)
            return
        except EmptyBatchExportError:
            QMessageBox.warning(
                self, "无法导出报销材料", "当前批次没有可导出的物品。"
            )
        except ExportTargetExistsError:
            QMessageBox.warning(
                self,
                "无法导出报销材料",
                "目标批次导出目录已存在，请选择其他目录或先处理旧导出结果。",
            )
        except (ExportServiceError, OSError, SQLAlchemyError):
            logger.exception("Failed to export reimbursement batch %s", batch_id)
            QMessageBox.warning(
                self, "无法导出报销材料", "导出失败，请确认附件可访问后重试。"
            )
        except Exception:
            logger.exception("Unexpected batch export failure for batch %s", batch_id)
            QMessageBox.warning(self, "无法导出报销材料", "导出失败，请稍后重试。")
        else:
            self._show_batch_export_success(result)

    def _choose_batch_export_format(self) -> str | None:
        dialog = QMessageBox(self)
        _configure_message_dialog(dialog)
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setWindowTitle("选择导出格式")
        dialog.setText("请选择报销材料的导出格式。")
        directory_button = dialog.addButton("导出文件夹", QMessageBox.ButtonRole.AcceptRole)
        zip_button = dialog.addButton("导出 ZIP", QMessageBox.ButtonRole.ActionRole)
        cancel_button = dialog.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        directory_button.setObjectName("primaryButton")
        zip_button.setObjectName("secondaryButton")
        cancel_button.setObjectName("secondaryButton")
        dialog.setDefaultButton(directory_button)
        dialog.exec()
        if dialog.clickedButton() is directory_button:
            return "directory"
        if dialog.clickedButton() is zip_button:
            return "zip"
        return None

    def _export_batch_with_format(
        self, batch_id: int, destination: Path, export_format: str, *, force: bool = False
    ) -> BatchExportResult:
        if export_format == "zip":
            return self._export_service.export_batch_zip(  # type: ignore[union-attr]
                batch_id, destination, force=force
            )
        return self._export_service.export_batch(  # type: ignore[union-attr]
            batch_id, destination, force=force
        )

    def _show_batch_export_success(self, result: BatchExportResult) -> None:
        export_label = "批次 ZIP 导出成功。" if result.export_format == "zip" else "批次报销材料导出成功。"
        if result.forced:
            QMessageBox.information(
                self,
                "强制导出完成",
                f"强制导出完成。部分物品材料不完整，请查看导出结果.txt。\n{export_label}\n"
                f"已导出到：{result.output_path}\n"
                f"已导出 {result.item_count} 个物品，共 {result.file_count} 个文件。",
            )
            return
        QMessageBox.information(
            self,
            "导出完成",
            f"{export_label}\n"
            f"已导出到：{result.output_path}\n"
            f"已导出 {result.item_count} 个物品，共 {result.file_count} 个文件。",
        )

    def _confirm_force_batch_export(self, details: str) -> bool:
        dialog = QMessageBox(self)
        _configure_message_dialog(dialog)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("提交材料不完整")
        dialog.setText(f"以下物品提交材料不完整：\n\n{details}")
        cancel_button = dialog.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        force_button = dialog.addButton("强制导出", QMessageBox.ButtonRole.AcceptRole)
        force_button.setObjectName("dangerButton")
        dialog.setDefaultButton(cancel_button)
        dialog.exec()
        return dialog.clickedButton() is force_button

    def _open_new_item_dialog(self) -> None:
        if (
            self._item_service is None
            or self._template_service is None
            or not hasattr(self, "_current_batch_entry")
        ):
            return
        templates = self._template_service.list_templates()
        if not templates:
            QMessageBox.warning(self, "\u65e0\u6cd5\u521b\u5efa\u7269\u54c1", "\u8bf7\u5148\u521b\u5efa\u81f3\u5c11\u4e00\u4e2a\u6750\u6599\u6a21\u677f\u3002")
            return
        dialog = NewItemDialog(self._current_batch_entry.name, templates, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            existing_items = self._item_service.list_items_by_batch(
                self._current_batch_entry.id
            )
            sequence_number = max(
                (item.sequence_number for item in existing_items), default=0
            ) + 1
            self._item_service.create_item(
                batch_id=self._current_batch_entry.id,
                template_id=dialog.template_id(),
                sequence_number=sequence_number,
                name=dialog.name_input.text(),
                purchase_date=dialog.purchase_date(),
                platform=dialog.platform_input.text(),
                merchant=dialog.merchant_input.text(),
                order_number=dialog.order_number_input.text(),
                total_amount_cents=dialog.total_amount_cents(),
                notes=dialog.notes_input.toPlainText(),
            )
            self.refresh_batch_list()
            self._refresh_current_batch_detail()
        except (ItemServiceError, TemplateServiceError, ValueError) as error:
            QMessageBox.warning(self, "\u65e0\u6cd5\u521b\u5efa\u7269\u54c1", str(error))
        except SQLAlchemyError:
            logger.exception("Failed to create reimbursement item")
            QMessageBox.critical(
                self, "\u65e0\u6cd5\u521b\u5efa\u7269\u54c1", "\u4fdd\u5b58\u7269\u54c1\u65f6\u53d1\u751f\u6570\u636e\u5e93\u9519\u8bef\u3002"
            )

    def _refresh_current_batch_detail(self) -> None:
        if self._batch_service is None or not hasattr(self, "_current_batch_entry"):
            return
        current_id = self._current_batch_entry.id
        for entry in self._batch_service.list_batch_entries():
            if entry.id == current_id:
                self._populate_batch_detail(entry)
                return

    def _show_batch_list(self) -> None:
        self.navigation.setCurrentRow(BATCH_LIST_PAGE_INDEX)
        self.pages.setCurrentIndex(BATCH_LIST_PAGE_INDEX)

    def _open_new_batch_dialog(self) -> None:
        if self._batch_service is None:
            return
        dialog = NewBatchDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._batch_service.create_batch(
                name=dialog.name_input.text(),
                reimburser=dialog.reimburser_input.text(),
                project_name=dialog.project_name_input.text(),
                notes=dialog.notes_input.toPlainText(),
            )
            self.refresh_batch_list()
        except ValueError as error:
            QMessageBox.warning(self, "\u65e0\u6cd5\u521b\u5efa\u6279\u6b21", str(error))
        except SQLAlchemyError:
            logger.exception("Failed to create reimbursement batch")
            QMessageBox.critical(self, "\u65e0\u6cd5\u521b\u5efa\u6279\u6b21", "\u4fdd\u5b58\u6279\u6b21\u65f6\u53d1\u751f\u6570\u636e\u5e93\u9519\u8bef\u3002")

    @staticmethod
    def _format_cents(amount_cents: int) -> str:
        return f"\u00a5{amount_cents // 100}.{amount_cents % 100:02d}"

    def _build_dashboard_page(self) -> QWidget:
        """Build the service-backed reimbursement workbench without business logic."""
        page = QWidget()
        page.setObjectName("dashboardPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("\u62a5\u9500\u6982\u89c8")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        summary_layout = QHBoxLayout()
        summary_layout.setSpacing(12)
        summary_values = (
            ("\u5f85\u8865\u6750\u6599", self._dashboard_data.incomplete_count),
            ("\u53ef\u63d0\u4ea4", self._dashboard_data.complete_count),
            ("\u5df2\u63d0\u4ea4", self._dashboard_data.submitted_count),
            ("\u5df2\u62a5\u9500", self._dashboard_data.reimbursed_count),
        )
        self.dashboard_summary_labels: dict[str, QLabel] = {}
        for label, value in summary_values:
            card = QFrame()
            card.setObjectName("dashboardStatCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 12, 16, 12)
            card_layout.setSpacing(2)

            value_label = QLabel(str(value))
            value_label.setObjectName("dashboardStatValue")
            title_label = QLabel(label)
            title_label.setObjectName("dashboardStatTitle")
            card_layout.addWidget(value_label)
            card_layout.addWidget(title_label)
            self.dashboard_summary_labels[label] = value_label
            summary_layout.addWidget(card, 1)
        layout.addLayout(summary_layout)

        pending_title = QLabel("\u5f85\u5904\u7406")
        pending_title.setObjectName("sectionTitle")
        layout.addWidget(pending_title)

        self.dashboard_pending_scroll = QScrollArea()
        self.dashboard_pending_scroll.setObjectName("dashboardPendingArea")
        self.dashboard_pending_scroll.setWidgetResizable(True)
        self.dashboard_pending_container = QWidget()
        pending_layout = QVBoxLayout(self.dashboard_pending_container)
        self.dashboard_pending_layout = pending_layout
        pending_layout.setContentsMargins(0, 0, 0, 0)
        pending_layout.setSpacing(8)

        self.dashboard_pending_items: list[QFrame] = []
        if self._dashboard_data.incomplete_items:
            for item in self._dashboard_data.incomplete_items:
                row = self._build_dashboard_pending_item(item)
                self.dashboard_pending_items.append(row)
                pending_layout.addWidget(row)
            pending_layout.addStretch()
            self.dashboard_empty_state = QLabel()
            self.dashboard_empty_state.hide()
        else:
            self.dashboard_empty_state = QLabel(
                "\u5f53\u524d\u6ca1\u6709\u5f85\u5904\u7406\u7684\u62a5\u9500\u6750\u6599\u3002\n"
                "\u6240\u6709\u7269\u54c1\u7684\u63d0\u4ea4\u6750\u6599\u90fd\u5df2\u51c6\u5907\u5b8c\u6210\u3002"
            )
            self.dashboard_empty_state.setObjectName("dashboardEmptyState")
            self.dashboard_empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pending_layout.addWidget(self.dashboard_empty_state)
            pending_layout.addStretch()
        self.dashboard_pending_scroll.setWidget(self.dashboard_pending_container)
        layout.addWidget(self.dashboard_pending_scroll, 1)
        return page

    def refresh_dashboard(self) -> None:
        """Refresh the Dashboard after a local data-changing action."""
        if self._dashboard_service is None:
            return
        self._dashboard_data = self._dashboard_service.get_data()
        for label, value in (
            ("待补材料", self._dashboard_data.incomplete_count),
            ("可提交", self._dashboard_data.complete_count),
            ("已提交", self._dashboard_data.submitted_count),
            ("已报销", self._dashboard_data.reimbursed_count),
        ):
            self.dashboard_summary_labels[label].setText(str(value))
        while self.dashboard_pending_layout.count():
            child = self.dashboard_pending_layout.takeAt(0)
            if child.widget() is not None:
                child.widget().deleteLater()
        self.dashboard_pending_items = []
        if self._dashboard_data.incomplete_items:
            for item in self._dashboard_data.incomplete_items:
                row = self._build_dashboard_pending_item(item)
                self.dashboard_pending_items.append(row)
                self.dashboard_pending_layout.addWidget(row)
            self.dashboard_empty_state = QLabel()
            self.dashboard_empty_state.hide()
        else:
            self.dashboard_empty_state = QLabel("当前没有待处理的报销材料。")
            self.dashboard_empty_state.setObjectName("dashboardEmptyState")
            self.dashboard_empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.dashboard_pending_layout.addWidget(self.dashboard_empty_state)
        self.dashboard_pending_layout.addStretch()

    def _build_dashboard_pending_item(
        self, dashboard_item: IncompleteDashboardItem
    ) -> QFrame:
        """Render data already prepared by services for one incomplete Item."""
        row = QFrame()
        row.setObjectName("dashboardPendingItem")
        item_layout = QHBoxLayout(row)
        item_layout.setContentsMargins(16, 12, 16, 12)
        item_layout.setSpacing(16)

        identity_layout = QVBoxLayout()
        identity_layout.setSpacing(2)
        name = QLabel(dashboard_item.name)
        name.setObjectName("dashboardItemName")
        batch = QLabel(self._dashboard_batch_name(dashboard_item.item_id))
        batch.setObjectName("dashboardItemBatch")
        identity_layout.addWidget(name)
        identity_layout.addWidget(batch)
        item_layout.addLayout(identity_layout, 1)

        progress = QLabel(
            f"\u6750\u6599\u6536\u96c6 {dashboard_item.completed_count} / "
            f"{dashboard_item.required_count}"
        )
        progress.setObjectName("dashboardProgress")
        item_layout.addWidget(progress)

        submission = self._dashboard_submission_text(dashboard_item.item_id)
        if submission is not None:
            submission_label = QLabel(submission)
            submission_label.setObjectName("dashboardProgress")
            item_layout.addWidget(submission_label)

        missing = QLabel(f"\u7f3a\uff1a{'\u3001'.join(dashboard_item.missing_materials)}")
        missing.setObjectName("dashboardMissing")
        missing.setWordWrap(True)
        item_layout.addWidget(missing, 1)
        return row

    def _dashboard_batch_name(self, item_id: int) -> str:
        """Use injected public services when available; do not query repositories in UI."""
        if self._item_service is None or self._batch_service is None:
            return "\u6240\u5c5e\u6279\u6b21\uff1a\u2014"
        try:
            item = self._item_service.get_item(item_id)
            batches = {batch.id: batch.name for batch in self._batch_service.list_batches()}
        except (ItemServiceError, SQLAlchemyError):
            logger.exception("Failed to load Dashboard batch name")
            return "\u6240\u5c5e\u6279\u6b21\uff1a\u2014"
        return f"\u6240\u5c5e\u6279\u6b21\uff1a{batches.get(item.batch_id, '\u2014')}"

    def _dashboard_submission_text(self, item_id: int) -> str | None:
        """Reuse SubmissionReadinessService only when it was already injected."""
        if self._submission_readiness_service is None:
            return None
        try:
            readiness = self._submission_readiness_service.calculate(item_id)
        except (ItemNotFoundError, SQLAlchemyError):
            logger.exception("Failed to load Dashboard submission progress")
            return None
        return f"\u63d0\u4ea4\u6750\u6599 {readiness.completed_count} / {readiness.required_count}"

    @staticmethod
    def _build_placeholder_page(page_title: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        label = QLabel(f"{page_title}\n\n\u529f\u80fd\u5c06\u5728\u540e\u7eed\u4efb\u52a1\u4e2d\u5b9e\u73b0\u3002")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        return page
