from __future__ import annotations

from dataclasses import dataclass

from reimbursement_manager.services.completeness_service import CompletenessService
from reimbursement_manager.services.item_service import ItemService
from reimbursement_manager.services.submission_readiness_service import SubmissionReadinessService


@dataclass(frozen=True, slots=True)
class PendingMaterialItem:
    """One Item that still needs source or final-submission material."""

    item_id: int
    item_name: str
    batch_name: str
    collection_completed_count: int
    collection_required_count: int
    missing_collection_materials: tuple[str, ...]
    submission_completed_count: int
    submission_required_count: int
    missing_submission_materials: tuple[str, ...]


class PendingMaterialsService:
    """Build the small derived data set for the pending-materials page."""

    def __init__(
        self,
        item_service: ItemService,
        completeness_service: CompletenessService,
        submission_readiness_service: SubmissionReadinessService,
    ) -> None:
        self._item_service = item_service
        self._completeness_service = completeness_service
        self._submission_readiness_service = submission_readiness_service

    def list_pending_items(self) -> list[PendingMaterialItem]:
        """Return Items whose collection or submission readiness is incomplete."""
        pending_items: list[PendingMaterialItem] = []
        for item in self._item_service.search_items():
            collection = self._completeness_service.calculate(item.id)
            submission = self._submission_readiness_service.calculate(item.id)
            if collection.is_complete and submission.is_ready:
                continue

            loaded_item = self._item_service.get_item(item.id)
            pending_items.append(
                PendingMaterialItem(
                    item_id=item.id,
                    item_name=item.name,
                    batch_name=loaded_item.batch.name,
                    collection_completed_count=collection.completed_count,
                    collection_required_count=collection.required_count,
                    missing_collection_materials=tuple(
                        material.name for material in collection.missing
                    ),
                    submission_completed_count=submission.completed_count,
                    submission_required_count=submission.required_count,
                    missing_submission_materials=tuple(
                        material.name for material in submission.missing
                    ),
                )
            )
        return pending_items
