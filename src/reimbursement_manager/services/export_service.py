from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tempfile
import zipfile

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Attachment, Item, ReimbursementBatch
from reimbursement_manager.database.repositories import (
    AttachmentRepository,
    BatchRepository,
    ItemRepository,
    MaterialTypeRepository,
)
from reimbursement_manager.domain import AttachmentHealth
from reimbursement_manager.services.file_service import FileService
from reimbursement_manager.services.item_service import ItemNotFoundError
from reimbursement_manager.services.naming_service import NamingService
from reimbursement_manager.services.payment_screenshot_merge_service import (
    is_merged_payment_screenshot,
)
from reimbursement_manager.services.storage_path_service import StoragePathService
from reimbursement_manager.services.submission_readiness_service import (
    SubmissionReadinessService,
)


PHYSICAL_PHOTO_CODE = "physical_photo"
INVOICE_CODE = "invoice"
PAYMENT_SCREENSHOT_CODE = "payment_screenshot"

_EXPORT_MATERIAL_NAMES = {
    PHYSICAL_PHOTO_CODE: "实物图",
    INVOICE_CODE: "发票",
    PAYMENT_SCREENSHOT_CODE: "支付截图",
}


class ExportServiceError(Exception):
    """Base exception for recoverable final-material export failures."""


class SubmissionMaterialsIncompleteError(ExportServiceError, ValueError):
    def __init__(self, missing_material_names: tuple[str, ...]) -> None:
        self.missing_material_names = missing_material_names
        super().__init__(
            "当前提交材料不完整：缺少" + "、".join(missing_material_names)
        )


class ExportTargetExistsError(ExportServiceError, FileExistsError):
    def __init__(self, destination: Path) -> None:
        self.destination = destination
        super().__init__(
            f"目标导出目录已存在，请选择其他目录或先删除旧导出结果：{destination}"
        )


class ExportCleanupError(ExportServiceError):
    def __init__(self, temporary_directory: Path, operation_error: Exception) -> None:
        self.temporary_directory = temporary_directory
        self.operation_error = operation_error
        super().__init__(f"导出失败且无法清理临时目录：{temporary_directory}")


class EmptyBatchExportError(ExportServiceError, ValueError):
    """Raised when a batch has no Items to export."""

    def __init__(self, batch_id: int) -> None:
        self.batch_id = batch_id
        super().__init__("The batch has no Items available for export.")


@dataclass(frozen=True, slots=True)
class IncompleteBatchExportItem:
    item_id: int
    sequence_number: int
    item_name: str
    missing_material_names: tuple[str, ...]


class BatchSubmissionMaterialsIncompleteError(ExportServiceError, ValueError):
    """Raised before batch export when any Item lacks submission materials."""

    def __init__(self, incomplete_items: tuple[IncompleteBatchExportItem, ...]) -> None:
        self.incomplete_items = incomplete_items
        super().__init__("The batch contains Items with incomplete submission materials.")


@dataclass(frozen=True, slots=True)
class ItemExportResult:
    item_id: int
    output_directory: Path
    exported_files: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class BatchExportResult:
    batch_id: int
    output_path: Path
    item_count: int
    file_count: int
    forced: bool = False
    incomplete_items: tuple[IncompleteBatchExportItem, ...] = ()
    report_path: Path | None = None
    export_format: str = "directory"


@dataclass(frozen=True, slots=True)
class _ExportFile:
    attachment: Attachment
    material_code: str
    file_index: int


class ExportService:
    """Copy one ready Item's final submission materials into a new directory."""

    def __init__(
        self,
        database: DatabaseManager,
        storage_path_service: StoragePathService,
        *,
        submission_readiness_service: SubmissionReadinessService | None = None,
        file_service: FileService | None = None,
        naming_service: NamingService | None = None,
    ) -> None:
        self._database = database
        self._storage_path_service = storage_path_service
        self._submission_readiness_service = (
            submission_readiness_service
            or SubmissionReadinessService(database, storage_path_service)
        )
        self._file_service = file_service or FileService()
        self._naming_service = naming_service or NamingService()

    def export_item(self, item_id: int, destination_dir: Path) -> ItemExportResult:
        """Export final files atomically without modifying archive files or data."""
        readiness = self._submission_readiness_service.calculate(item_id)
        if not readiness.is_ready:
            raise SubmissionMaterialsIncompleteError(
                tuple(material.name for material in readiness.missing)
            )

        item, files = self._load_export_files(item_id)
        destination_root = Path(destination_dir).expanduser().resolve()
        output_directory = destination_root / self._item_directory_name(
            item.sequence_number, item.name
        )
        if output_directory.exists():
            raise ExportTargetExistsError(output_directory)

        self._file_service.ensure_directory(destination_root)
        temporary_directory: Path | None = Path(
            tempfile.mkdtemp(
                dir=destination_root,
                prefix=f".tmp_{output_directory.name}_",
            )
        )
        try:
            exported_names = self._export_item_to_directory(
                item, files, temporary_directory
            )

            os.replace(temporary_directory, output_directory)
            temporary_directory = None
            return ItemExportResult(
                item_id=item_id,
                output_directory=output_directory,
                exported_files=tuple(
                    output_directory / filename for filename in exported_names
                ),
            )
        except Exception as operation_error:
            if temporary_directory is not None and temporary_directory.exists():
                try:
                    shutil.rmtree(temporary_directory)
                except OSError as cleanup_error:
                    raise ExportCleanupError(
                        temporary_directory, operation_error
                    ) from cleanup_error
            raise

    def export_batch(
        self, batch_id: int, destination_dir: Path, *, force: bool = False
    ) -> BatchExportResult:
        """Export every ready Item in a batch as one atomic directory copy."""
        batch, items = self._load_batch_items(batch_id)
        if not items:
            raise EmptyBatchExportError(batch_id)

        incomplete_items = self._find_incomplete_batch_items(items)
        if incomplete_items and not force:
            raise BatchSubmissionMaterialsIncompleteError(incomplete_items)

        destination_root = Path(destination_dir).expanduser().resolve()
        output_directory = destination_root / self._batch_directory_name(batch.name)
        if output_directory.exists():
            raise ExportTargetExistsError(output_directory)

        temporary_directory = self._create_temporary_batch_directory(
            destination_root, output_directory.name
        )
        try:
            file_count, report_path = self._write_batch_export_directory(
                temporary_directory, batch, items, force, incomplete_items
            )

            os.replace(temporary_directory, output_directory)
            temporary_directory = None
            return BatchExportResult(
                batch_id=batch_id,
                output_path=output_directory,
                item_count=len(items),
                file_count=file_count,
                forced=force,
                incomplete_items=incomplete_items,
                report_path=(
                    output_directory / report_path.name
                    if report_path is not None
                    else None
                ),
            )
        except Exception as operation_error:
            self._cleanup_temporary_directory(temporary_directory, operation_error)
            raise

    def export_batch_zip(
        self, batch_id: int, destination_dir: Path, *, force: bool = False
    ) -> BatchExportResult:
        """Export a batch to a ZIP using the same temporary directory export."""
        batch, items = self._load_batch_items(batch_id)
        if not items:
            raise EmptyBatchExportError(batch_id)

        incomplete_items = self._find_incomplete_batch_items(items)
        if incomplete_items and not force:
            raise BatchSubmissionMaterialsIncompleteError(incomplete_items)

        destination_root = Path(destination_dir).expanduser().resolve()
        batch_directory_name = self._batch_directory_name(batch.name)
        output_path = destination_root / f"{batch_directory_name}.zip"
        if output_path.exists():
            raise ExportTargetExistsError(output_path)

        temporary_directory = self._create_temporary_batch_directory(
            destination_root, batch_directory_name
        )
        temporary_zip = destination_root / f"{batch_directory_name}.tmp.zip"
        zip_created = False
        try:
            if temporary_zip.exists():
                raise ExportTargetExistsError(temporary_zip)
            file_count, _ = self._write_batch_export_directory(
                temporary_directory, batch, items, force, incomplete_items
            )
            zip_created = True
            self._write_batch_zip(
                temporary_directory, temporary_zip, batch_directory_name
            )
            if not temporary_zip.is_file():
                raise OSError(f"Temporary ZIP was not created: {temporary_zip}")
            os.replace(temporary_zip, output_path)
            zip_created = False
            shutil.rmtree(temporary_directory)
            return BatchExportResult(
                batch_id=batch_id,
                output_path=output_path,
                item_count=len(items),
                file_count=file_count,
                forced=force,
                incomplete_items=incomplete_items,
                export_format="zip",
            )
        except Exception as operation_error:
            if zip_created and temporary_zip.exists():
                try:
                    temporary_zip.unlink()
                except OSError as cleanup_error:
                    raise ExportCleanupError(temporary_directory, operation_error) from cleanup_error
            self._cleanup_temporary_directory(temporary_directory, operation_error)
            raise

    def _create_temporary_batch_directory(
        self, destination_root: Path, batch_directory_name: str
    ) -> Path:
        self._file_service.ensure_directory(destination_root)
        return Path(
            tempfile.mkdtemp(
                dir=destination_root,
                prefix=f".tmp_{batch_directory_name}_",
            )
        )

    def _write_batch_export_directory(
        self,
        temporary_directory: Path,
        batch: ReimbursementBatch,
        items: list[Item],
        force: bool,
        incomplete_items: tuple[IncompleteBatchExportItem, ...],
    ) -> tuple[int, Path | None]:
        file_count = 0
        for item in items:
            item_directory = temporary_directory / self._item_directory_name(
                item.sequence_number, item.name
            )
            item_directory.mkdir()
            loaded_item, files = self._load_export_files(item.id)
            file_count += len(
                self._export_item_to_directory(loaded_item, files, item_directory)
            )

        report_path: Path | None = None
        if force:
            report_path = temporary_directory / "导出结果.txt"
            self._write_force_export_report(report_path, batch.name, incomplete_items)
        return file_count, report_path

    @staticmethod
    def _write_batch_zip(
        source_directory: Path, temporary_zip: Path, root_name: str
    ) -> None:
        with zipfile.ZipFile(
            temporary_zip, mode="x", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for path in sorted(source_directory.rglob("*")):
                if path.is_file():
                    archive.write(path, Path(root_name) / path.relative_to(source_directory))

    @staticmethod
    def _cleanup_temporary_directory(
        temporary_directory: Path, operation_error: Exception
    ) -> None:
        if temporary_directory.exists():
            try:
                shutil.rmtree(temporary_directory)
            except OSError as cleanup_error:
                raise ExportCleanupError(
                    temporary_directory, operation_error
                ) from cleanup_error

    def _find_incomplete_batch_items(
        self, items: list[Item]
    ) -> tuple[IncompleteBatchExportItem, ...]:
        incomplete_items: list[IncompleteBatchExportItem] = []
        for item in items:
            readiness = self._submission_readiness_service.calculate(item.id)
            if not readiness.is_ready:
                incomplete_items.append(
                    IncompleteBatchExportItem(
                        item_id=item.id,
                        sequence_number=item.sequence_number,
                        item_name=item.name,
                        missing_material_names=tuple(
                            material.name for material in readiness.missing
                        ),
                    )
                )
        return tuple(incomplete_items)

    @staticmethod
    def _write_force_export_report(
        report_path: Path,
        batch_name: str,
        incomplete_items: tuple[IncompleteBatchExportItem, ...],
    ) -> None:
        lines = [
            f"批次：{batch_name}",
            "",
            "导出模式：强制导出",
            "",
        ]
        if incomplete_items:
            lines.extend(("以下物品提交材料不完整：", ""))
            for item in incomplete_items:
                lines.append(f"{item.sequence_number:03d} {item.item_name}")
                lines.append("缺少：")
                lines.extend(f"- {name}" for name in item.missing_material_names)
                lines.append("")
        else:
            lines.append("所有物品提交材料完整。")
        report_path.write_text("\n".join(lines), encoding="utf-8")

    def _load_batch_items(self, batch_id: int) -> tuple[ReimbursementBatch, list[Item]]:
        with self._database.transaction() as session:
            batch = BatchRepository(session).get_by_id(batch_id)
            if batch is None:
                raise BatchNotFoundError(batch_id)
            items = ItemRepository(session).list_by_batch(batch_id)
            return batch, sorted(items, key=lambda item: (item.sequence_number, item.id))

    def _export_item_to_directory(
        self,
        item: Item,
        files: list[_ExportFile],
        output_directory: Path,
    ) -> list[str]:
        exported_names: list[str] = []
        for export_file in files:
            source = self._storage_path_service.resolve_relative_path(
                export_file.attachment.relative_path
            )
            filename = self._naming_service.generate_filename(
                sequence_number=item.sequence_number,
                item_name=item.name,
                material_name=_EXPORT_MATERIAL_NAMES[export_file.material_code],
                file_index=export_file.file_index,
                extension=export_file.attachment.file_extension,
                existing_names=exported_names,
            )
            self._file_service.copy_file(source, output_directory / filename)
            exported_names.append(filename)
        return exported_names

    def _load_export_files(self, item_id: int) -> tuple[Item, list[_ExportFile]]:
        with self._database.transaction() as session:
            item = ItemRepository(session).get_by_id_with_requirements(item_id)
            if item is None:
                raise ItemNotFoundError(item_id)

            material_types = MaterialTypeRepository(session)
            material_type_ids = {
                code: material_type.id
                for code in (
                    PHYSICAL_PHOTO_CODE,
                    INVOICE_CODE,
                    PAYMENT_SCREENSHOT_CODE,
                )
                if (material_type := material_types.get_by_code(code)) is not None
            }
            attachments = AttachmentRepository(session).list_by_item(item_id)
            physical_photos = self._usable_originals(
                attachments, material_type_ids.get(PHYSICAL_PHOTO_CODE)
            )
            invoices = self._usable_originals(
                attachments, material_type_ids.get(INVOICE_CODE)
            )
            payment_material_type_id = material_type_ids.get(PAYMENT_SCREENSHOT_CODE)
            merged_payment = self._latest_usable_merged_payment(
                attachments, payment_material_type_id
            )

            files = [
                *(
                    _ExportFile(attachment, PHYSICAL_PHOTO_CODE, index)
                    for index, attachment in enumerate(physical_photos, start=1)
                ),
                *(
                    _ExportFile(attachment, INVOICE_CODE, index)
                    for index, attachment in enumerate(invoices, start=1)
                ),
            ]
            if merged_payment is not None:
                files.append(
                    _ExportFile(
                        merged_payment, PAYMENT_SCREENSHOT_CODE, file_index=1
                    )
                )
            return item, files

    @staticmethod
    def _usable_originals(
        attachments: list[Attachment], material_type_id: int | None
    ) -> list[Attachment]:
        if material_type_id is None:
            return []
        return [
            attachment
            for attachment in attachments
            if attachment.material_type_id == material_type_id
            and not attachment.is_derived
            and attachment.health is AttachmentHealth.OK
        ]

    @staticmethod
    def _latest_usable_merged_payment(
        attachments: list[Attachment], payment_material_type_id: int | None
    ) -> Attachment | None:
        if payment_material_type_id is None:
            return None
        candidates = [
            attachment
            for attachment in attachments
            if attachment.health is AttachmentHealth.OK
            and is_merged_payment_screenshot(
                attachment, payment_material_type_id=payment_material_type_id
            )
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda attachment: (attachment.created_at, attachment.id),
        )

    def _item_directory_name(self, sequence_number: int, item_name: str) -> str:
        if sequence_number <= 0:
            raise ValueError("sequence_number must be greater than zero")
        safe_item_name = self._naming_service.sanitize_component(
            item_name, fallback="未命名物品", max_length=116
        )
        return f"{sequence_number:03d}_{safe_item_name}"

    def _batch_directory_name(self, batch_name: str) -> str:
        return self._naming_service.sanitize_component(
            batch_name, fallback="unnamed-batch"
        )
