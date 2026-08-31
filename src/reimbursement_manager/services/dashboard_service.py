from __future__ import annotations

from dataclasses import dataclass

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.repositories import ItemRepository
from reimbursement_manager.domain import ReimbursementStatus
from reimbursement_manager.services.completeness_service import CompletenessService
from reimbursement_manager.services.submission_readiness_service import (
    SubmissionReadinessService,
)


@dataclass(frozen=True, slots=True)
class IncompleteDashboardItem:
    item_id: int
    name: str
    completed_count: int
    required_count: int
    missing_materials: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DashboardData:
    incomplete_count: int
    complete_count: int
    submitted_count: int
    reimbursed_count: int
    incomplete_items: tuple[IncompleteDashboardItem, ...]


class DashboardService:
    """Provide the small, derived data set required by the Dashboard."""

    def __init__(
        self,
        database: DatabaseManager,
        completeness_service: CompletenessService,
        submission_readiness_service: SubmissionReadinessService | None = None,
    ) -> None:
        self._database = database
        self._completeness_service = completeness_service
        self._submission_readiness_service = submission_readiness_service

    def get_data(self) -> DashboardData:
        with self._database.transaction() as session:
            items = ItemRepository(session).list()

        incomplete_items: list[IncompleteDashboardItem] = []
        complete_count = 0
        submitted_count = 0
        reimbursed_count = 0
        for item in items:
            completeness = self._completeness_service.calculate(item.id)
            if (
                item.status is ReimbursementStatus.COLLECTING
                and self._is_ready_to_submit(item.id, completeness.is_complete)
            ):
                complete_count += 1
            if not completeness.is_complete:
                incomplete_items.append(
                    IncompleteDashboardItem(
                        item_id=item.id,
                        name=item.name,
                        completed_count=completeness.completed_count,
                        required_count=completeness.required_count,
                        missing_materials=tuple(
                            material.name for material in completeness.missing
                        ),
                    )
                )

            if item.status is ReimbursementStatus.SUBMITTED:
                submitted_count += 1
            elif item.status is ReimbursementStatus.REIMBURSED:
                reimbursed_count += 1

        return DashboardData(
            incomplete_count=len(incomplete_items),
            complete_count=complete_count,
            submitted_count=submitted_count,
            reimbursed_count=reimbursed_count,
            incomplete_items=tuple(incomplete_items),
        )

    def _is_ready_to_submit(self, item_id: int, fallback: bool) -> bool:
        if self._submission_readiness_service is None:
            return fallback
        return self._submission_readiness_service.calculate(item_id).is_ready
