from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import TYPE_CHECKING

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import ReimbursementBatch
from reimbursement_manager.database.repositories import BatchRepository
from reimbursement_manager.domain import ReimbursementStatus

if TYPE_CHECKING:
    from reimbursement_manager.services.storage_path_service import StoragePathService


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BatchListEntry:
    """Read model used by the reimbursement-batch list."""

    id: int
    name: str
    created_at: datetime
    item_count: int
    total_amount_cents: int


class BatchNotFoundError(LookupError):
    pass


class BatchNotEmptyError(ValueError):
    def __init__(self, batch_id: int, item_count: int) -> None:
        super().__init__(
            f"Batch {batch_id} still contains {item_count} item(s)."
        )
        self.batch_id = batch_id
        self.item_count = item_count


class BatchService:
    """Coordinate basic reimbursement-batch use cases."""

    def __init__(
        self,
        database: DatabaseManager,
        storage_path_service: StoragePathService | None = None,
    ) -> None:
        self._database = database
        self._storage_path_service = storage_path_service

    def create_batch(
        self,
        *,
        name: str,
        project_name: str | None = None,
        reimburser: str | None = None,
        notes: str | None = None,
    ) -> ReimbursementBatch:
        normalized_name = self._normalize_required_text(name, "name")
        with self._database.transaction() as session:
            return BatchRepository(session).create(
                ReimbursementBatch(
                    name=normalized_name,
                    project_name=self._normalize_optional_text(project_name),
                    reimburser=self._normalize_optional_text(reimburser),
                    notes=self._normalize_optional_text(notes),
                    status=ReimbursementStatus.COLLECTING,
                )
            )

    def list_batches(self) -> list[ReimbursementBatch]:
        with self._database.transaction() as session:
            return BatchRepository(session).list()

    def list_batch_entries(self) -> list[BatchListEntry]:
        """List batches together with exact, database-aggregated item totals."""
        with self._database.transaction() as session:
            rows = BatchRepository(session).list_with_item_totals()
        return [
            BatchListEntry(
                id=batch.id,
                name=batch.name,
                created_at=batch.created_at,
                item_count=item_count,
                total_amount_cents=total_amount_cents,
            )
            for batch, item_count, total_amount_cents in rows
        ]

    def delete_batch(self, batch_id: int) -> None:
        """Delete an empty Batch; never cascade its Items or files."""
        batch: ReimbursementBatch | None = None
        with self._database.transaction() as session:
            repository = BatchRepository(session)
            batch = repository.get_by_id(batch_id)
            if batch is None:
                raise BatchNotFoundError(f"Batch {batch_id} does not exist.")
            item_count = len(batch.items)
            if item_count:
                raise BatchNotEmptyError(batch_id, item_count)
            repository.delete(batch)

        if batch is not None and self._storage_path_service is not None:
            directory = self._storage_path_service.get_batch_directory(
                batch_name=batch.name,
                batch_date=batch.created_at.date(),
            )
            try:
                directory.rmdir()
            except FileNotFoundError:
                return
            except OSError:
                logger.info("Retained non-empty batch directory: %s", directory)

    @staticmethod
    def _normalize_required_text(value: str, field_name: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")
        return normalized

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
