from __future__ import annotations

from dataclasses import dataclass

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Attachment
from reimbursement_manager.database.repositories import (
    AttachmentRepository,
    ItemRepository,
    MaterialTypeRepository,
)
from reimbursement_manager.domain import AttachmentHealth
from reimbursement_manager.services.file_service import FileService
from reimbursement_manager.services.item_service import ItemNotFoundError
from reimbursement_manager.services.payment_screenshot_merge_service import (
    is_merged_payment_screenshot,
)
from reimbursement_manager.services.storage_path_service import StoragePathService


PHYSICAL_PHOTO_CODE = "physical_photo"
INVOICE_CODE = "invoice"
PAYMENT_SCREENSHOT_CODE = "payment_screenshot"
MERGED_PAYMENT_SCREENSHOT_CODE = "merged_payment_screenshot"
MERGED_PAYMENT_SCREENSHOT_NAME = "合并支付截图"


@dataclass(frozen=True, slots=True)
class MissingSubmissionMaterial:
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class SubmissionReadinessResult:
    required_count: int
    completed_count: int
    is_ready: bool
    missing: tuple[MissingSubmissionMaterial, ...]


class SubmissionReadinessService:
    """Derive whether a normal purchase Item has its final submission files."""

    def __init__(
        self,
        database: DatabaseManager,
        storage_path_service: StoragePathService,
        *,
        file_service: FileService | None = None,
    ) -> None:
        self._database = database
        self._storage_path_service = storage_path_service
        self._file_service = file_service or FileService()

    def calculate(self, item_id: int) -> SubmissionReadinessResult:
        with self._database.transaction() as session:
            if ItemRepository(session).get_by_id(item_id) is None:
                raise ItemNotFoundError(item_id)

            material_types = MaterialTypeRepository(session)
            attachment_repository = AttachmentRepository(session)
            attachments = attachment_repository.list_by_item(item_id)
            self._refresh_attachment_health(attachments, attachment_repository)

            material_type_ids = {
                code: material_type.id
                for code in (
                    PHYSICAL_PHOTO_CODE,
                    INVOICE_CODE,
                    PAYMENT_SCREENSHOT_CODE,
                )
                if (material_type := material_types.get_by_code(code)) is not None
            }
            available = {
                code: any(
                    self._is_submission_attachment(
                        attachment,
                        code=code,
                        material_type_ids=material_type_ids,
                    )
                    for attachment in attachments
                )
                for code in (
                    PHYSICAL_PHOTO_CODE,
                    INVOICE_CODE,
                    MERGED_PAYMENT_SCREENSHOT_CODE,
                )
            }
            names = {
                PHYSICAL_PHOTO_CODE: self._material_name(
                    material_types, PHYSICAL_PHOTO_CODE
                ),
                INVOICE_CODE: self._material_name(material_types, INVOICE_CODE),
                MERGED_PAYMENT_SCREENSHOT_CODE: MERGED_PAYMENT_SCREENSHOT_NAME,
            }
            missing = tuple(
                MissingSubmissionMaterial(code=code, name=names[code])
                for code, is_available in available.items()
                if not is_available
            )
            required_count = len(available)
            completed_count = required_count - len(missing)
            return SubmissionReadinessResult(
                required_count=required_count,
                completed_count=completed_count,
                is_ready=not missing,
                missing=missing,
            )

    def _refresh_attachment_health(
        self,
        attachments: list[Attachment],
        repository: AttachmentRepository,
    ) -> None:
        for attachment in attachments:
            health = self._get_attachment_health(attachment)
            if attachment.health is not health:
                attachment.health = health
                repository.update(attachment)

    def _is_submission_attachment(
        self,
        attachment: Attachment,
        *,
        code: str,
        material_type_ids: dict[str, int],
    ) -> bool:
        if attachment.health is not AttachmentHealth.OK:
            return False
        if code == MERGED_PAYMENT_SCREENSHOT_CODE:
            payment_material_type_id = material_type_ids.get(
                PAYMENT_SCREENSHOT_CODE
            )
            return payment_material_type_id is not None and is_merged_payment_screenshot(
                attachment, payment_material_type_id=payment_material_type_id
            )
        material_type_id = material_type_ids.get(code)
        return (
            material_type_id is not None
            and attachment.material_type_id == material_type_id
            and not attachment.is_derived
        )

    def _get_attachment_health(self, attachment: Attachment) -> AttachmentHealth:
        try:
            absolute_path = self._storage_path_service.resolve_relative_path(
                attachment.relative_path
            )
            exists = self._file_service.file_exists(absolute_path)
        except (OSError, ValueError):
            exists = False
        return AttachmentHealth.OK if exists else AttachmentHealth.MISSING

    @staticmethod
    def _material_name(material_types: MaterialTypeRepository, code: str) -> str:
        material_type = material_types.get_by_code(code)
        return material_type.name if material_type is not None else code
