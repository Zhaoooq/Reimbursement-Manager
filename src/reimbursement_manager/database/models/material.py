from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reimbursement_manager.database.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from reimbursement_manager.database.models.attachment import Attachment
    from reimbursement_manager.database.models.item import Item
    from reimbursement_manager.database.models.template import TemplateMaterial


class MaterialType(TimestampMixin, Base):
    __tablename__ = "material_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, index=True
    )
    code: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    description: Mapped[str | None] = mapped_column(Text)

    requirements: Mapped[list[MaterialRequirement]] = relationship(
        back_populates="material_type",
        passive_deletes="all",
    )
    attachments: Mapped[list[Attachment]] = relationship(
        back_populates="material_type",
        passive_deletes="all",
    )
    template_materials: Mapped[list[TemplateMaterial]] = relationship(
        back_populates="material_type",
        passive_deletes="all",
    )


class MaterialRequirement(TimestampMixin, Base):
    __tablename__ = "material_requirements"
    __table_args__ = (
        UniqueConstraint(
            "item_id",
            "material_type_id",
            name="uq_material_requirements_item_type",
        ),
        CheckConstraint(
            "sort_order >= 0", name="ck_material_requirements_sort_non_negative"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    material_type_id: Mapped[int] = mapped_column(
        ForeignKey("material_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    item: Mapped[Item] = relationship(back_populates="requirements")
    material_type: Mapped[MaterialType] = relationship(
        back_populates="requirements"
    )

