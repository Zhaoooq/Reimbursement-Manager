from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reimbursement_manager.database.models import Item, ReimbursementBatch
from reimbursement_manager.database.repositories.base import _Repository


class BatchRepository(_Repository[ReimbursementBatch]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ReimbursementBatch)

    def get_by_name(self, name: str) -> ReimbursementBatch | None:
        statement = (
            select(ReimbursementBatch)
            .where(ReimbursementBatch.name == name)
            .order_by(ReimbursementBatch.id)
        )
        return self._session.scalar(statement)

    def list_with_item_totals(
        self,
    ) -> list[tuple[ReimbursementBatch, int, int]]:
        """Return batches with their item count and integer-cent total."""
        statement = (
            select(
                ReimbursementBatch,
                func.count(Item.id),
                func.coalesce(func.sum(Item.total_amount_cents), 0),
            )
            .outerjoin(Item, Item.batch_id == ReimbursementBatch.id)
            .group_by(ReimbursementBatch.id)
            .order_by(ReimbursementBatch.id)
        )
        return [
            (batch, int(item_count), int(total_amount_cents))
            for batch, item_count, total_amount_cents in self._session.execute(statement)
        ]
