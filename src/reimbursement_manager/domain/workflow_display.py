"""Display-only workflow states derived from material readiness.

``ReimbursementStatus`` is the persisted reimbursement process state and stays
independent from material completeness.  Lists still need one label that tells
the user what is actually left to do, so these states are derived at render
time and never written back into ``items.status``.
"""

from __future__ import annotations

from reimbursement_manager.domain.enums import ReimbursementStatus


READY_STATUS = "ready"
"""Submission package complete: the Item can be marked as submitted."""

INCOMPLETE_STATUS = "incomplete"
"""Source material is still missing."""

PENDING_PAYMENT_STATUS = "pending_payment"
"""Source material is complete, but the submission package is not."""


def display_status(
    status: ReimbursementStatus,
    *,
    submission_ready: bool,
    collection_complete: bool | None = None,
) -> str:
    """Return the status key to show for one Item.

    While an Item is still collecting, the label distinguishes the two very
    different jobs a user may have to do: upload source material, or generate
    the merged payment screenshot.  Any later process state (submitted,
    reimbursed, archived) wins, so deleting an attachment never rewinds a
    submitted Item.
    """
    if status is not ReimbursementStatus.COLLECTING:
        return str(status)
    if submission_ready:
        return READY_STATUS
    if collection_complete is False:
        return INCOMPLETE_STATUS
    if collection_complete is True:
        return PENDING_PAYMENT_STATUS
    return str(status)
