from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Attachment, MaterialRequirement
from reimbursement_manager.database.repositories import (
    AttachmentRepository,
    ItemRepository,
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
ORDER_SCREENSHOT_CODE = "order_screenshot"
MERGED_PAYMENT_SCREENSHOT_CODE = "merged_payment_screenshot"
MERGED_PAYMENT_SCREENSHOT_NAME = "合并支付截图"

#: Conventional order of the final submission package. Materials outside this
#: list follow in their own template order.
_BASE_SUBMISSION_ORDER = (
    PHYSICAL_PHOTO_CODE,
    INVOICE_CODE,
    PAYMENT_SCREENSHOT_CODE,
)


@dataclass(frozen=True, slots=True)
class MissingSubmissionMaterial:
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class SubmissionMaterial:
    """One entry of an Item's final submission package.

    ``merged_payment`` marks the derived screenshot that replaces both the
    order screenshot and the payment screenshot in the exported package.
    """

    code: str
    name: str
    material_type_id: int
    merged_payment: bool = False


@dataclass(frozen=True, slots=True)
class SubmissionReadinessResult:
    required_count: int
    completed_count: int
    is_ready: bool
    missing: tuple[MissingSubmissionMaterial, ...]


def supports_payment_merge(
    requirements: Iterable[MaterialRequirement],
) -> bool:
    """Return whether an Item can produce a merged payment screenshot.

    The merge joins the order screenshot with the payment screenshot, so it is
    only meaningful when the Item actually requires both of them.
    """
    required_codes = {
        requirement.material_type.code
        for requirement in requirements
        if requirement.required
    }
    return (
        ORDER_SCREENSHOT_CODE in required_codes
        and PAYMENT_SCREENSHOT_CODE in required_codes
    )


def build_submission_materials(
    requirements: Sequence[MaterialRequirement],
) -> tuple[SubmissionMaterial, ...]:
    """Derive the final submission package from an Item's own requirements.

    Templates are free to omit order or payment screenshots. Whatever an Item
    requires is what its submission package contains; the merged payment
    screenshot only exists when both of its sources are required.
    """
    required = sorted(
        (requirement for requirement in requirements if requirement.required),
        key=lambda requirement: (
            requirement.sort_order,
            requirement.material_type_id,
        ),
    )
    by_code = {
        requirement.material_type.code: requirement for requirement in required
    }
    merge_payment = supports_payment_merge(required)

    materials: list[SubmissionMaterial] = []
    for code in _BASE_SUBMISSION_ORDER:
        requirement = by_code.get(code)
        if requirement is None:
            continue
        if code == PAYMENT_SCREENSHOT_CODE and merge_payment:
            materials.append(
                SubmissionMaterial(
                    code=MERGED_PAYMENT_SCREENSHOT_CODE,
                    name=MERGED_PAYMENT_SCREENSHOT_NAME,
                    material_type_id=requirement.material_type_id,
                    merged_payment=True,
                )
            )
            continue
        materials.append(
            SubmissionMaterial(
                code=code,
                name=requirement.material_type.name,
                material_type_id=requirement.material_type_id,
            )
        )

    consumed_codes = set(_BASE_SUBMISSION_ORDER)
    if merge_payment:
        consumed_codes.add(ORDER_SCREENSHOT_CODE)
    for requirement in required:
        code = requirement.material_type.code
        if code in consumed_codes:
            continue
        materials.append(
            SubmissionMaterial(
                code=code,
                name=requirement.material_type.name,
                material_type_id=requirement.material_type_id,
            )
        )
    return tuple(materials)


class SubmissionReadinessService:
    """Derive whether an Item has the files its final submission package needs."""

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
            item = ItemRepository(session).get_by_id_with_requirements(item_id)
            if item is None:
                raise ItemNotFoundError(item_id)

            attachment_repository = AttachmentRepository(session)
            attachments = attachment_repository.list_by_item(item_id)
            self._refresh_attachment_health(attachments, attachment_repository)

            materials = build_submission_materials(item.requirements)
            missing = tuple(
                MissingSubmissionMaterial(code=material.code, name=material.name)
                for material in materials
                if not self._is_satisfied(material, attachments)
            )
            required_count = len(materials)
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

    @staticmethod
    def _is_satisfied(
        material: SubmissionMaterial,
        attachments: Sequence[Attachment],
    ) -> bool:
        return any(
            SubmissionReadinessService._is_submission_attachment(
                attachment, material
            )
            for attachment in attachments
        )

    @staticmethod
    def _is_submission_attachment(
        attachment: Attachment,
        material: SubmissionMaterial,
    ) -> bool:
        if attachment.health is not AttachmentHealth.OK:
            return False
        if attachment.material_type_id != material.material_type_id:
            return False
        if material.merged_payment:
            return is_merged_payment_screenshot(
                attachment, payment_material_type_id=material.material_type_id
            )
        return not attachment.is_derived

    def _get_attachment_health(self, attachment: Attachment) -> AttachmentHealth:
        try:
            absolute_path = self._storage_path_service.resolve_relative_path(
                attachment.relative_path
            )
            exists = self._file_service.file_exists(absolute_path)
        except (OSError, ValueError):
            exists = False
        return AttachmentHealth.OK if exists else AttachmentHealth.MISSING
