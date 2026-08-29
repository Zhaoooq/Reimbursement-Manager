from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from reimbursement_manager.database.models import (
    Item,
    MaterialRequirement,
    ReimbursementBatch,
)
from reimbursement_manager.database.repositories.base import _Repository


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ItemRepository(_Repository[Item]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Item)

    def list_by_batch(self, batch_id: int) -> list[Item]:
        statement = (
            select(Item)
            .where(Item.batch_id == batch_id)
            .order_by(Item.id)
        )
        return list(self._session.scalars(statement))

    def get_by_batch_and_sequence(
        self, batch_id: int, sequence_number: int
    ) -> Item | None:
        statement = select(Item).where(
            Item.batch_id == batch_id,
            Item.sequence_number == sequence_number,
        )
        return self._session.scalar(statement)

    def get_by_id_with_requirements(self, item_id: int) -> Item | None:
        statement = (
            select(Item)
            .where(Item.id == item_id)
            .options(
                selectinload(Item.batch),
                selectinload(Item.requirements).selectinload(
                    MaterialRequirement.material_type
                )
            )
        )
        item = self._session.scalar(statement)
        if item is not None:
            item.requirements.sort(
                key=lambda value: (value.sort_order, value.id)
            )
        return item

    def create_requirement(
        self, requirement: MaterialRequirement
    ) -> MaterialRequirement:
        self._session.add(requirement)
        self._session.flush()
        return requirement

    def search(self, query: str) -> list[Item]:
        normalized_query = query.strip()
        if not normalized_query:
            return self.list()

        pattern = f"%{_escape_like(normalized_query)}%"
        statement = (
            select(Item)
            .join(ReimbursementBatch, Item.batch_id == ReimbursementBatch.id)
            .where(
                or_(
                    Item.name.ilike(pattern, escape="\\"),
                    Item.merchant.ilike(pattern, escape="\\"),
                    Item.order_number.ilike(pattern, escape="\\"),
                    ReimbursementBatch.name.ilike(pattern, escape="\\"),
                )
            )
            .order_by(Item.id)
        )
        return list(self._session.scalars(statement))
