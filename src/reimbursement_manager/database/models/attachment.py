from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reimbursement_manager.database.models.base import Base, TimestampMixin
from reimbursement_manager.database.models.types import persisted_enum
from reimbursement_manager.domain import AttachmentHealth

if TYPE_CHECKING:
    from reimbursement_manager.database.models.item import Item
    from reimbursement_manager.database.models.material import MaterialType


class Attachment(TimestampMixin, Base):
    __tablename__ = "attachments"
    __table_args__ = (
        UniqueConstraint(
            "item_id", "sha256", name="uq_attachments_item_sha256"
        ),
        UniqueConstraint(
            "relative_path", name="uq_attachments_relative_path"
        ),
        CheckConstraint(
            "file_size >= 0", name="ck_attachments_file_size_non_negative"
        ),
        CheckConstraint(
            "health IN ('ok', 'missing')", name="attachment_health"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    material_type_id: Mapped[int] = mapped_column(
        ForeignKey("material_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_extension: Mapped[str] = mapped_column(String(32), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    is_derived: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        server_default="0",
    )
    health: Mapped[AttachmentHealth] = mapped_column(
        persisted_enum(AttachmentHealth, name="attachment_health"),
        nullable=False,
        default=AttachmentHealth.OK,
    )

    item: Mapped[Item] = relationship(back_populates="attachments")
    material_type: Mapped[MaterialType] = relationship(
        back_populates="attachments"
    )
