from __future__ import annotations

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
from reimbursement_manager.services.storage_path_service import StoragePathService


@dataclass(frozen=True, slots=True)
class MissingMaterial:
    material_type_id: int
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class CompletenessResult:
    required_count: int
    completed_count: int
    percentage: int
    is_complete: bool
    missing: tuple[MissingMaterial, ...]


class CompletenessService:
    """Derive Item material completeness from requirements and real files."""

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

    def calculate(self, item_id: int) -> CompletenessResult:
        with self._database.transaction() as session:
            item = ItemRepository(session).get_by_id_with_requirements(item_id)
            if item is None:
                raise ItemNotFoundError(item_id)

            attachment_repository = AttachmentRepository(session)
            available_material_type_ids: set[int] = set()
            for attachment in attachment_repository.list_by_item(item_id):
                health = self._get_attachment_health(attachment)
                if attachment.health is not health:
                    attachment.health = health
                    attachment_repository.update(attachment)
                if not attachment.is_derived and health is AttachmentHealth.OK:
                    available_material_type_ids.add(attachment.material_type_id)

            required_requirements = [
                requirement
                for requirement in item.requirements
                if requirement.required
            ]
            missing = tuple(
                MissingMaterial(
                    material_type_id=requirement.material_type_id,
                    code=requirement.material_type.code,
                    name=requirement.material_type.name,
                )
                for requirement in required_requirements
                if requirement.material_type_id not in available_material_type_ids
            )
            required_count = len(required_requirements)
            completed_count = required_count - len(missing)
            percentage = (
                100
                if required_count == 0
                else completed_count * 100 // required_count
            )
            return CompletenessResult(
                required_count=required_count,
                completed_count=completed_count,
                percentage=percentage,
                is_complete=not missing,
                missing=missing,
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
