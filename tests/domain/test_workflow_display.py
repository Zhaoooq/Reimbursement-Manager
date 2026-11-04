import pytest

from reimbursement_manager.domain import (
    INCOMPLETE_STATUS,
    PENDING_PAYMENT_STATUS,
    READY_STATUS,
    ReimbursementStatus,
    display_status,
)


def test_collecting_item_with_complete_submission_package_is_ready() -> None:
    assert (
        display_status(ReimbursementStatus.COLLECTING, submission_ready=True)
        == READY_STATUS
    )


def test_collecting_item_with_missing_materials_stays_collecting() -> None:
    assert (
        display_status(ReimbursementStatus.COLLECTING, submission_ready=False)
        == ReimbursementStatus.COLLECTING.value
    )


def test_missing_source_material_is_reported_as_incomplete() -> None:
    assert (
        display_status(
            ReimbursementStatus.COLLECTING,
            submission_ready=False,
            collection_complete=False,
        )
        == INCOMPLETE_STATUS
    )


def test_complete_source_material_without_submission_package_is_pending_payment() -> (
    None
):
    assert (
        display_status(
            ReimbursementStatus.COLLECTING,
            submission_ready=False,
            collection_complete=True,
        )
        == PENDING_PAYMENT_STATUS
    )


def test_submission_ready_wins_over_collection_state() -> None:
    assert (
        display_status(
            ReimbursementStatus.COLLECTING,
            submission_ready=True,
            collection_complete=False,
        )
        == READY_STATUS
    )


@pytest.mark.parametrize(
    "status",
    [
        ReimbursementStatus.SUBMITTED,
        ReimbursementStatus.REIMBURSED,
        ReimbursementStatus.ARCHIVED,
    ],
)
def test_later_workflow_states_never_fall_back_to_ready(
    status: ReimbursementStatus,
) -> None:
    assert display_status(status, submission_ready=True) == status.value


def test_ready_status_is_not_a_persisted_workflow_state() -> None:
    assert READY_STATUS not in ReimbursementStatus.__members__
    assert all(member.value != READY_STATUS for member in ReimbursementStatus)
