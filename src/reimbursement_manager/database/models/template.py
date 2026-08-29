from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reimbursement_manager.database.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from reimbursement_manager.database.models.material import MaterialType


class Template(TimestampMixin, Base):
    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(
        String(200), nullable=False, unique=True, index=True
    )
    description: Mapped[str | None] = mapped_column(Text)

    materials: Mapped[list[TemplateMaterial]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class TemplateMaterial(TimestampMixin, Base):
    __tablename__ = "template_materials"
    __table_args__ = (
        UniqueConstraint(
            "template_id",
            "material_type_id",
            name="uq_template_materials_template_type",
        ),
        CheckConstraint(
            "sort_order >= 0", name="ck_template_materials_sort_non_negative"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("templates.id", ondelete="CASCADE"),
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

    template: Mapped[Template] = relationship(back_populates="materials")
    material_type: Mapped[MaterialType] = relationship(
        back_populates="template_materials"
    )

