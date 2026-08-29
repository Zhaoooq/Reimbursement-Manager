from sqlalchemy import select
from sqlalchemy.orm import Session

from reimbursement_manager.database.models import Attachment
from reimbursement_manager.database.repositories.base import _Repository


class AttachmentRepository(_Repository[Attachment]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Attachment)

    def list_by_item(self, item_id: int) -> list[Attachment]:
        statement = (
            select(Attachment)
            .where(Attachment.item_id == item_id)
            .order_by(Attachment.id)
        )
        return list(self._session.scalars(statement))

    def list_by_material(
        self, *, item_id: int, material_type_id: int
    ) -> list[Attachment]:
        statement = (
            select(Attachment)
            .where(
                Attachment.item_id == item_id,
                Attachment.material_type_id == material_type_id,
            )
            .order_by(Attachment.id)
        )
        return list(self._session.scalars(statement))

    def find_by_hash(self, *, item_id: int, sha256: str) -> Attachment | None:
        statement = select(Attachment).where(
            Attachment.item_id == item_id,
            Attachment.sha256 == sha256,
        )
        return self._session.scalar(statement)

