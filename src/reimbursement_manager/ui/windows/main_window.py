from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QFontMetrics,
    QIcon,
    QPixmap,
)
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
    QLineEdit,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import SQLAlchemyError

from reimbursement_manager.database.models import Attachment, Item, MaterialType
from reimbursement_manager.domain import ReimbursementStatus, display_status
from reimbursement_manager.services.backup_service import BackupService
from reimbursement_manager.services.restore_service import (
    DatabaseReplacementError,
    InvalidBackupDatabaseError,
    RestoreService,
    RestoreServiceError,
    SafetyBackupError,
    UnknownSchemaRevisionError,
)
from reimbursement_manager.ui.theme import IOS_LIGHT_TOKENS, apply_light_theme

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
    SubmissionNotReadyError,
    WorkflowService,
    WorkflowServiceError,
)
from reimbursement_manager.services.payment_screenshot_merge_service import (
    PAYMENT_SCREENSHOT_CODE,
    is_merged_payment_screenshot,
)
from reimbursement_manager.ui.windows.update_dialog import UpdateContext, UpdateSection
from reimbursement_manager.version import __version__


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
    "incomplete": "待补材料",
    "pending_payment": "待生成凭证",
    "ready": "可提交",
    "submitted": "已提交",
    "reimbursed": "已报销",
    "archived": "已归档",
}

BATCH_STATUS_LABELS = {
    "collecting": "收集中",
    "submitted": "已提交",
    "reimbursed": "已报销",
    "archived": "已归档",
}

logger = logging.getLogger(__name__)


_IMAGE_ATTACHMENT_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png"})
_THUMBNAIL_SIZE = QSize(180, 120)


class MaterialDropSection(QFrame):
    """Accept local files dropped onto one material requirement section."""

    filesDropped = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setProperty("dropActive", False)

    @staticmethod
    def _local_paths(
        event: QDragEnterEvent | QDragMoveEvent | QDropEvent,
    ) -> tuple[Path, ...]:
        mime_data = event.mimeData()
        if not mime_data.hasUrls():
            return ()
        return tuple(
            Path(url.toLocalFile())
            for url in mime_data.urls()
            if url.isLocalFile() and url.toLocalFile()
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._local_paths(event):
            self._set_drop_active(True)
            event.acceptProposedAction()
            return
        self._set_drop_active(False)
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802
        self._set_drop_active(False)
        event.accept()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if self._local_paths(event):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = self._local_paths(event)
        self._set_drop_active(False)
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self.filesDropped.emit(paths)

    def _set_drop_active(self, active: bool) -> None:
        if self.property("dropActive") is active:
            return
        self.setProperty("dropActive", active)
        self.style().unpolish(self)
        self.style().polish(self)


class AttachmentFlowLayout(QLayout):
    """Wrap attachment cards without imposing a horizontal scroll bar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[object] = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(12)

    def addItem(self, item: object) -> None:  # noqa: N802 - Qt API name
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> object | None:  # noqa: N802 - Qt API name
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> object | None:  # noqa: N802 - Qt API name
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt API name
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt API name
        return self._layout_items(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - Qt API name
        super().setGeometry(rect)
        self._layout_items(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return QSize(0, self.heightForWidth(self.geometry().width()))

    def minimumSize(self) -> QSize:
        return QSize(0, 0)

    def _layout_items(self, rect: QRect, *, test_only: bool) -> int:
        x, y = rect.x(), rect.y()
        line_height = 0
        right = rect.right()
        for item in self._items:
            size = item.sizeHint()
            next_x = x + size.width()
            if line_height and next_x > right + 1:
                x = rect.x()
                y += line_height + self.spacing()
                next_x = x + size.width()
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(x, y, size.width(), size.height()))
            x = next_x + self.spacing()
            line_height = max(line_height, size.height())
        return y + line_height - rect.y()


class SidebarNavigation(QFrame):
    """Keep the existing page-index navigation API while presenting two groups."""

    currentRowChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("navigation")
        self._current_row = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self._primary_list = self._create_list("primaryNavigation")
        self._management_list = self._create_list("managementNavigation")
        layout.addWidget(self._primary_list)

        management_title = QLabel("管理")
        management_title.setObjectName("managementGroupTitle")
        self.management_group_title = management_title
        layout.addWidget(management_title)
        layout.addWidget(self._management_list)
        layout.addStretch()

        self._primary_list.currentRowChanged.connect(self._select_primary_row)
        self._management_list.currentRowChanged.connect(self._select_management_row)

    @staticmethod
    def _create_list(object_name: str) -> QListWidget:
        navigation_list = QListWidget()
        navigation_list.setObjectName(object_name)
        navigation_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        navigation_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        navigation_list.setSpacing(4)
        return navigation_list

    def addItem(self, item: QListWidgetItem) -> None:
        target = self._primary_list if self.count() < 4 else self._management_list
        target.addItem(item)
        if target is self._primary_list:
            # The primary group has four fixed navigation rows.  Its QSS item
            # margins make the viewport one pixel shorter than the content at
            # the previously allocated height; selecting row 3 then scrolls
            # row 0 out of view.  Reserve the group's own spacing so every
            # primary item stays inside the viewport for the window lifetime.
            target.setMinimumHeight(target.sizeHint().height() + target.spacing())

    def count(self) -> int:
        return self._primary_list.count() + self._management_list.count()

    def item(self, row: int) -> QListWidgetItem | None:
        if row < 0 or row >= self.count():
            return None
        if row < self._primary_list.count():
            return self._primary_list.item(row)
        return self._management_list.item(row - self._primary_list.count())

    def setIconSize(self, size: QSize) -> None:
        self._primary_list.setIconSize(size)
        self._management_list.setIconSize(size)

    def iconSize(self) -> QSize:
        return self._primary_list.iconSize()

    def currentRow(self) -> int:
        return self._current_row

    def setCurrentRow(self, row: int) -> None:
        if row < 0 or row >= self.count():
            return
        if row < self._primary_list.count():
            target_list = self._primary_list
            target_row = row
            other_list = self._management_list
        else:
            target_list = self._management_list
            target_row = row - self._primary_list.count()
            other_list = self._primary_list

        # A cleared list retains its current row.  Setting that same row again
        # does not emit QListWidget.currentRowChanged, so synchronize both
        # groups explicitly instead of relying on a later Qt signal.
        with QSignalBlocker(target_list), QSignalBlocker(other_list):
            other_list.clearSelection()
            target_list.setCurrentRow(target_row)
        self._set_current_row(row)

    def _select_primary_row(self, row: int) -> None:
        if row < 0:
            return
        with QSignalBlocker(self._management_list):
            self._management_list.clearSelection()
        self._set_current_row(row)

    def _select_management_row(self, row: int) -> None:
        if row < 0:
            return
        with QSignalBlocker(self._primary_list):
            self._primary_list.clearSelection()
        self._set_current_row(self._primary_list.count() + row)

    def _set_current_row(self, row: int) -> None:
        if self._current_row == row:
            return
        self._current_row = row
        self.currentRowChanged.emit(row)


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
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("例如：树莓派 Zero 2 W")
        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText("例如：23.45（留空为 0.00）")
        self.purchase_date_input = QLineEdit()
        self.purchase_date_input.setPlaceholderText("YYYY-MM-DD（可选）")
        self.platform_input = QLineEdit()
        self.platform_input.setPlaceholderText("淘宝 / 京东 / 官网")
        self.merchant_input = QLineEdit()
        self.merchant_input.setPlaceholderText("店铺或收款方")
        self.order_number_input = QLineEdit()
        self.order_number_input.setPlaceholderText("可选")
        self.template_input = QComboBox()
        for template in templates:
            self.template_input.addItem(template.name, template.id)
        self.batch_input = QLineEdit(batch_name)
        self.batch_input.setReadOnly(True)
        self.batch_input.setObjectName("readOnlyField")
        self.notes_input = QTextEdit()
        self.notes_input.setFixedHeight(64)
        self.notes_input.setPlaceholderText("可选")

        self._build_field_group(
            layout,
            "基本信息",
            (
                ("物品名称 *", self.name_input),
                ("金额", self.amount_input),
                ("购买日期", self.purchase_date_input),
            ),
        )
        self._build_field_group(
            layout,
            "采购信息",
            (
                ("平台", self.platform_input),
                ("商家", self.merchant_input),
                ("订单号", self.order_number_input),
            ),
        )
        self._build_field_group(
            layout,
            "归档设置",
            (
                ("模板 *", self.template_input),
                ("批次", self.batch_input),
                ("备注", self.notes_input),
            ),
        )

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        _configure_dialog_buttons(self.buttons, save_text="创建物品")
        self.buttons.rejected.connect(self.reject)
        self.buttons.accepted.connect(self._accept_if_valid)
        layout.addWidget(self.buttons)

    @staticmethod
    def _build_field_group(
        layout: QVBoxLayout, title: str, fields: tuple[tuple[str, QWidget], ...]
    ) -> QFormLayout:
        """Add one titled field group so a nine-field form stays scannable."""
        group_title = QLabel(title)
        group_title.setObjectName("dialogFieldGroupTitle")
        layout.addWidget(group_title)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 4)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        for label, widget in fields:
            form.addRow(label, widget)
        layout.addLayout(form)
        return form

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


class NewMaterialTypeDialog(QDialog):
    """Collect one user-defined material type for the template editor."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = _configure_dialog(self, "新增材料类型", minimum_width=460)
        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("例如：验收单、保修卡")
        self.name_input.setMaxLength(100)
        self.description_input = QTextEdit()
        self.description_input.setFixedHeight(70)
        self.description_input.setPlaceholderText("可选，用于说明该材料的用途")
        form.addRow("名称 *", self.name_input)
        form.addRow("说明", self.description_input)
        layout.addLayout(form)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        _configure_dialog_buttons(self.buttons, save_text="添加材料")
        self.buttons.rejected.connect(self.reject)
        self.buttons.accepted.connect(self._accept_if_valid)
        layout.addWidget(self.buttons)

    def _accept_if_valid(self) -> None:
        if not self.material_name():
            QMessageBox.warning(self, "无法添加材料类型", "材料名称不能为空。")
            return
        self.accept()

    def material_name(self) -> str:
        return self.name_input.text().strip()

    def description(self) -> str | None:
        text = self.description_input.toPlainText().strip()
        return text or None


class TemplateEditorDialog(QDialog):
    """Edit the collection-material snapshot used for future Items."""

    def __init__(
        self,
        template_service: TemplateService,
        material_types: list[MaterialType],
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
        material_hint = QLabel(
            "勾选“加入模板”后，可设置该材料是否必需；"
            "列表里没有合适的类型时，可新增自定义材料类型。"
        )
        material_hint.setObjectName("dialogHint")
        material_hint.setWordWrap(True)
        layout.addWidget(material_hint)

        material_list = QFrame()
        material_list.setObjectName("templateMaterialList")
        self._material_list_layout = QVBoxLayout(material_list)
        self._material_list_layout.setContentsMargins(12, 8, 12, 8)
        self._material_list_layout.setSpacing(4)

        selected = {
            value.material_type.code: value.required
            for value in getattr(template, "materials", ())
        }
        self.material_inputs: dict[str, tuple[QCheckBox, QCheckBox]] = {}
        for material_type in material_types:
            self._append_material_row(
                material_type,
                checked=material_type.code in selected,
                required=selected.get(material_type.code, True),
            )

        material_scroll = QScrollArea()
        material_scroll.setObjectName("templateMaterialScroll")
        material_scroll.setWidgetResizable(True)
        material_scroll.setFrameShape(QFrame.Shape.NoFrame)
        material_scroll.setMaximumHeight(260)
        material_scroll.setWidget(material_list)
        layout.addWidget(material_scroll)

        add_material_layout = QHBoxLayout()
        self.add_material_type_button = QPushButton("+ 新增材料类型")
        self.add_material_type_button.setObjectName("templateAddMaterialButton")
        self.add_material_type_button.clicked.connect(self._add_custom_material_type)
        add_material_layout.addWidget(self.add_material_type_button)
        add_material_layout.addStretch()
        layout.addLayout(add_material_layout)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        _configure_dialog_buttons(
            self.buttons, save_text="保存模板" if template is not None else "创建模板"
        )
        self.buttons.rejected.connect(self.reject)
        self.buttons.accepted.connect(self._save)
        layout.addWidget(self.buttons)

    def _append_material_row(
        self,
        material_type: MaterialType,
        *,
        checked: bool,
        required: bool | None = None,
    ) -> None:
        """Append one selectable material type to the scrollable list."""
        code = material_type.code
        if code in self.material_inputs:
            return

        row = QHBoxLayout()
        included = QCheckBox(f"加入模板：{material_type.name}")
        included.setChecked(checked)
        required_checkbox = QCheckBox("必需")
        required_checkbox.setChecked(True if required is None else required)
        required_checkbox.setEnabled(checked)
        included.toggled.connect(required_checkbox.setEnabled)
        row.addWidget(included)
        row.addWidget(required_checkbox)
        row.addStretch()
        self._material_list_layout.addLayout(row)
        self.material_inputs[code] = (included, required_checkbox)

    def _add_custom_material_type(self) -> None:
        """Create a reusable material type and select it for this template."""
        dialog = NewMaterialTypeDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            material_type = self._template_service.create_material_type(
                dialog.material_name(), dialog.description()
            )
        except (TemplateServiceError, ValueError, SQLAlchemyError) as error:
            logger.warning("Failed to create a custom material type", exc_info=error)
            QMessageBox.warning(self, "无法添加材料类型", str(error))
            return

        self._append_material_row(material_type, checked=True)

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


class DashboardStatsGrid(QWidget):
    """Keep Dashboard statistics compact while adapting to the available width."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dashboardStatGrid")
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setHorizontalSpacing(12)
        self._layout.setVerticalSpacing(12)
        self._cards: list[QFrame] = []
        self._column_count = 0

    def add_card(self, card: QFrame) -> None:
        self._cards.append(card)
        self._column_count = 0
        self._relayout_cards()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._relayout_cards()

    def _relayout_cards(self) -> None:
        column_count = 4 if self.contentsRect().width() >= 760 else 2
        if column_count == self._column_count:
            return
        self._column_count = column_count
        while self._layout.count():
            self._layout.takeAt(0)
        for index, card in enumerate(self._cards):
            self._layout.addWidget(card, index // column_count, index % column_count)
        for column in range(column_count):
            self._layout.setColumnStretch(column, 1)


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
        workflow_service: WorkflowService | None = None,
        update_context: UpdateContext | None = None,
    ) -> None:
        super().__init__()
        self._update_context = update_context
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
        self._workflow_service = workflow_service
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
        sidebar.setFixedWidth(210)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 18)
        layout.setSpacing(14)

        title = QLabel("报销归档")
        title.setObjectName("appTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(title)

        self.navigation = SidebarNavigation()
        self.management_group_title = self.navigation.management_group_title
        self.navigation.setIconSize(QSize(18, 18))
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
        page.setObjectName("settingsPage")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setObjectName("settingsScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        page_layout.addWidget(scroll_area)

        content = QWidget()
        content.setObjectName("settingsContent")
        scroll_area.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QVBoxLayout()
        header.setSpacing(4)
        title = QLabel("设置")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        subtitle = QLabel("管理本地数据、备份与应用信息")
        subtitle.setObjectName("settingsPageSubtitle")
        header.addWidget(subtitle)
        layout.addLayout(header)

        storage_section = QFrame()
        storage_section.setObjectName("settingsGroupSurface")
        storage_layout = QVBoxLayout(storage_section)
        storage_layout.setContentsMargins(16, 14, 16, 14)
        storage_layout.setSpacing(8)
        storage_title = QLabel("数据与存储")
        storage_title.setObjectName("settingsSectionTitle")
        storage_layout.addWidget(storage_title)
        archive_title = QLabel("报销附件归档目录")
        archive_title.setObjectName("settingsRowTitle")
        storage_layout.addWidget(archive_title)
        archive_root = getattr(
            getattr(self._backup_service, "_settings", None), "archive_root", None
        )
        self._archive_root_path = Path(archive_root) if archive_root else None
        self.archive_root_label = QLabel(str(archive_root) if archive_root else "未配置")
        self.archive_root_label.setObjectName("settingsRowDetail")
        self.archive_root_label.setWordWrap(True)
        self.archive_root_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        storage_layout.addWidget(self.archive_root_label)
        self.open_archive_root_button = QPushButton("打开目录")
        self.open_archive_root_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.open_archive_root_button.setEnabled(self._archive_root_path is not None)
        self.open_archive_root_button.clicked.connect(self._open_archive_root)
        storage_layout.addWidget(
            self.open_archive_root_button, 0, Qt.AlignmentFlag.AlignLeft
        )
        layout.addWidget(storage_section)

        backup_section = QFrame()
        backup_section.setObjectName("settingsGroupSurface")
        backup_layout = QVBoxLayout(backup_section)
        backup_layout.setContentsMargins(20, 20, 20, 20)
        backup_layout.setSpacing(10)

        section_title = QLabel("数据库备份")
        section_title.setObjectName("settingsSectionTitle")
        backup_layout.addWidget(section_title)

        description = QLabel("备份数据库与元信息，不包含图片、PDF 等附件文件。")
        description.setObjectName("settingsSectionDescription")
        description.setWordWrap(True)
        backup_layout.addWidget(description)

        self.backup_database_button = QPushButton("备份数据库")
        self.backup_database_button.setObjectName("secondaryButton")
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
        restore_section.setObjectName("settingsGroupSurface")
        restore_layout = QVBoxLayout(restore_section)
        restore_layout.setContentsMargins(20, 20, 20, 20)
        restore_layout.setSpacing(10)

        restore_title = QLabel("恢复数据库")
        restore_title.setObjectName("settingsSectionTitle")
        restore_layout.addWidget(restore_title)

        restore_description = QLabel(
            "恢复会替换当前数据库，但不会恢复或删除附件文件。"
        )
        restore_description.setObjectName("settingsSectionDescription")
        restore_description.setWordWrap(True)
        restore_layout.addWidget(restore_description)

        self.restore_database_button = QPushButton("恢复数据库")
        self.restore_database_button.setObjectName("dangerButton")
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

        application_section = QFrame()
        application_section.setObjectName("settingsGroupSurface")
        application_layout = QVBoxLayout(application_section)
        application_layout.setContentsMargins(20, 20, 20, 20)
        application_layout.setSpacing(10)
        application_title = QLabel("应用")
        application_title.setObjectName("settingsSectionTitle")
        application_layout.addWidget(application_title)
        version_title = QLabel("版本")
        version_title.setObjectName("settingsRowTitle")
        application_layout.addWidget(version_title)
        self.application_version_label = QLabel(__version__)
        self.application_version_label.setObjectName("settingsRowDetail")
        application_layout.addWidget(self.application_version_label)
        layout.addWidget(application_section)

        self.update_section: UpdateSection | None = None
        if self._update_context is not None:
            self.update_section = UpdateSection(self._update_context, content)
            layout.addWidget(self.update_section)

        layout.addStretch()
        return page

    def _open_archive_root(self) -> None:
        """Open the configured archive root in the system file manager."""
        path = getattr(self, "_archive_root_path", None)
        if path is None:
            QMessageBox.warning(self, "无法打开目录", "归档目录尚未配置。")
            return
        if not path.exists():
            QMessageBox.warning(
                self, "无法打开目录", "归档目录不存在，请检查设置或磁盘。"
            )
            return
        try:
            self._desktop_integration_service.open_folder(path)
        except DesktopIntegrationError:
            logger.exception("Failed to open archive root %s", path)
            QMessageBox.warning(self, "无法打开目录", "打开目录失败，请稍后重试。")

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
        _configure_message_dialog(dialog)
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
        title_layout = QVBoxLayout()
        title_layout.setSpacing(4)
        title = QLabel("模板管理")
        title.setObjectName("templatePageTitle")
        title_layout.addWidget(title)
        subtitle = QLabel("管理新建报销物品时使用的材料清单")
        subtitle.setObjectName("templatePageSubtitle")
        title_layout.addWidget(subtitle)
        header.addLayout(title_layout)
        header.addStretch()
        self.new_template_button = QPushButton("+ 新建模板")
        self.new_template_button.setObjectName("primaryButton")
        self.new_template_button.clicked.connect(self._open_new_template_dialog)
        header.addWidget(self.new_template_button)
        layout.addLayout(header)

        self.template_list_surface = QFrame()
        self.template_list_surface.setObjectName("templateListSurface")
        template_list_layout = QVBoxLayout(self.template_list_surface)
        template_list_layout.setContentsMargins(0, 0, 0, 0)
        self.template_table = QTableWidget(0, 3)
        self.template_table.setHorizontalHeaderLabels(
            ("模板名称", "材料", "")
        )
        self.template_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.template_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.template_table.setObjectName("templateTable")
        self.template_table.setAlternatingRowColors(True)
        self.template_table.setShowGrid(False)
        self.template_table.verticalHeader().setVisible(False)
        self.template_table.verticalHeader().setDefaultSectionSize(52)
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
        template_list_layout.addWidget(self.template_table)
        layout.addWidget(self.template_list_surface, 1)

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
            self.template_list_surface.setVisible(False)
            self.template_table.setVisible(False)
            return
        try:
            templates = self._template_service.list_templates()
        except (TemplateServiceError, SQLAlchemyError):
            logger.exception("Failed to list templates")
            self.template_empty_state.setVisible(True)
            self.template_list_surface.setVisible(False)
            self.template_table.setVisible(False)
            return
        for template in templates:
            row = self.template_table.rowCount()
            self.template_table.insertRow(row)
            values = (
                template.name,
                f"{len(template.materials)} 项材料 · "
                f"{sum(value.required for value in template.materials)} 项必需",
                "›",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, template.id)
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                elif column == 2:
                    item.setForeground(QColor(IOS_LIGHT_TOKENS.tertiary_text))
                    item.setData(
                        Qt.ItemDataRole.TextAlignmentRole,
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    )
                else:
                    item.setData(
                        Qt.ItemDataRole.TextAlignmentRole,
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    )
                self.template_table.setItem(row, column, item)
        is_empty = self.template_table.rowCount() == 0
        self.template_empty_state.setVisible(is_empty)
        self.template_list_surface.setVisible(not is_empty)
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
        self.pending_materials_subtitle = QLabel(
            "集中处理仍缺材料或尚未准备好提交的物品"
        )
        self.pending_materials_subtitle.setObjectName("pendingMaterialsSubtitle")
        title_layout.addWidget(self.pending_materials_subtitle)
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

        self.pending_materials_list_surface = QFrame()
        self.pending_materials_list_surface.setObjectName("pendingMaterialsListSurface")
        list_layout = QVBoxLayout(self.pending_materials_list_surface)
        list_layout.setContentsMargins(0, 0, 0, 0)

        self.pending_materials_table = QTableWidget(0, 6)
        self.pending_materials_table.setObjectName("pendingMaterialsTable")
        self.pending_materials_table.setHorizontalHeaderLabels(
            ("物品名称", "所属批次", "材料收集", "缺失原始材料", "提交材料", "缺失提交材料")
        )
        self.pending_materials_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.pending_materials_table.setSelectionMode(
            QTableWidget.SelectionMode.NoSelection
        )
        self.pending_materials_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pending_materials_table.setAlternatingRowColors(True)
        self.pending_materials_table.setShowGrid(False)
        self._make_table_rows_clickable(
            self.pending_materials_table, self._open_pending_material_item_detail
        )
        self._align_table_headers(
            self.pending_materials_table, center=(2, 4)
        )
        self.pending_materials_table.verticalHeader().setVisible(False)
        self.pending_materials_table.verticalHeader().setDefaultSectionSize(52)
        self.pending_materials_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in range(1, self.pending_materials_table.columnCount()):
            self.pending_materials_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        list_layout.addWidget(self.pending_materials_table)
        layout.addWidget(self.pending_materials_list_surface, 1)

        self.pending_materials_empty_state = QFrame()
        self.pending_materials_empty_state.setObjectName("pendingMaterialsEmptyState")
        empty_layout = QVBoxLayout(self.pending_materials_empty_state)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.setSpacing(8)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pending_materials_empty_title = QLabel("当前没有待处理事项")
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
            self.pending_materials_list_surface.setVisible(False)
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
                ),
                self._pending_missing_text(
                    entry.missing_collection_materials, complete_text="材料完整"
                ),
                self._pending_progress_text(
                    entry.submission_completed_count,
                    entry.submission_required_count,
                ),
                self._pending_missing_text(
                    entry.missing_submission_materials, complete_text="可提交"
                ),
            )
            for column, value in enumerate(values):
                table_item = QTableWidgetItem(value)
                if column == 0:
                    table_item.setData(Qt.ItemDataRole.UserRole, entry.item_id)
                if column in (2, 4):
                    table_item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
                    )
                if column in (3, 5):
                    table_item.setToolTip(value)
                    is_complete = value in {"材料完整", "可提交"}
                    table_item.setForeground(
                        QColor(IOS_LIGHT_TOKENS.success_text)
                        if is_complete
                        else QColor(IOS_LIGHT_TOKENS.warning_text)
                    )
                    table_item.setBackground(
                        QColor(IOS_LIGHT_TOKENS.success_surface)
                        if is_complete
                        else QColor(IOS_LIGHT_TOKENS.warning_surface)
                    )
                    if not is_complete:
                        table_item.setFont(QFont("", -1, QFont.Weight.DemiBold))
                self.pending_materials_table.setItem(row, column, table_item)
        has_pending_items = self.pending_materials_table.rowCount() > 0
        self.pending_materials_table.setVisible(has_pending_items)
        self.pending_materials_list_surface.setVisible(has_pending_items)
        self.pending_materials_empty_state.setVisible(not has_pending_items)

    @staticmethod
    def _pending_progress_text(completed: int, required: int) -> str:
        return f"{completed} / {required}"

    @staticmethod
    def _pending_missing_text(
        missing_materials: tuple[str, ...], *, complete_text: str
    ) -> str:
        friendly_names = tuple(
            "最终支付截图" if material == "合并支付截图" else material
            for material in missing_materials
        )
        return complete_text if not friendly_names else f"缺少：{'、'.join(friendly_names)}"

    def _build_all_items_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("allItemsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(16)
        title_group = QVBoxLayout()
        title_group.setSpacing(4)
        self.all_items_title = QLabel("所有物品")
        self.all_items_title.setObjectName("pageTitle")
        title_group.addWidget(self.all_items_title)
        self.all_items_subtitle = QLabel("查看和搜索全部报销物品")
        self.all_items_subtitle.setObjectName("allItemsSubtitle")
        title_group.addWidget(self.all_items_subtitle)
        header.addLayout(title_group)
        header.addStretch()
        self.all_items_search_input = QLineEdit()
        self.all_items_search_input.setObjectName("allItemsSearchInput")
        self.all_items_search_input.setPlaceholderText("搜索物品、商家或订单号")
        self.all_items_search_input.setMinimumWidth(280)
        self.all_items_search_input.setMaximumWidth(360)
        self.all_items_search_input.textChanged.connect(self.refresh_all_items)
        header.addWidget(self.all_items_search_input)
        layout.addLayout(header)

        self.all_items_list_surface = QFrame()
        self.all_items_list_surface.setObjectName("allItemsListSurface")
        list_layout = QVBoxLayout(self.all_items_list_surface)
        list_layout.setContentsMargins(0, 0, 0, 0)

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
        self.all_items_table.setSelectionMode(
            QTableWidget.SelectionMode.NoSelection
        )
        self.all_items_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.all_items_table.setAlternatingRowColors(True)
        self.all_items_table.setShowGrid(False)
        self.all_items_table.verticalHeader().setVisible(False)
        self.all_items_table.verticalHeader().setDefaultSectionSize(52)
        self.all_items_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in range(1, self.all_items_table.columnCount()):
            self.all_items_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.all_items_table.horizontalHeader().setSectionResizeMode(
            7, QHeaderView.ResizeMode.Fixed
        )
        self.all_items_table.setColumnWidth(7, 96)
        self._make_table_rows_clickable(self.all_items_table, self._open_item_detail)
        self._align_table_headers(
            self.all_items_table, right=(2,), center=(5, 7)
        )
        list_layout.addWidget(self.all_items_table)
        layout.addWidget(self.all_items_list_surface, 1)

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
        self.all_items_clear_search_button = QPushButton("清空搜索")
        self.all_items_clear_search_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.all_items_clear_search_button.clicked.connect(
            self.all_items_search_input.clear
        )
        self.all_items_clear_search_button.setVisible(False)
        empty_layout.addWidget(
            self.all_items_clear_search_button,
            0,
            Qt.AlignmentFlag.AlignCenter,
        )
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
            item_status = self._display_item_status(
                item.id, item.status, collection_complete=completeness.is_complete
            )
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
                f"{completeness.completed_count} / {completeness.required_count}",
                missing_materials or "材料完整",
                ITEM_STATUS_LABELS.get(item_status, item_status),
            )
            for column, value in enumerate(values):
                if column == 7:
                    continue
                table_item = QTableWidgetItem(value)
                if column == 0:
                    table_item.setData(Qt.ItemDataRole.UserRole, item.id)
                    table_item.setFont(QFont("", -1, QFont.Weight.DemiBold))
                if column in (1, 3, 4):
                        table_item.setForeground(QColor(IOS_LIGHT_TOKENS.secondary_text))
                if column == 2:
                    table_item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                elif column == 5:
                    table_item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
                    )
                if column == 6:
                    table_item.setToolTip(value)
                    if completeness.is_complete:
                        table_item.setForeground(
                            QColor(IOS_LIGHT_TOKENS.success_text)
                        )
                    else:
                        table_item.setForeground(
                            QColor(IOS_LIGHT_TOKENS.warning_text)
                        )
                self.all_items_table.setItem(row, column, table_item)
            status_badge = QLabel(values[7])
            status_badge.setObjectName("allItemsWorkflowBadge")
            status_badge.setProperty("status", item_status)
            status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.all_items_table.setCellWidget(row, 7, status_badge)
        self._set_all_items_empty_state(
            is_search_result=bool(query.strip())
            and self.all_items_table.rowCount() == 0
        )

    def _display_item_status(
        self,
        item_id: int,
        status: ReimbursementStatus,
        *,
        collection_complete: bool | None = None,
    ) -> str:
        """Return the status label for one Item without persisting it.

        Readiness is derived from the Item's own submission package, so it is
        only computed while the Item is still collecting materials.
        """
        if status is not ReimbursementStatus.COLLECTING:
            return display_status(status, submission_ready=False)
        if collection_complete is None:
            collection_complete = (
                self._completeness_service.calculate(item_id).is_complete
                if self._completeness_service is not None
                else None
            )
        submission_ready = (
            self._submission_readiness_service is not None
            and self._submission_readiness_service.calculate(item_id).is_ready
        )
        return display_status(
            status,
            submission_ready=submission_ready,
            collection_complete=collection_complete,
        )

    def _set_all_items_empty_state(self, *, is_search_result: bool) -> None:
        """Show the empty state appropriate to the current all-items query."""
        is_empty = self.all_items_table.rowCount() == 0
        self.all_items_list_surface.setVisible(not is_empty)
        self.all_items_empty_state.setVisible(is_empty)
        if not is_empty:
            return
        if is_search_result:
            self.all_items_empty_title.setText("没有找到匹配的物品")
            self.all_items_empty_description.setText("尝试使用其他关键词。")
            self.all_items_clear_search_button.setVisible(True)
            return
        self.all_items_empty_title.setText("暂无报销物品")
        self.all_items_empty_description.setText(
            "创建报销批次并添加物品后，它们会出现在这里。"
        )
        self.all_items_clear_search_button.setVisible(False)

    def _build_batch_list_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("batchListPage")
        self.batch_list_page = page
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(16)
        title_group = QVBoxLayout()
        title_group.setSpacing(4)
        self.batch_list_title = QLabel("报销批次")
        self.batch_list_title.setObjectName("pageTitle")
        title_group.addWidget(self.batch_list_title)
        self.batch_list_subtitle = QLabel("管理当前和历史报销批次")
        self.batch_list_subtitle.setObjectName("batchListSubtitle")
        title_group.addWidget(self.batch_list_subtitle)
        header.addLayout(title_group)
        header.addStretch()
        self.new_batch_button = QPushButton("+ 新建批次")
        self.new_batch_button.setObjectName("primaryButton")
        self.new_batch_button.clicked.connect(self._open_new_batch_dialog)
        header.addWidget(self.new_batch_button)
        layout.addLayout(header)

        self.batch_list_surface = QFrame()
        self.batch_list_surface.setObjectName("batchListSurface")
        surface_layout = QVBoxLayout(self.batch_list_surface)
        surface_layout.setContentsMargins(0, 0, 0, 0)

        self.batch_table = QTableWidget(0, 5)
        self.batch_table.setObjectName("batchTable")
        self.batch_table.setHorizontalHeaderLabels(
            ("批次名称", "创建日期", "物品数量", "总金额", "状态")
        )
        self.batch_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.batch_table.setSelectionMode(
            QTableWidget.SelectionMode.NoSelection
        )
        self.batch_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.batch_table.setAlternatingRowColors(True)
        self.batch_table.setShowGrid(False)
        self.batch_table.verticalHeader().setVisible(False)
        self.batch_table.verticalHeader().setDefaultSectionSize(52)
        self.batch_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in (1, 2, 3, 4):
            self.batch_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self._make_table_rows_clickable(self.batch_table, self._open_batch_detail)
        self._align_table_headers(
            self.batch_table, right=(2, 3), center=(4,)
        )
        surface_layout.addWidget(self.batch_table)
        layout.addWidget(self.batch_list_surface, 1)

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
        self.back_to_all_items_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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
        details = QVBoxLayout(details_frame)
        details.setContentsMargins(16, 14, 16, 14)
        details.setSpacing(6)
        self.item_detail_purchase_date_label = QLabel()
        self.item_detail_platform_label = QLabel()
        self.item_detail_merchant_label = QLabel()
        self.item_detail_order_number_label = QLabel()
        self.item_detail_batch_label = QLabel()
        self.item_detail_primary_metadata_label = QLabel()
        self.item_detail_primary_metadata_label.setObjectName("itemDetailMetadataPrimary")
        self.item_detail_merchant_label.setObjectName("itemDetailMetadataSecondary")
        self.item_detail_order_number_label.setObjectName("itemDetailMetadataSecondary")
        self.item_detail_batch_label.setObjectName("itemDetailMetadataSecondary")
        details.addWidget(self.item_detail_primary_metadata_label)
        metadata_row = QHBoxLayout()
        metadata_row.setContentsMargins(0, 0, 0, 0)
        metadata_row.setSpacing(16)
        metadata_row.addWidget(self.item_detail_merchant_label)
        metadata_row.addWidget(self.item_detail_order_number_label)
        metadata_row.addWidget(self.item_detail_batch_label)
        metadata_row.addStretch()
        details.addLayout(metadata_row)
        layout.addWidget(details_frame)

        workflow_card = QFrame()
        workflow_card.setObjectName("itemDetailWorkflowCard")
        workflow_layout = QHBoxLayout(workflow_card)
        workflow_layout.setContentsMargins(16, 14, 16, 14)
        workflow_layout.setSpacing(12)
        workflow_title = QLabel("报销状态")
        workflow_title.setObjectName("itemDetailStatusTitle")
        workflow_layout.addWidget(workflow_title)
        self.item_detail_status_label = QLabel()
        self.item_detail_status_label.setObjectName("itemDetailWorkflowBadge")
        workflow_layout.addWidget(
            self.item_detail_status_label, 0, Qt.AlignmentFlag.AlignVCenter
        )
        workflow_layout.addStretch()
        self.item_detail_workflow_button = QPushButton()
        self.item_detail_workflow_button.setObjectName("primaryButton")
        self.item_detail_workflow_button.clicked.connect(
            self._advance_current_item_workflow
        )
        workflow_layout.addWidget(
            self.item_detail_workflow_button, 0, Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(workflow_card)

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
        self.item_detail_collection_count_label = QLabel()
        self.item_detail_collection_count_label.setObjectName("itemDetailStatusValue")
        self.item_detail_collection_percentage_label = QLabel()
        self.item_detail_collection_percentage_label.setObjectName("itemDetailStatusText")
        collection_metrics = QHBoxLayout()
        collection_metrics.setContentsMargins(0, 0, 0, 0)
        collection_metrics.setSpacing(8)
        collection_metrics.addWidget(self.item_detail_collection_count_label)
        collection_metrics.addStretch()
        collection_metrics.addWidget(
            self.item_detail_collection_percentage_label,
            0,
            Qt.AlignmentFlag.AlignBottom,
        )
        collection_layout.addLayout(collection_metrics)
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
        self.item_detail_submission_count_label = QLabel()
        self.item_detail_submission_count_label.setObjectName("itemDetailStatusValue")
        submission_layout.addWidget(self.item_detail_submission_count_label)
        submission_layout.addWidget(self.item_detail_submission_readiness_label)
        self.item_detail_submission_progress = QProgressBar()
        self.item_detail_submission_progress.setObjectName("itemDetailProgress")
        self.item_detail_submission_progress.setTextVisible(False)
        submission_layout.addWidget(self.item_detail_submission_progress)
        self.export_submission_materials_button = QPushButton("导出提交材料")
        self.export_submission_materials_button.setObjectName("itemDetailExportButton")
        self.export_submission_materials_button.clicked.connect(
            self._export_submission_materials
        )
        submission_layout.addWidget(
            self.export_submission_materials_button, 0, Qt.AlignmentFlag.AlignLeft
        )
        self.export_submission_hint_label = QLabel()
        self.export_submission_hint_label.setObjectName("actionHint")
        self.export_submission_hint_label.setWordWrap(True)
        submission_layout.addWidget(self.export_submission_hint_label)
        status_layout.addWidget(submission_card, 1)
        layout.addLayout(status_layout)

        self.merged_payment_section = QFrame()
        self.merged_payment_section.setObjectName("mergedPaymentSection")
        self.merged_payment_section_layout = QVBoxLayout(self.merged_payment_section)
        self.merged_payment_section_layout.setContentsMargins(16, 16, 16, 16)
        self.merged_payment_section_layout.setSpacing(12)
        layout.addWidget(self.merged_payment_section)

        materials_title = QLabel("材料")
        materials_title.setObjectName("sectionTitle")
        layout.addWidget(materials_title)
        self.item_detail_materials = QWidget()
        self.item_detail_materials.setObjectName("itemDetailMaterials")
        self.item_detail_materials_layout = QVBoxLayout(self.item_detail_materials)
        self.item_detail_materials_layout.setContentsMargins(0, 0, 0, 0)
        self.item_detail_materials_layout.setSpacing(12)
        layout.addWidget(self.item_detail_materials)

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
        submission = (
            self._submission_readiness_service.calculate(item_id)
            if self._submission_readiness_service is not None
            else None
        )
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
        item_status = display_status(
            item.status,
            submission_ready=submission is not None and submission.is_ready,
            collection_complete=completeness.is_complete,
        )
        self.item_detail_status_label.setText(
            ITEM_STATUS_LABELS.get(item_status, item_status)
        )
        self.item_detail_status_label.setProperty("status", item_status)
        self._refresh_dynamic_style(self.item_detail_status_label)
        metadata_parts = [
            value
            for value in (
                item.platform,
                item.purchase_date.isoformat() if item.purchase_date else None,
            )
            if value
        ]
        self.item_detail_primary_metadata_label.setText(" · ".join(metadata_parts))
        self.item_detail_primary_metadata_label.setVisible(bool(metadata_parts))
        self.item_detail_platform_label.setVisible(False)
        self.item_detail_purchase_date_label.setVisible(False)
        metadata_rows = (
            (self.item_detail_merchant_label, "商家", item.merchant),
            (self.item_detail_order_number_label, "订单号", item.order_number),
            (self.item_detail_batch_label, "所属批次", item.batch.name),
        )
        for label, title, value in metadata_rows:
            label.setText(f"{title}：{value}" if value else "")
            label.setVisible(bool(value))
        self._update_item_workflow_action(item.status)
        self.item_detail_collection_count_label.setText(
            f"{completeness.completed_count} / {completeness.required_count}"
        )
        self.item_detail_collection_percentage_label.setText(
            f"{completeness.percentage}%"
        )
        self.item_detail_completeness_label.setText(
            "材料完整"
            if completeness.is_complete
            else f"缺少：{'、'.join(material.name for material in completeness.missing)}"
        )
        self.item_detail_collection_progress.setRange(0, 100)
        self.item_detail_collection_progress.setValue(completeness.percentage)
        self.item_detail_collection_progress.setProperty(
            "semantic", "success" if completeness.is_complete else "accent"
        )
        self._refresh_dynamic_style(self.item_detail_collection_progress)
        if submission is not None:
            missing = "、".join(material.name for material in submission.missing)
            self.item_detail_submission_count_label.setText(
                f"{submission.completed_count} / {submission.required_count}"
            )
            self.item_detail_submission_readiness_label.setText(
                "可提交" if submission.is_ready else f"缺少：{missing}"
            )
            submission_percentage = (
                round(submission.completed_count * 100 / submission.required_count)
                if submission.required_count
                else 100
            )
            self.item_detail_submission_progress.setRange(0, 100)
            self.item_detail_submission_progress.setValue(submission_percentage)
            self.item_detail_submission_progress.setProperty(
                "semantic", "success" if submission.is_ready else "accent"
            )
            self._refresh_dynamic_style(self.item_detail_submission_progress)
            self.export_submission_materials_button.setEnabled(
                submission.is_ready and self._export_service is not None
            )
            self.export_submission_materials_button.setToolTip(
                "" if submission.is_ready else f"提交材料未完整，缺少：{missing}"
            )
            self.export_submission_hint_label.setText(
                "" if submission.is_ready else "提交材料不齐全时不能导出。"
            )
            self.item_detail_workflow_button.setProperty(
                "quiet",
                "true"
                if item.status is ReimbursementStatus.COLLECTING
                and not submission.is_ready
                else "false",
            )
            self.item_detail_workflow_button.setToolTip(
                ""
                if submission.is_ready
                else "提交材料尚未齐全，点击后会先确认再提交。"
            )
            self._refresh_dynamic_style(self.item_detail_workflow_button)
        else:
            self.item_detail_submission_count_label.clear()
            self.item_detail_submission_readiness_label.clear()
            self.item_detail_submission_progress.setRange(0, 100)
            self.item_detail_submission_progress.setValue(0)
            self.item_detail_submission_progress.setProperty("semantic", "accent")
            self._refresh_dynamic_style(self.item_detail_submission_progress)
            self.export_submission_materials_button.setEnabled(False)
            self.export_submission_materials_button.setToolTip("提交材料状态当前不可用。")
            self.export_submission_hint_label.setText("提交材料状态当前不可用。")
            self.item_detail_workflow_button.setProperty("quiet", "false")
            self._refresh_dynamic_style(self.item_detail_workflow_button)
        self._current_item_detail_id = item_id

        self._clear_layout(self.item_detail_materials_layout)
        for requirement in item.requirements:
            attachments = attachments_by_material.get(
                requirement.material_type_id, []
            )
            is_missing = requirement.required and any(
                material.material_type_id == requirement.material_type_id
                for material in completeness.missing
            )
            self.item_detail_materials_layout.addWidget(
                self._build_material_section(
                    item_id=item_id,
                    material_type_id=requirement.material_type_id,
                    material_name=requirement.material_type.name,
                    required=requirement.required,
                    attachments=attachments,
                    is_missing=is_missing,
                )
            )
        self.item_detail_materials_layout.addStretch()

        self._populate_merged_payment_section(item_id, attachments_by_material, item)

    def _populate_merged_payment_section(
        self,
        item_id: int,
        attachments_by_material: dict[int, list[Attachment]],
        item: Item,
    ) -> None:
        """Render the payment-merge workflow using the merge service's selection rule."""
        self._clear_layout(self.merged_payment_section_layout)

        material_type_ids = {
            requirement.material_type.code: requirement.material_type_id
            for requirement in item.requirements
        }
        order_id = material_type_ids.get("order_screenshot")
        payment_id = material_type_ids.get(PAYMENT_SCREENSHOT_CODE)

        # The merge needs both screenshots; templates that do not ask for an
        # order screenshot have no payment certificate step at all.
        merge_applicable = order_id is not None and payment_id is not None
        self.merged_payment_section.setVisible(merge_applicable)
        if not merge_applicable:
            return

        title = QLabel("支付凭证")
        title.setObjectName("mergedPaymentSectionTitle")
        self.merged_payment_section_layout.addWidget(title)
        description = QLabel("订单截图与支付截图将合并为最终提交用的支付截图")
        description.setObjectName("mergedPaymentSectionDescription")
        description.setWordWrap(True)
        self.merged_payment_section_layout.addWidget(description)

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

        arrow = QLabel("↓\n最终支付截图")
        arrow.setObjectName("mergedPaymentFlow")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.merged_payment_section_layout.addWidget(arrow)

        result = QFrame()
        result.setObjectName("mergedPaymentResult")
        result_layout = QVBoxLayout(result)
        result_layout.setContentsMargins(12, 12, 12, 12)
        result_layout.setSpacing(8)
        result_title = QLabel("最终支付截图")
        result_title.setObjectName("mergedPaymentResultTitle")
        result_layout.addWidget(result_title)
        latest_result = self._latest_usable_merged_payment(
            attachments_by_material.get(payment_id, []) if payment_id is not None else [],
            payment_id,
        )
        if latest_result is None:
            empty = QLabel("尚未生成最终支付截图")
            empty.setObjectName("mergedPaymentEmpty")
            result_layout.addWidget(empty, 0, Qt.AlignmentFlag.AlignLeft)
        else:
            result_layout.addWidget(self._build_attachment_card(latest_result))
        self.merged_payment_section_layout.addWidget(result)

        self.generate_merged_payment_screenshot_button = QPushButton(
            "重新生成" if latest_result is not None else "生成支付截图"
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
        merge_hint = ""
        if order_attachment is None and payment_attachment is None:
            merge_hint = "先上传订单截图与支付截图。"
        elif order_attachment is None:
            merge_hint = "还缺订单截图。"
        elif payment_attachment is None:
            merge_hint = "还缺支付截图。"
        if merge_hint:
            self.merged_payment_hint_label = QLabel(merge_hint)
            self.merged_payment_hint_label.setObjectName("actionHint")
            self.merged_payment_section_layout.addWidget(self.merged_payment_hint_label)

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
            layout.addWidget(missing, 0, Qt.AlignmentFlag.AlignLeft)
        else:
            unsupported = QLabel("当前附件不是可直接合并的图片")
            unsupported.setObjectName("mergedPaymentSourceUnsupported")
            unsupported.setWordWrap(True)
            layout.addWidget(unsupported, 0, Qt.AlignmentFlag.AlignLeft)
            latest_attachment = next(
                (attachment for attachment in reversed(attachments) if not attachment.is_derived),
                None,
            )
            if latest_attachment is not None:
                filename = QLabel(latest_attachment.stored_filename)
                filename.setObjectName("mergedPaymentSourceFilename")
                filename.setWordWrap(True)
                layout.addWidget(filename)
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

    def _build_material_section(
        self,
        *,
        item_id: int,
        material_type_id: int,
        material_name: str,
        required: bool,
        attachments: list[Attachment],
        is_missing: bool,
    ) -> QFrame:
        """Build one lightweight grouped material section from service-backed data."""
        section = MaterialDropSection()
        section.setObjectName("materialSection")
        section.setProperty("materialTypeId", material_type_id)
        section.filesDropped.connect(
            lambda paths: self._add_attachments(
                item_id, material_type_id, tuple(Path(path) for path in paths)
            )
        )
        layout = QVBoxLayout(section)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel(material_name)
        title.setObjectName("materialSectionTitle")
        header.addWidget(title, 1)
        requirement_badge = QLabel("必需" if required else "可选")
        requirement_badge.setObjectName("materialRequirementBadge")
        requirement_badge.setProperty("kind", "required" if required else "optional")
        header.addWidget(requirement_badge)
        attachment_count = QLabel(f"{len(attachments)} 个附件")
        attachment_count.setObjectName("materialAttachmentCount")
        header.addWidget(attachment_count)
        layout.addLayout(header)

        if attachments:
            layout.addWidget(self._build_attachment_grid(attachments))
        else:
            empty_state = QLabel("缺少材料" if is_missing else "暂无附件")
            empty_state.setObjectName(
                "materialMissingState" if is_missing else "materialOptionalState"
            )
            layout.addWidget(empty_state, 0, Qt.AlignmentFlag.AlignLeft)
            drop_hint = QLabel("可拖动一个或多个文件到此区域")
            drop_hint.setObjectName("materialDropHint")
            layout.addWidget(drop_hint)

        add_attachment_button = QPushButton("+ 添加附件")
        add_attachment_button.setObjectName("itemDetailAddAttachmentButton")
        add_attachment_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        add_attachment_button.clicked.connect(
            lambda _checked=False: self._select_and_add_attachment(
                item_id, material_type_id
            )
        )
        layout.addWidget(add_attachment_button, 0, Qt.AlignmentFlag.AlignLeft)
        return section

    def _build_attachment_grid(self, attachments: list[Attachment]) -> QWidget:
        """Build the current material's responsive, wrapping attachment cards."""
        grid_widget = QWidget()
        grid_widget.setObjectName("attachmentGrid")
        layout = AttachmentFlowLayout(grid_widget)
        for attachment in attachments:
            layout.addWidget(self._build_attachment_card(attachment))
        return grid_widget

    def _build_attachment_card(self, attachment: Attachment) -> QFrame:
        """Render an attachment using only its existing stored archive file."""
        card = QFrame()
        card.setObjectName("attachmentCard")
        card.setFixedWidth(224)
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

        filename_label = QLabel()
        filename_label.setObjectName("attachmentFilename")
        filename_label.setWordWrap(False)
        filename_font = QFont()
        filename_font.setPixelSize(IOS_LIGHT_TOKENS.body_size)
        filename_font.setWeight(QFont.Weight.DemiBold)
        filename_label.setFixedWidth(200)
        filename_label.setText(
            QFontMetrics(filename_font).elidedText(
                display_name, Qt.TextElideMode.ElideMiddle, 196
            )
        )
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
        layout.setSpacing(8)
        open_button = QPushButton("\u6253\u5f00")
        open_button.setObjectName("attachmentTextAction")
        open_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        open_button.clicked.connect(
            lambda _checked=False: self._open_attachment(attachment_id)
        )
        layout.addWidget(open_button)
        open_folder_button = QPushButton("\u6587\u4ef6\u5939")
        open_folder_button.setObjectName("attachmentTextAction")
        open_folder_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        open_folder_button.setToolTip("\u6253\u5f00\u6240\u5728\u6587\u4ef6\u5939")
        open_folder_button.clicked.connect(
            lambda _checked=False: self._open_attachment_folder(attachment_id)
        )
        layout.addWidget(open_folder_button)
        remove_button = QPushButton("\u5220\u9664")
        remove_button.setObjectName("attachmentDangerAction")
        remove_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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
            "删除后附件会移入应用回收目录，不会直接永久删除。\n\n仍要删除吗？",
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

        message = "删除后物品会从当前批次移除。\n\n仍要删除这个物品吗？"
        if attachment_count:
            message = (
                f"该物品包含 {attachment_count} 个附件。删除后附件将移动到应用回收目录，"
                "不会直接永久删除。\n\n仍要删除这个物品吗？"
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

    @staticmethod
    def _make_table_rows_clickable(
        table: QTableWidget, handler: Callable[[int, int], None]
    ) -> None:
        """Open a row on a single click and advertise it with a pointer cursor.

        Double-click stays wired for people who expect it; because the handler
        switches pages, the second click lands on the newly shown page instead
        of reopening the same row.
        """
        table.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        table.cellClicked.connect(handler)
        table.cellDoubleClicked.connect(handler)

    @staticmethod
    def _align_table_headers(
        table: QTableWidget,
        *,
        right: tuple[int, ...] = (),
        center: tuple[int, ...] = (),
    ) -> None:
        """Keep header labels aligned with the cells they describe."""
        vertical = Qt.AlignmentFlag.AlignVCenter
        table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | vertical
        )
        for column in range(table.columnCount()):
            header_item = table.horizontalHeaderItem(column)
            if header_item is None:
                continue
            if column in right:
                alignment = Qt.AlignmentFlag.AlignRight | vertical
            elif column in center:
                alignment = Qt.AlignmentFlag.AlignCenter | vertical
            else:
                alignment = Qt.AlignmentFlag.AlignLeft | vertical
            header_item.setTextAlignment(alignment)

    @staticmethod
    def _refresh_dynamic_style(widget: QWidget) -> None:
        """Apply QSS selectors again after a dynamic presentation property changes."""
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    def _update_item_workflow_action(self, status: ReimbursementStatus) -> None:
        actions = {
            ReimbursementStatus.COLLECTING: "标记已提交",
            ReimbursementStatus.SUBMITTED: "标记已报销",
            ReimbursementStatus.REIMBURSED: "归档",
        }
        label = actions.get(status)
        self.item_detail_workflow_button.setVisible(label is not None)
        self.item_detail_workflow_button.setEnabled(
            label is not None and self._workflow_service is not None
        )
        self.item_detail_workflow_button.setText(label or "")

    def _advance_current_item_workflow(self) -> None:
        if self._workflow_service is None or not hasattr(self, "_current_item_detail_id"):
            return
        item_id = self._current_item_detail_id
        try:
            self._workflow_service.advance_item(item_id)
        except SubmissionNotReadyError as error:
            if not self._confirm_unready_submission(error.items):
                return
            try:
                self._workflow_service.advance_item(
                    item_id, allow_unready_submission=True
                )
            except WorkflowServiceError as retry_error:
                QMessageBox.warning(self, "无法更新报销状态", str(retry_error))
                return
        except WorkflowServiceError as error:
            QMessageBox.warning(self, "无法更新报销状态", str(error))
            return
        self._refresh_after_workflow_change(item_id=item_id)

    def _refresh_after_workflow_change(self, *, item_id: int | None = None) -> None:
        self.refresh_all_items()
        self.refresh_dashboard()
        self.refresh_batch_list()
        self._refresh_current_batch_detail()
        if item_id is not None:
            self._populate_item_detail(item_id)

    def _confirm_unready_submission(self, items: tuple[object, ...]) -> bool:
        details = "\n\n".join(
            f"{item.item_name}\n缺：{'、'.join(material.name for material in item.readiness.missing)}"
            for item in items
        )
        confirmed = QMessageBox.question(
            self,
            "提交材料不完整",
            f"以下物品提交材料不完整：\n\n{details}\n\n仍要标记已提交吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return confirmed is QMessageBox.StandardButton.Yes

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

        self._add_attachments(item_id, material_type_id, (Path(source_path),))

    def _add_attachments(
        self,
        item_id: int,
        material_type_id: int,
        source_paths: tuple[Path, ...],
    ) -> None:
        """Import one or more files and refresh Item Detail once when successful."""
        if self._attachment_service is None:
            QMessageBox.warning(self, "无法添加附件", "附件服务当前不可用。")
            return

        failures: list[tuple[Path, str]] = []
        added_count = 0
        for source_path in source_paths:
            try:
                self._attachment_service.add_attachment(
                    item_id=item_id,
                    material_type_id=material_type_id,
                    source_path=source_path,
                )
                added_count += 1
            except DuplicateAttachmentError:
                failures.append((source_path, "该文件已经添加到这个报销物品。"))
            except ItemNotFoundError:
                failures.append((source_path, "当前报销物品不存在或已失效。"))
            except MaterialRequirementNotFoundError:
                failures.append((source_path, "当前材料要求已失效，请刷新后重试。"))
            except (AttachmentServiceError, OSError, SQLAlchemyError):
                logger.exception(
                    "Failed to add attachment %s to item %s", source_path, item_id
                )
                failures.append(
                    (source_path, "添加附件失败，请确认文件可访问后重试。")
                )
            except Exception:
                logger.exception(
                    "Unexpected attachment upload failure for %s on item %s",
                    source_path,
                    item_id,
                )
                failures.append((source_path, "添加附件失败，请稍后重试。"))

        if added_count:
            self._populate_item_detail(item_id)
        if not failures:
            return
        if len(source_paths) == 1:
            QMessageBox.warning(self, "无法添加附件", failures[0][1])
            return

        details = "\n".join(f"{path.name}：{message}" for path, message in failures)
        QMessageBox.warning(
            self,
            "部分附件未添加",
            f"已添加 {added_count} 个文件，{len(failures)} 个文件未能添加：\n{details}",
        )

    def _show_all_items(self) -> None:
        self.navigation.setCurrentRow(ALL_ITEMS_PAGE_INDEX)
        self.pages.setCurrentIndex(ALL_ITEMS_PAGE_INDEX)

    def _show_item_detail_return_page(self) -> None:
        page_index = getattr(
            self, "_item_detail_return_page_index", ALL_ITEMS_PAGE_INDEX
        )
        if page_index == BATCH_DETAIL_PAGE_INDEX:
            self.navigation.setCurrentRow(BATCH_LIST_PAGE_INDEX)
            self.pages.setCurrentIndex(BATCH_DETAIL_PAGE_INDEX)
            return
        self.navigation.setCurrentRow(page_index)
        self.pages.setCurrentIndex(page_index)

    def refresh_batch_list(self) -> None:
        """Refresh displayed batch summaries through the application service."""
        self.batch_table.setRowCount(0)
        self._batch_entries: dict[int, BatchListEntry] = {}
        if self._batch_service is not None:
            batch_statuses = {
                batch.id: BATCH_STATUS_LABELS.get(str(batch.status), str(batch.status))
                for batch in self._batch_service.list_batches()
            }
            for entry in self._batch_service.list_batch_entries():
                self._batch_entries[entry.id] = entry
                self._append_batch_entry(
                    entry, status_label=batch_statuses.get(entry.id, "")
                )
        has_entries = self.batch_table.rowCount() > 0
        self.batch_list_surface.setVisible(has_entries)
        self.batch_empty_state.setVisible(not has_entries)

    def _append_batch_entry(self, entry: BatchListEntry, *, status_label: str) -> None:
        row = self.batch_table.rowCount()
        self.batch_table.insertRow(row)
        values = (
            entry.name,
            entry.created_at.strftime("%Y-%m-%d"),
            str(entry.item_count),
            self._format_cents(entry.total_amount_cents),
            status_label,
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
            elif column == 4:
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
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
        self.batch_mark_submitted_button = QPushButton("批量标记已提交")
        self.batch_mark_submitted_button.clicked.connect(self._mark_batch_submitted)
        header.addWidget(self.batch_mark_submitted_button)
        self.batch_mark_reimbursed_button = QPushButton("批量标记已报销")
        self.batch_mark_reimbursed_button.clicked.connect(self._mark_batch_reimbursed)
        header.addWidget(self.batch_mark_reimbursed_button)
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
        self.batch_detail_table.setSelectionMode(
            QTableWidget.SelectionMode.NoSelection
        )
        self.batch_detail_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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
        self.back_to_batch_list_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.back_to_batch_list_button.clicked.connect(self._show_batch_list)
        layout.addWidget(self.back_to_batch_list_button, 0, Qt.AlignmentFlag.AlignLeft)

        header = QHBoxLayout()
        header.setSpacing(16)
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
        layout.addLayout(header)

        overview = QFrame()
        overview.setObjectName("batchDetailOverview")
        overview_layout = QHBoxLayout(overview)
        overview_layout.setContentsMargins(16, 14, 16, 14)
        overview_layout.setSpacing(32)
        overview_count = QVBoxLayout()
        overview_count.setSpacing(2)
        overview_count_title = QLabel("物品数量")
        overview_count_title.setObjectName("batchDetailMetricTitle")
        overview_count.addWidget(overview_count_title)
        self.batch_detail_overview_count_label = QLabel()
        self.batch_detail_overview_count_label.setObjectName("batchDetailMetricValue")
        overview_count.addWidget(self.batch_detail_overview_count_label)
        overview_layout.addLayout(overview_count)
        overview_amount = QVBoxLayout()
        overview_amount.setSpacing(2)
        overview_amount_title = QLabel("总金额")
        overview_amount_title.setObjectName("batchDetailMetricTitle")
        overview_amount.addWidget(overview_amount_title)
        self.batch_detail_overview_amount_label = QLabel()
        self.batch_detail_overview_amount_label.setObjectName("batchDetailMetricValue")
        overview_amount.addWidget(self.batch_detail_overview_amount_label)
        overview_layout.addLayout(overview_amount)
        overview_materials = QVBoxLayout()
        overview_materials.setSpacing(2)
        overview_materials_title = QLabel("材料完整度")
        overview_materials_title.setObjectName("batchDetailMetricTitle")
        overview_materials.addWidget(overview_materials_title)
        self.batch_detail_overview_materials_label = QLabel()
        self.batch_detail_overview_materials_label.setObjectName(
            "batchDetailMetricValue"
        )
        overview_materials.addWidget(self.batch_detail_overview_materials_label)
        overview_layout.addLayout(overview_materials)
        overview_layout.addStretch()
        layout.addWidget(overview)

        workflow = QFrame()
        workflow.setObjectName("batchDetailWorkflow")
        workflow_layout = QHBoxLayout(workflow)
        workflow_layout.setContentsMargins(16, 14, 16, 14)
        workflow_layout.setSpacing(16)
        workflow_information = QVBoxLayout()
        workflow_information.setSpacing(4)
        workflow_heading = QHBoxLayout()
        workflow_heading.setSpacing(8)
        workflow_title = QLabel("报销状态")
        workflow_title.setObjectName("sectionTitle")
        workflow_heading.addWidget(workflow_title)
        self.batch_detail_status_badge = QLabel()
        self.batch_detail_status_badge.setObjectName("batchDetailWorkflowBadge")
        workflow_heading.addWidget(self.batch_detail_status_badge)
        workflow_heading.addStretch()
        workflow_information.addLayout(workflow_heading)
        self.batch_detail_workflow_summary_label = QLabel()
        self.batch_detail_workflow_summary_label.setObjectName("batchDetailWorkflowSummary")
        workflow_information.addWidget(self.batch_detail_workflow_summary_label)
        workflow_layout.addLayout(workflow_information)
        workflow_layout.addStretch()
        self.batch_mark_submitted_button = QPushButton("标记批次已提交")
        self.batch_mark_submitted_button.setObjectName("primaryButton")
        self.batch_mark_submitted_button.clicked.connect(self._mark_batch_submitted)
        workflow_layout.addWidget(self.batch_mark_submitted_button)
        self.batch_mark_reimbursed_button = QPushButton("标记批次已报销")
        self.batch_mark_reimbursed_button.clicked.connect(self._mark_batch_reimbursed)
        workflow_layout.addWidget(self.batch_mark_reimbursed_button)
        self.batch_workflow_hint_label = QLabel()
        self.batch_workflow_hint_label.setObjectName("actionHint")
        workflow_layout.addWidget(self.batch_workflow_hint_label)
        layout.addWidget(workflow)

        items_title = QLabel("\u7269\u54c1")
        items_title.setObjectName("sectionTitle")
        layout.addWidget(items_title)

        self.batch_detail_list_surface = QFrame()
        self.batch_detail_list_surface.setObjectName("batchDetailListSurface")
        item_list_layout = QVBoxLayout(self.batch_detail_list_surface)
        item_list_layout.setContentsMargins(0, 0, 0, 0)
        self.batch_detail_table = QTableWidget(0, 5)
        self.batch_detail_table.setObjectName("batchDetailTable")
        self.batch_detail_table.setHorizontalHeaderLabels(
            ("\u7269\u54c1\u540d\u79f0", "\u91d1\u989d", "\u6750\u6599\u5b8c\u6574\u5ea6", "\u7f3a\u5931\u6750\u6599", "\u62a5\u9500\u72b6\u6001")
        )
        self.batch_detail_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.batch_detail_table.setSelectionMode(
            QTableWidget.SelectionMode.NoSelection
        )
        self.batch_detail_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.batch_detail_table.setAlternatingRowColors(True)
        self.batch_detail_table.setShowGrid(False)
        self.batch_detail_table.verticalHeader().setVisible(False)
        self.batch_detail_table.verticalHeader().setDefaultSectionSize(52)
        header_view = self.batch_detail_table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            header_view.setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        header_view.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.batch_detail_table.setColumnWidth(4, 96)
        self._make_table_rows_clickable(
            self.batch_detail_table, self._open_batch_detail_item
        )
        self._align_table_headers(
            self.batch_detail_table, right=(1,), center=(2, 4)
        )
        item_list_layout.addWidget(self.batch_detail_table)
        layout.addWidget(self.batch_detail_list_surface, 1)

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

        danger_area = QFrame()
        danger_area.setObjectName("batchDetailDangerArea")
        danger_layout = QHBoxLayout(danger_area)
        danger_layout.setContentsMargins(16, 12, 16, 12)
        danger_layout.setSpacing(12)
        danger_hint = QLabel("仅可删除没有物品的批次")
        danger_hint.setObjectName("settingsRowDetail")
        danger_layout.addWidget(danger_hint)
        danger_layout.addStretch()
        self.delete_batch_button = QPushButton("删除批次")
        self.delete_batch_button.setObjectName("dangerButton")
        self.delete_batch_button.clicked.connect(self._delete_current_batch)
        danger_layout.addWidget(self.delete_batch_button)
        layout.addWidget(danger_area)
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
        self.batch_detail_overview_count_label.setText(f"{entry.item_count} \u4e2a")
        self.batch_detail_overview_amount_label.setText(
            self._format_cents(entry.total_amount_cents)
        )
        workflow_counts = {status: 0 for status in ITEM_STATUS_LABELS}
        item_statuses: list[ReimbursementStatus] = []
        completed_materials = 0
        required_materials = 0
        if self._item_service is not None and self._completeness_service is not None:
            for item in self._item_service.list_items_by_batch(entry.id):
                item_statuses.append(item.status)
                completeness = self._completeness_service.calculate(item.id)
                completed_materials += completeness.completed_count
                required_materials += completeness.required_count
                item_status = self._display_item_status(
                    item.id, item.status, collection_complete=completeness.is_complete
                )
                if item_status in workflow_counts:
                    workflow_counts[item_status] += 1
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
                    ITEM_STATUS_LABELS.get(item_status, item_status),
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
                    if column == 3:
                        table_item.setToolTip(value)
                        if missing_materials:
                            table_item.setForeground(
                                QColor(IOS_LIGHT_TOKENS.warning_text)
                            )
                    self.batch_detail_table.setItem(row, column, table_item)
                status_badge = QLabel(ITEM_STATUS_LABELS.get(item_status, item_status))
                status_badge.setObjectName("batchDetailWorkflowBadge")
                status_badge.setProperty("status", item_status)
                status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.batch_detail_table.setCellWidget(row, 4, status_badge)

        self.batch_detail_workflow_summary_label.setText(
            " · ".join(
                f"{count} 个{ITEM_STATUS_LABELS[status]}"
                for status, count in workflow_counts.items()
                if count
            )
            or "暂无物品"
        )
        self.batch_detail_overview_materials_label.setText(
            f"{completed_materials} / {required_materials}"
            if required_materials
            else "—"
        )

        has_items = self.batch_detail_table.rowCount() > 0
        self._update_batch_workflow_actions(item_statuses)
        self._update_batch_status_badge(entry.id)
        self.batch_detail_list_surface.setVisible(has_items)
        self.batch_detail_empty_state.setVisible(not has_items)

    def _update_batch_status_badge(self, batch_id: int) -> None:
        """Show the persisted batch state next to the workflow heading."""
        status_label = ""
        raw_status = ""
        if self._batch_service is not None:
            for batch in self._batch_service.list_batches():
                if batch.id == batch_id:
                    raw_status = str(batch.status)
                    status_label = BATCH_STATUS_LABELS.get(raw_status, raw_status)
                    break
        self.batch_detail_status_badge.setText(status_label)
        self.batch_detail_status_badge.setProperty("status", raw_status)
        self.batch_detail_status_badge.setVisible(bool(status_label))
        self._refresh_dynamic_style(self.batch_detail_status_badge)

    def _update_batch_workflow_actions(
        self, statuses: list[ReimbursementStatus]
    ) -> None:
        """Offer only the one workflow step that is valid for every item."""
        service_ready = self._workflow_service is not None
        can_submit = bool(statuses) and all(
            status is ReimbursementStatus.COLLECTING for status in statuses
        )
        can_reimburse = bool(statuses) and all(
            status is ReimbursementStatus.SUBMITTED for status in statuses
        )
        self.batch_mark_submitted_button.setVisible(can_submit)
        self.batch_mark_submitted_button.setEnabled(can_submit and service_ready)
        self.batch_mark_reimbursed_button.setVisible(can_reimburse)
        self.batch_mark_reimbursed_button.setEnabled(can_reimburse and service_ready)
        self.batch_workflow_hint_label.setText(
            self._batch_workflow_hint(statuses, can_submit, can_reimburse)
        )

    @staticmethod
    def _batch_workflow_hint(
        statuses: list[ReimbursementStatus], can_submit: bool, can_reimburse: bool
    ) -> str:
        if not statuses or can_submit or can_reimburse:
            return ""
        if all(status is ReimbursementStatus.REIMBURSED for status in statuses):
            return "本批次已全部报销。"
        if all(status is ReimbursementStatus.ARCHIVED for status in statuses):
            return "本批次已归档。"
        return "物品状态不一致，请在物品详情里逐个推进。"

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

    def _mark_batch_submitted(self) -> None:
        self._advance_current_batch_workflow(ReimbursementStatus.SUBMITTED)

    def _mark_batch_reimbursed(self) -> None:
        self._advance_current_batch_workflow(ReimbursementStatus.REIMBURSED)

    def _advance_current_batch_workflow(
        self, target: ReimbursementStatus
    ) -> None:
        if self._workflow_service is None or not hasattr(self, "_current_batch_entry"):
            return
        batch_id = self._current_batch_entry.id
        try:
            self._workflow_service.advance_batch(batch_id, target)
        except SubmissionNotReadyError as error:
            if not self._confirm_unready_submission(error.items):
                return
            try:
                self._workflow_service.advance_batch(
                    batch_id, target, allow_unready_submission=True
                )
            except WorkflowServiceError as retry_error:
                QMessageBox.warning(self, "无法更新批次状态", str(retry_error))
                return
        except WorkflowServiceError as error:
            QMessageBox.warning(self, "无法更新批次状态", str(error))
            return
        self._refresh_after_workflow_change()

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
            sequence_number = self._item_service.allocate_sequence(
                self._current_batch_entry.id
            )
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
        layout.setSpacing(20)

        title_group = QVBoxLayout()
        title_group.setSpacing(4)
        title = QLabel("\u6982\u89c8")
        title.setObjectName("pageTitle")
        title_group.addWidget(title)

        subtitle = QLabel("\u4eca\u5929\u9700\u8981\u5904\u7406\u7684\u62a5\u9500\u6750\u6599")
        subtitle.setObjectName("dashboardPageSubtitle")
        title_group.addWidget(subtitle)
        layout.addLayout(title_group)

        summary_layout = DashboardStatsGrid()
        summary_layout.setMinimumHeight(104)
        self.dashboard_stats_grid = summary_layout
        summary_values = (
            ("\u5f85\u5904\u7406", self._dashboard_data.incomplete_count),
            ("\u53ef\u63d0\u4ea4", self._dashboard_data.complete_count),
            ("\u5df2\u63d0\u4ea4", self._dashboard_data.submitted_count),
            ("\u5df2\u62a5\u9500", self._dashboard_data.reimbursed_count),
        )
        self.dashboard_summary_labels: dict[str, QLabel] = {}
        for label, value in summary_values:
            card = QFrame()
            card.setObjectName("dashboardStatCard")
            card.setProperty(
                "semantic",
                {
                    "待处理": "warning",
                    "可提交": "accent",
                    "已提交": "secondary",
                    "已报销": "success",
                }[label],
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 12, 16, 12)
            card_layout.setSpacing(2)

            title_label = QLabel(label)
            title_label.setObjectName("dashboardStatTitle")
            value_label = QLabel(str(value))
            value_label.setObjectName("dashboardStatValue")
            value_label.setProperty("semantic", card.property("semantic"))
            hint_label = QLabel(
                {
                    "\u5f85\u5904\u7406": "\u4ecd\u6709\u4e8b\u9879\u5f85\u5904\u7406",
                    "\u53ef\u63d0\u4ea4": "\u6750\u6599\u5df2\u7ecf\u5c31\u7eea",
                    "\u5df2\u63d0\u4ea4": "\u7b49\u5f85\u62a5\u9500\u7ed3\u679c",
                    "\u5df2\u62a5\u9500": "\u62a5\u9500\u6d41\u7a0b\u5df2\u5b8c\u6210",
                }[label]
            )
            hint_label.setObjectName("dashboardStatHint")
            card_layout.addWidget(title_label)
            card_layout.addWidget(value_label)
            card_layout.addWidget(hint_label)
            card_layout.addStretch()
            self.dashboard_summary_labels[label] = value_label
            summary_layout.add_card(card)
        layout.addWidget(summary_layout)

        pending_title = QLabel("\u5f85\u5904\u7406")
        pending_title.setObjectName("sectionTitle")
        pending_header = QHBoxLayout()
        pending_header.setSpacing(8)
        self.dashboard_pending_summary = QLabel()
        self.dashboard_pending_summary.setObjectName("dashboardPendingSummary")
        pending_header.addWidget(pending_title)
        pending_header.addWidget(self.dashboard_pending_summary)
        pending_header.addStretch()
        layout.addLayout(pending_header)

        self.dashboard_pending_scroll = QScrollArea()
        self.dashboard_pending_scroll.setObjectName("dashboardPendingArea")
        self.dashboard_pending_scroll.setWidgetResizable(True)
        self.dashboard_pending_container = QWidget()
        pending_layout = QVBoxLayout(self.dashboard_pending_container)
        self.dashboard_pending_layout = pending_layout
        pending_layout.setContentsMargins(0, 0, 0, 0)
        pending_layout.setSpacing(8)

        self.dashboard_pending_items: list[QFrame] = []
        self._render_dashboard_pending_items()
        self.dashboard_pending_scroll.setWidget(self.dashboard_pending_container)
        layout.addWidget(self.dashboard_pending_scroll, 1)
        return page

    def refresh_dashboard(self) -> None:
        """Refresh the Dashboard after a local data-changing action."""
        if self._dashboard_service is None:
            return
        self._dashboard_data = self._dashboard_service.get_data()
        for label, value in (
            ("待处理", self._dashboard_data.incomplete_count),
            ("可提交", self._dashboard_data.complete_count),
            ("已提交", self._dashboard_data.submitted_count),
            ("已报销", self._dashboard_data.reimbursed_count),
        ):
            self.dashboard_summary_labels[label].setText(str(value))
        self._render_dashboard_pending_items()

    def _render_dashboard_pending_items(self) -> None:
        """Render the already-derived Dashboard attention list and empty state."""
        while self.dashboard_pending_layout.count():
            child = self.dashboard_pending_layout.takeAt(0)
            if child.widget() is not None:
                child.widget().deleteLater()
        self.dashboard_pending_items = []
        pending_count = len(self._dashboard_data.incomplete_items)
        self.dashboard_pending_summary.setText(f"还有 {pending_count} 个物品需要处理")
        if self._dashboard_data.incomplete_items:
            for item in self._dashboard_data.incomplete_items:
                row = self._build_dashboard_pending_item(item)
                self.dashboard_pending_items.append(row)
                self.dashboard_pending_layout.addWidget(row)
            self.dashboard_empty_state = QLabel()
            self.dashboard_empty_state.hide()
        else:
            self.dashboard_empty_state = QLabel(
                "当前没有待处理事项\n所有物品的提交材料都已准备完成。"
            )
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
        item_layout = QVBoxLayout(row)
        item_layout.setContentsMargins(16, 14, 16, 14)
        item_layout.setSpacing(10)

        identity_layout = QHBoxLayout()
        identity_layout.setSpacing(8)
        item_identity = QVBoxLayout()
        item_identity.setSpacing(2)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name = QLabel(dashboard_item.name)
        name.setObjectName("dashboardItemName")
        name_row.addWidget(name)
        state_chip = QLabel(
            "\u5f85\u8865\u6750\u6599"
            if dashboard_item.status_key == "incomplete"
            else "\u5f85\u751f\u6210\u51ed\u8bc1"
        )
        state_chip.setObjectName("dashboardStateChip")
        state_chip.setProperty("status", dashboard_item.status_key)
        name_row.addWidget(state_chip)
        name_row.addStretch()
        batch = QLabel(self._dashboard_batch_name(dashboard_item.item_id))
        batch.setObjectName("dashboardItemBatch")
        item_identity.addLayout(name_row)
        item_identity.addWidget(batch)
        identity_layout.addLayout(item_identity)
        identity_layout.addStretch()
        detail_button = QPushButton("\u67e5\u770b  \u203a")
        detail_button.setObjectName("dashboardItemDetailButton")
        detail_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        detail_button.setEnabled(
            self._item_service is not None and self._completeness_service is not None
        )
        detail_button.clicked.connect(
            lambda _checked=False, item_id=dashboard_item.item_id: self._open_dashboard_item_detail(
                item_id
            )
        )
        identity_layout.addWidget(detail_button)
        item_layout.addLayout(identity_layout)

        progress_layout = QHBoxLayout()
        progress_layout.setSpacing(16)
        progress_layout.addLayout(
            self._build_dashboard_progress(
                "\u6750\u6599\u6536\u96c6",
                dashboard_item.completed_count,
                dashboard_item.required_count,
                "dashboardCollectionProgress",
            ),
            1,
        )

        submission = self._dashboard_submission_progress(dashboard_item.item_id)
        if submission is not None:
            progress_layout.addLayout(
                self._build_dashboard_progress(
                    "\u63d0\u4ea4\u6750\u6599",
                    submission[0],
                    submission[1],
                    "dashboardSubmissionProgress",
                ),
                1,
            )
        item_layout.addLayout(progress_layout)
        missing = QLabel(
            f"\u7f3a\u5c11\uff1a{'\u3001'.join(dashboard_item.missing_materials)}"
            if dashboard_item.missing_materials
            else "\u6750\u6599\u5df2\u9f50\uff0c\u53ef\u63d0\u4ea4"
        )
        missing.setObjectName("dashboardMissing")
        missing.setWordWrap(False)
        missing.setToolTip(missing.text())
        item_layout.addWidget(missing)
        return row

    @staticmethod
    def _build_dashboard_progress(
        title: str, completed_count: int, required_count: int, object_name: str
    ) -> QVBoxLayout:
        progress_layout = QVBoxLayout()
        progress_layout.setSpacing(4)
        label_layout = QHBoxLayout()
        label_layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("dashboardProgressLabel")
        value_label = QLabel(f"{completed_count} / {required_count}")
        value_label.setObjectName("dashboardProgressValue")
        label_layout.addWidget(title_label)
        label_layout.addStretch()
        label_layout.addWidget(value_label)
        progress = QProgressBar()
        progress.setObjectName(object_name)
        progress.setTextVisible(False)
        progress.setRange(0, max(required_count, 1))
        progress.setValue(completed_count)
        progress.setProperty(
            "semantic",
            "success"
            if required_count > 0 and completed_count >= required_count
            else "accent",
        )
        progress_layout.addLayout(label_layout)
        progress_layout.addWidget(progress)
        return progress_layout

    def _open_dashboard_item_detail(self, item_id: int) -> None:
        """Open an existing Item Detail without duplicating its navigation flow."""
        if self._item_service is None or self._completeness_service is None:
            return
        self._item_detail_return_page_index = 0
        self._populate_item_detail(item_id)
        self.pages.setCurrentIndex(ITEM_DETAIL_PAGE_INDEX)

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

    def _dashboard_submission_progress(self, item_id: int) -> tuple[int, int] | None:
        """Reuse SubmissionReadinessService only when it was already injected."""
        if self._submission_readiness_service is None:
            return None
        try:
            readiness = self._submission_readiness_service.calculate(item_id)
        except (ItemNotFoundError, SQLAlchemyError):
            logger.exception("Failed to load Dashboard submission progress")
            return None
        return readiness.completed_count, readiness.required_count

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
