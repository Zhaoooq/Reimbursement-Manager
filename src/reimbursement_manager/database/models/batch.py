from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reimbursement_manager.database.models.base import Base, TimestampMixin
from reimbursement_manager.database.models.types import persisted_enum
from reimbursement_manager.domain import ReimbursementStatus

if TYPE_CHECKING:
    from reimbursement_manager.database.models.item import Item


class ReimbursementBatch(TimestampMixin, Base):
    __tablename__ = "reimbursement_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('collecting', 'submitted', 'reimbursed', 'archived')",
            name="reimbursement_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    status: Mapped[ReimbursementStatus] = mapped_column(
        persisted_enum(ReimbursementStatus, name="reimbursement_status"),
        nullable=False,
        default=ReimbursementStatus.COLLECTING,
    )
    reimburser: Mapped[str | None] = mapped_column(String(100))
    project_name: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reimbursed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[Item]] = relationship(
        back_populates="batch",
        passive_deletes="all",
    )
