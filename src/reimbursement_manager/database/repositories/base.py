from typing import Generic, TypeVar

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from reimbursement_manager.database.models import Base


ModelType = TypeVar("ModelType", bound=Base)


class _Repository(Generic[ModelType]):
    """Shared session-scoped CRUD operations for mapped entities."""

    def __init__(self, session: Session, model_type: type[ModelType]) -> None:
        self._session = session
        self._model_type = model_type

    def create(self, entity: ModelType) -> ModelType:
        self._session.add(entity)
        self._session.flush()
        return entity

    def get_by_id(self, entity_id: int) -> ModelType | None:
        return self._session.get(self._model_type, entity_id)

    def list(self) -> list[ModelType]:
        primary_key = inspect(self._model_type).primary_key[0]
        statement = select(self._model_type).order_by(primary_key)
        return list(self._session.scalars(statement))

    def update(self, entity: ModelType) -> ModelType:
        self._session.add(entity)
        self._session.flush()
        return entity

    def delete(self, entity: ModelType) -> None:
        self._session.delete(entity)
        self._session.flush()

