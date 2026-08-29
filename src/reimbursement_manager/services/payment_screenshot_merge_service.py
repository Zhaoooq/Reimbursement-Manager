from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Attachment
from reimbursement_manager.database.repositories import (
    AttachmentRepository,
    ItemRepository,
    MaterialTypeRepository,
)
from reimbursement_manager.domain import AttachmentHealth
from reimbursement_manager.services.file_service import FileService
from reimbursement_manager.services.hash_service import HashService
from reimbursement_manager.services.image_merge_service import ImageMergeService
from reimbursement_manager.services.item_service import ItemNotFoundError
from reimbursement_manager.services.naming_service import NamingService
from reimbursement_manager.services.storage_path_service import StoragePathService


IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png"})
ORDER_SCREENSHOT_CODE = "order_screenshot"
PAYMENT_SCREENSHOT_CODE = "payment_screenshot"
MERGED_PAYMENT_MATERIAL_NAME = "支付截图_合并"
MERGED_PAYMENT_ORIGINAL_FILENAME = "订单截图 + 支付截图"


class PaymentScreenshotMergeError(Exception):
    """Base exception for recoverable screenshot merge failures."""


class RequiredScreenshotMissingError(PaymentScreenshotMergeError):
    def __init__(self, material_code: str) -> None:
        messages = {
            ORDER_SCREENSHOT_CODE: "请先上传订单截图。",
            PAYMENT_SCREENSHOT_CODE: "请先上传支付截图。",
        }
        super().__init__(messages[material_code])
        self.material_code = material_code


class UnsupportedMergeSourceError(PaymentScreenshotMergeError):
    def __init__(self, material_code: str) -> None:
        messages = {
            ORDER_SCREENSHOT_CODE: "当前订单截图不是可直接拼接的图片，请使用 JPG/PNG 截图。",
            PAYMENT_SCREENSHOT_CODE: "当前支付截图不是可直接拼接的图片，请使用 JPG/PNG 截图。",
        }
        super().__init__(messages[material_code])
        self.material_code = material_code


@dataclass(frozen=True, slots=True)
class MergeAvailability:
    can_generate: bool
    message: str


class PaymentScreenshotMergeService:
    """Persist a derived payment screenshot from an Item's latest images."""

    def __init__(
        self,
        database: DatabaseManager,
        storage_path_service: StoragePathService,
        *,
        image_merge_service: ImageMergeService | None = None,
        file_service: FileService | None = None,
        hash_service: HashService | None = None,
        naming_service: NamingService | None = None,
    ) -> None:
        self._database = database
        self._storage_path_service = storage_path_service
        self._image_merge_service = image_merge_service or ImageMergeService()
        self._file_service = file_service or FileService()
        self._hash_service = hash_service or HashService()
        self._naming_service = naming_service or NamingService()

    def get_availability(self, item_id: int) -> MergeAvailability:
        try:
            with self._database.transaction() as session:
                item = ItemRepository(session).get_by_id(item_id)
                if item is None:
                    raise ItemNotFoundError(item_id)
                material_types = MaterialTypeRepository(session)
                attachment_repository = AttachmentRepository(session)
                for code in (ORDER_SCREENSHOT_CODE, PAYMENT_SCREENSHOT_CODE):
                    material_type = material_types.get_by_code(code)
                    if material_type is None:
                        raise RequiredScreenshotMissingError(code)
                    self._latest_usable_image(
                        attachment_repository, item_id, material_type.id, code
                    )
        except (RequiredScreenshotMissingError, UnsupportedMergeSourceError) as error:
            return MergeAvailability(False, str(error))
        return MergeAvailability(True, "")

    def generate(self, item_id: int) -> Attachment:
        output_path: Path | None = None
        try:
            with self._database.transaction() as session:
                item = ItemRepository(session).get_by_id_with_requirements(item_id)
                if item is None:
                    raise ItemNotFoundError(item_id)
                material_types = MaterialTypeRepository(session)
                attachment_repository = AttachmentRepository(session)
                order_type = material_types.get_by_code(ORDER_SCREENSHOT_CODE)
                payment_type = material_types.get_by_code(PAYMENT_SCREENSHOT_CODE)
                if order_type is None:
                    raise RequiredScreenshotMissingError(ORDER_SCREENSHOT_CODE)
                if payment_type is None:
                    raise RequiredScreenshotMissingError(PAYMENT_SCREENSHOT_CODE)

                order_attachment = self._latest_usable_image(
                    attachment_repository, item_id, order_type.id, ORDER_SCREENSHOT_CODE
                )
                payment_attachment = self._latest_usable_image(
                    attachment_repository, item_id, payment_type.id, PAYMENT_SCREENSHOT_CODE
                )
                order_path = self._storage_path_service.resolve_relative_path(
                    order_attachment.relative_path
                )
                payment_path = self._storage_path_service.resolve_relative_path(
                    payment_attachment.relative_path
                )
                item_directory = self._storage_path_service.get_item_directory(
                    batch_name=item.batch.name,
                    batch_date=item.batch.created_at.date(),
                    sequence_number=item.sequence_number,
                    item_name=item.name,
                )
                existing_names = self._file_service.list_file_names(item_directory)
                derived_count = sum(
                    attachment.is_derived
                    for attachment in attachment_repository.list_by_material(
                        item_id=item_id, material_type_id=payment_type.id
                    )
                )
                stored_filename = self._naming_service.generate_filename(
                    sequence_number=item.sequence_number,
                    item_name=item.name,
                    material_name=MERGED_PAYMENT_MATERIAL_NAME,
                    file_index=derived_count + 1,
                    extension="png",
                    existing_names=existing_names,
                )
                relative_path = self._storage_path_service.get_attachment_relative_path(
                    batch_name=item.batch.name,
                    batch_date=item.batch.created_at.date(),
                    sequence_number=item.sequence_number,
                    item_name=item.name,
                    stored_filename=stored_filename,
                )
                output_path = self._storage_path_service.resolve_relative_path(relative_path)
                self._image_merge_service.merge(
                    order_image_path=order_path,
                    payment_image_path=payment_path,
                    output_path=output_path,
                )
                attachment = attachment_repository.create(
                    Attachment(
                        item_id=item_id,
                        material_type_id=payment_type.id,
                        original_filename=MERGED_PAYMENT_ORIGINAL_FILENAME,
                        stored_filename=stored_filename,
                        relative_path=relative_path.as_posix(),
                        file_extension=".png",
                        file_size=self._file_service.get_file_size(output_path),
                        sha256=self._hash_service.calculate_sha256(output_path),
                        is_derived=True,
                        health=AttachmentHealth.OK,
                    )
                )
            return attachment
        except Exception:
            if output_path is not None and self._file_service.file_exists(output_path):
                self._file_service.delete_file(output_path)
            raise

    def _latest_usable_image(
        self,
        repository: AttachmentRepository,
        item_id: int,
        material_type_id: int,
        material_code: str,
    ) -> Attachment:
        attachments = [
            attachment
            for attachment in repository.list_by_material(
                item_id=item_id, material_type_id=material_type_id
            )
            if not attachment.is_derived
        ]
        if not attachments:
            raise RequiredScreenshotMissingError(material_code)
        image_attachments = [
            attachment
            for attachment in attachments
            if attachment.file_extension.lower() in IMAGE_EXTENSIONS
            and self._file_service.file_exists(
                self._storage_path_service.resolve_relative_path(
                    attachment.relative_path
                )
            )
        ]
        if not image_attachments:
            raise UnsupportedMergeSourceError(material_code)
        return image_attachments[-1]


def is_merged_payment_screenshot(
    attachment: Attachment, *, payment_material_type_id: int
) -> bool:
    """Return whether an attachment was created by this payment merge flow."""
    return (
        attachment.material_type_id == payment_material_type_id
        and attachment.is_derived
        and attachment.original_filename == MERGED_PAYMENT_ORIGINAL_FILENAME
    )
