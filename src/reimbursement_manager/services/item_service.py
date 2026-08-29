from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Item, MaterialRequirement
from reimbursement_manager.database.repositories import (
    AttachmentRepository,
    BatchRepository,
    ItemRepository,
    TemplateRepository,
)
from reimbursement_manager.domain import ReimbursementStatus
from reimbursement_manager.services.template_service import TemplateNotFoundError

if TYPE_CHECKING:
    from reimbursement_manager.services.attachment_service import (
        AttachmentService,
        AttachmentTrashMove,
    )


class ItemServiceError(Exception):
    """Base exception for recoverable Item service failures."""


class ItemNotFoundError(ItemServiceError, LookupError):
    def __init__(self, item_id: int) -> None:
        super().__init__(f"Item {item_id} does not exist.")
        self.item_id = item_id


class BatchNotFoundError(ItemServiceError, LookupError):
    def __init__(self, batch_id: int) -> None:
        super().__init__(f"Batch {batch_id} does not exist.")
        self.batch_id = batch_id


class ItemSequenceAlreadyExistsError(ItemServiceError, ValueError):
    def __init__(self, batch_id: int, sequence_number: int) -> None:
        super().__init__(
            f"Batch {batch_id} already contains sequence number "
            f"{sequence_number}."
        )
        self.batch_id = batch_id
        self.sequence_number = sequence_number


class ItemDeletionUnavailableError(ItemServiceError):
    """Raised when managed attachment files cannot be safely coordinated."""


class ItemService:
    """Create and read Item aggregates through explicit transactions."""

    def __init__(
        self,
        database: DatabaseManager,
        attachment_service: AttachmentService | None = None,
    ) -> None:
        self._database = database
        self._attachment_service = attachment_service

    def create_item(
        self,
        *,
        batch_id: int,
        template_id: int,
        sequence_number: int,
        name: str,
        purchase_date: date | None = None,
        merchant: str | None = None,
        platform: str | None = None,
        order_number: str | None = None,
        quantity: int = 1,
        unit_price_cents: int | None = None,
        total_amount_cents: int = 0,
        notes: str | None = None,
    ) -> Item:
        normalized_name = self._normalize_required_text(name, "name")
        self._validate_positive(sequence_number, "sequence_number")
        self._validate_positive(quantity, "quantity")
        self._validate_non_negative(total_amount_cents, "total_amount_cents")
        if unit_price_cents is not None:
            self._validate_non_negative(unit_price_cents, "unit_price_cents")

        with self._database.transaction() as session:
            batch_repository = BatchRepository(session)
            if batch_repository.get_by_id(batch_id) is None:
                raise BatchNotFoundError(batch_id)

            template_repository = TemplateRepository(session)
            template = template_repository.get_by_id_with_materials(template_id)
            if template is None:
                raise TemplateNotFoundError(template_id)

            item_repository = ItemRepository(session)
            duplicate = item_repository.get_by_batch_and_sequence(
                batch_id, sequence_number
            )
            if duplicate is not None:
                raise ItemSequenceAlreadyExistsError(
                    batch_id, sequence_number
                )

            item = item_repository.create(
                Item(
                    batch_id=batch_id,
                    sequence_number=sequence_number,
                    name=normalized_name,
                    purchase_date=purchase_date,
                    merchant=self._normalize_optional_text(merchant),
                    platform=self._normalize_optional_text(platform),
                    order_number=self._normalize_optional_text(order_number),
                    quantity=quantity,
                    unit_price_cents=unit_price_cents,
                    total_amount_cents=total_amount_cents,
                    status=ReimbursementStatus.COLLECTING,
                    notes=self._normalize_optional_text(notes),
                )
            )

            for template_material in template.materials:
                item_repository.create_requirement(
                    MaterialRequirement(
                        item_id=item.id,
                        material_type_id=template_material.material_type_id,
                        required=template_material.required,
                        sort_order=template_material.sort_order,
                    )
                )

            return self._require_loaded_item(item_repository, item.id)

    def get_item(self, item_id: int) -> Item:
        with self._database.transaction() as session:
            repository = ItemRepository(session)
            return self._require_loaded_item(repository, item_id)

    def list_items_by_batch(self, batch_id: int) -> list[Item]:
        """List the Items belonging to one reimbursement batch."""
        with self._database.transaction() as session:
            return ItemRepository(session).list_by_batch(batch_id)

    def search_items(self, query: str = "") -> list[Item]:
        """List Items matching the simple all-items page search query."""
        with self._database.transaction() as session:
            return ItemRepository(session).search(query)

    def delete_item(self, item_id: int) -> None:
        """Safely delete one Item and move each managed attachment to Trash."""
        attachment_moves: list[AttachmentTrashMove] = []
        item: Item | None = None
        try:
            with self._database.transaction() as session:
                item_repository = ItemRepository(session)
                item = self._require_loaded_item(item_repository, item_id)
                attachment_repository = AttachmentRepository(session)
                attachments = attachment_repository.list_by_item(item_id)
                if attachments and self._attachment_service is None:
                    raise ItemDeletionUnavailableError(
                        "Item deletion requires the attachment service when "
                        "attachments are present."
                    )
                if self._attachment_service is not None:
                    attachment_moves = (
                        self._attachment_service.move_item_attachments_to_trash(
                            session, item_id
                        )
                    )
                for attachment in attachments:
                    attachment_repository.delete(attachment)
                item_repository.delete(item)
        except Exception as operation_error:
            if attachment_moves and self._attachment_service is not None:
                self._attachment_service.restore_item_attachment_moves(
                    attachment_moves, operation_error
                )
            raise

        if item is not None and self._attachment_service is not None:
            self._attachment_service.remove_item_directory_if_empty(item)

    @staticmethod
    def _require_loaded_item(
        repository: ItemRepository, item_id: int
    ) -> Item:
        item = repository.get_by_id_with_requirements(item_id)
        if item is None:
            raise ItemNotFoundError(item_id)
        return item

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

    @staticmethod
    def _validate_positive(value: int, field_name: str) -> None:
        if value <= 0:
            raise ValueError(f"{field_name} must be greater than zero")

    @staticmethod
    def _validate_non_negative(value: int, field_name: str) -> None:
        if value < 0:
            raise ValueError(f"{field_name} must be greater than or equal to zero")
