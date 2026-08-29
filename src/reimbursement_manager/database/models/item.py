from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reimbursement_manager.database.models.base import Base, TimestampMixin
from reimbursement_manager.database.models.types import persisted_enum
from reimbursement_manager.domain import ReimbursementStatus

if TYPE_CHECKING:
    from reimbursement_manager.database.models.attachment import Attachment
    from reimbursement_manager.database.models.batch import ReimbursementBatch
    from reimbursement_manager.database.models.material import MaterialRequirement


class Item(TimestampMixin, Base):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint(
            "batch_id", "sequence_number", name="uq_items_batch_sequence"
        ),
        CheckConstraint("sequence_number > 0", name="ck_items_sequence_positive"),
        CheckConstraint("quantity > 0", name="ck_items_quantity_positive"),
        CheckConstraint(
            "unit_price_cents IS NULL OR unit_price_cents >= 0",
            name="ck_items_unit_price_non_negative",
        ),
        CheckConstraint(
            "total_amount_cents >= 0", name="ck_items_total_amount_non_negative"
        ),
        CheckConstraint(
            "status IN ('collecting', 'submitted', 'reimbursed', 'archived')",
            name="item_reimbursement_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("reimbursement_batches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    purchase_date: Mapped[date | None] = mapped_column(Date)
    merchant: Mapped[str | None] = mapped_column(String(200), index=True)
    platform: Mapped[str | None] = mapped_column(String(100))
    order_number: Mapped[str | None] = mapped_column(String(200), index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price_cents: Mapped[int | None] = mapped_column(Integer)
    total_amount_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    status: Mapped[ReimbursementStatus] = mapped_column(
        persisted_enum(ReimbursementStatus, name="item_reimbursement_status"),
        nullable=False,
        default=ReimbursementStatus.COLLECTING,
    )
    notes: Mapped[str | None] = mapped_column(Text)

    batch: Mapped[ReimbursementBatch] = relationship(back_populates="items")
    requirements: Mapped[list[MaterialRequirement]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    attachments: Mapped[list[Attachment]] = relationship(
        back_populates="item",
        passive_deletes="all",
    )
