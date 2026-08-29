from sqlalchemy import select
from sqlalchemy.orm import Session

from reimbursement_manager.database.models import MaterialType
from reimbursement_manager.database.repositories.base import _Repository


class MaterialTypeRepository(_Repository[MaterialType]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, MaterialType)

    def get_by_code(self, code: str) -> MaterialType | None:
        statement = select(MaterialType).where(MaterialType.code == code)
        return self._session.scalar(statement)

