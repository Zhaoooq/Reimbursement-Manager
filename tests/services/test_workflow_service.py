from __future__ import annotations

from collections.abc import Iterator

import pytest

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Base, Item, ReimbursementBatch
from reimbursement_manager.database.repositories import BatchRepository, ItemRepository
from reimbursement_manager.domain import ReimbursementStatus
from reimbursement_manager.services import (
    InvalidWorkflowTransitionError,
    SubmissionNotReadyError,
    WorkflowService,
)
from reimbursement_manager.services.submission_readiness_service import (
    SubmissionReadinessResult,
)


class ReadinessStub:
    def __init__(self, ready_item_ids: set[int]) -> None:
        self._ready_item_ids = ready_item_ids

    def calculate(self, item_id: int) -> SubmissionReadinessResult:
        ready = item_id in self._ready_item_ids
        return SubmissionReadinessResult(
            required_count=3,
            completed_count=3 if ready else 2,
            is_ready=ready,
            missing=(),
        )


@pytest.fixture
def database() -> Iterator[DatabaseManager]:
    manager = DatabaseManager.in_memory()
    Base.metadata.create_all(manager.engine)
    try:
        yield manager
    finally:
        manager.dispose()


def _create_batch_with_items(database: DatabaseManager, count: int = 2) -> tuple[int, list[int]]:
    with database.transaction() as session:
        batch = BatchRepository(session).create(ReimbursementBatch(name="August"))
        items = [
            ItemRepository(session).create(
                Item(
                    batch_id=batch.id,
                    sequence_number=index,
                    name=f"Item {index}",
                    quantity=1,
                    total_amount_cents=100,
                )
            )
            for index in range(1, count + 1)
        ]
    return batch.id, [item.id for item in items]


def test_item_workflow_advances_in_order(database: DatabaseManager) -> None:
    _batch_id, item_ids = _create_batch_with_items(database, 1)
    service = WorkflowService(database, ReadinessStub(set(item_ids)))  # type: ignore[arg-type]

    assert service.advance_item(item_ids[0]).status is ReimbursementStatus.SUBMITTED
    assert service.advance_item(item_ids[0]).status is ReimbursementStatus.REIMBURSED
    assert service.advance_item(item_ids[0]).status is ReimbursementStatus.ARCHIVED

    with pytest.raises(InvalidWorkflowTransitionError):
        service.advance_item(item_ids[0])


def test_unready_submission_requires_explicit_override(database: DatabaseManager) -> None:
    _batch_id, item_ids = _create_batch_with_items(database, 1)
    service = WorkflowService(database, ReadinessStub(set()))  # type: ignore[arg-type]

    with pytest.raises(SubmissionNotReadyError):
        service.advance_item(item_ids[0])

    assert service.advance_item(
        item_ids[0], allow_unready_submission=True
    ).status is ReimbursementStatus.SUBMITTED


def test_batch_transition_rolls_back_when_any_item_cannot_transition(
    database: DatabaseManager,
) -> None:
    batch_id, item_ids = _create_batch_with_items(database)
    with database.transaction() as session:
        item = session.get(Item, item_ids[1])
        assert item is not None
        item.status = ReimbursementStatus.SUBMITTED

    service = WorkflowService(database, ReadinessStub(set(item_ids)))  # type: ignore[arg-type]

    with pytest.raises(InvalidWorkflowTransitionError):
        service.advance_batch(batch_id, ReimbursementStatus.SUBMITTED)

    with database.transaction() as session:
        statuses = [
            item.status for item in ItemRepository(session).list_by_batch(batch_id)
        ]
    assert statuses == [ReimbursementStatus.COLLECTING, ReimbursementStatus.SUBMITTED]


def test_batch_transition_updates_all_items_and_batch_timestamp(
    database: DatabaseManager,
) -> None:
    batch_id, item_ids = _create_batch_with_items(database)
    service = WorkflowService(database, ReadinessStub(set(item_ids)))  # type: ignore[arg-type]

    service.advance_batch(batch_id, ReimbursementStatus.SUBMITTED)
    service.advance_batch(batch_id, ReimbursementStatus.REIMBURSED)

    with database.transaction() as session:
        batch = BatchRepository(session).get_by_id(batch_id)
        assert batch is not None
        assert batch.status is ReimbursementStatus.REIMBURSED
        assert batch.submitted_at is not None
        assert batch.reimbursed_at is not None
        assert all(
            item.status is ReimbursementStatus.REIMBURSED
            for item in ItemRepository(session).list_by_batch(batch_id)
        )
