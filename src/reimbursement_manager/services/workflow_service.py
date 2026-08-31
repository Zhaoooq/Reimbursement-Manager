from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Item
from reimbursement_manager.database.repositories import BatchRepository, ItemRepository
from reimbursement_manager.domain import ReimbursementStatus
from reimbursement_manager.services.item_service import ItemNotFoundError
from reimbursement_manager.services.submission_readiness_service import SubmissionReadinessResult, SubmissionReadinessService


class WorkflowServiceError(Exception):
    """Base error for recoverable reimbursement workflow failures."""


class InvalidWorkflowTransitionError(WorkflowServiceError, ValueError):
    def __init__(self, current: ReimbursementStatus, target: ReimbursementStatus) -> None:
        super().__init__(f"Cannot transition from {current.value} to {target.value}.")


class WorkflowBatchNotFoundError(WorkflowServiceError, LookupError):
    pass


class EmptyWorkflowBatchError(WorkflowServiceError, ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SubmissionNotReadyItem:
    item_id: int
    item_name: str
    readiness: SubmissionReadinessResult


class SubmissionNotReadyError(WorkflowServiceError):
    def __init__(self, items: tuple[SubmissionNotReadyItem, ...]) -> None:
        super().__init__("Submission materials are not ready.")
        self.items = items


class WorkflowService:
    """Apply the explicit reimbursement workflow without changing material rules."""

    def __init__(self, database: DatabaseManager, submission_readiness_service: SubmissionReadinessService) -> None:
        self._database = database
        self._submission_readiness_service = submission_readiness_service

    def advance_item(self, item_id: int, *, allow_unready_submission: bool = False) -> Item:
        with self._database.transaction() as session:
            item = ItemRepository(session).get_by_id(item_id)
            if item is None:
                raise ItemNotFoundError(item_id)
            target = self._next_status(item.status)

        if target is ReimbursementStatus.SUBMITTED:
            self._ensure_submission_ready((item_id,), allow_unready_submission=allow_unready_submission)

        with self._database.transaction() as session:
            item = ItemRepository(session).get_by_id(item_id)
            if item is None:
                raise ItemNotFoundError(item_id)
            item.status = self._next_status(item.status)
            return item

    def advance_batch(self, batch_id: int, target: ReimbursementStatus, *, allow_unready_submission: bool = False) -> list[Item]:
        if target not in (ReimbursementStatus.SUBMITTED, ReimbursementStatus.REIMBURSED):
            raise ValueError("Batch workflow supports submitted or reimbursed only.")

        with self._database.transaction() as session:
            batch = BatchRepository(session).get_by_id(batch_id)
            if batch is None:
                raise WorkflowBatchNotFoundError(f"Batch {batch_id} does not exist.")
            items = ItemRepository(session).list_by_batch(batch_id)
            if not items:
                raise EmptyWorkflowBatchError(f"Batch {batch_id} has no items.")
            for item in items:
                self._validate_transition(item.status, target)

        if target is ReimbursementStatus.SUBMITTED:
            self._ensure_submission_ready(tuple(item.id for item in items), allow_unready_submission=allow_unready_submission)

        with self._database.transaction() as session:
            batch = BatchRepository(session).get_by_id(batch_id)
            if batch is None:
                raise WorkflowBatchNotFoundError(f"Batch {batch_id} does not exist.")
            items = ItemRepository(session).list_by_batch(batch_id)
            if not items:
                raise EmptyWorkflowBatchError(f"Batch {batch_id} has no items.")
            for item in items:
                self._validate_transition(item.status, target)
            for item in items:
                item.status = target
            batch.status = target
            now = datetime.now(timezone.utc)
            if target is ReimbursementStatus.SUBMITTED:
                batch.submitted_at = now
            else:
                batch.reimbursed_at = now
            return items

    def _ensure_submission_ready(self, item_ids: tuple[int, ...], *, allow_unready_submission: bool) -> None:
        incomplete = tuple(
            SubmissionNotReadyItem(item_id=item_id, item_name=self._item_name(item_id), readiness=readiness)
            for item_id in item_ids
            if not (readiness := self._submission_readiness_service.calculate(item_id)).is_ready
        )
        if incomplete and not allow_unready_submission:
            raise SubmissionNotReadyError(incomplete)

    def _item_name(self, item_id: int) -> str:
        with self._database.transaction() as session:
            item = ItemRepository(session).get_by_id(item_id)
            if item is None:
                raise ItemNotFoundError(item_id)
            return item.name

    @staticmethod
    def _next_status(current: ReimbursementStatus) -> ReimbursementStatus:
        transitions = {ReimbursementStatus.COLLECTING: ReimbursementStatus.SUBMITTED, ReimbursementStatus.SUBMITTED: ReimbursementStatus.REIMBURSED, ReimbursementStatus.REIMBURSED: ReimbursementStatus.ARCHIVED}
        try:
            return transitions[current]
        except KeyError as error:
            raise InvalidWorkflowTransitionError(current, current) from error

    @staticmethod
    def _validate_transition(current: ReimbursementStatus, target: ReimbursementStatus) -> None:
        if WorkflowService._next_status(current) is not target:
            raise InvalidWorkflowTransitionError(current, target)
