"""Create the initial Phase 1 schema.

Revision ID: 20260828_0001
Revises:
Create Date: 2026-08-28
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260828_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "material_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_material_types_code", "material_types", ["code"], unique=True
    )
    op.create_index(
        "ix_material_types_name", "material_types", ["name"], unique=True
    )

    op.create_table(
        "reimbursement_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "collecting",
                "submitted",
                "reimbursed",
                "archived",
                name="reimbursement_status",
                native_enum=False,
                create_constraint=False,
            ),
            nullable=False,
        ),
        sa.Column("reimburser", sa.String(length=100), nullable=True),
        sa.Column("project_name", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reimbursed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('collecting', 'submitted', 'reimbursed', 'archived')",
            name="reimbursement_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_reimbursement_batches_name",
        "reimbursement_batches",
        ["name"],
        unique=False,
    )

    op.create_table(
        "templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_templates_name", "templates", ["name"], unique=True)

    op.create_table(
        "items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("merchant", sa.String(length=200), nullable=True),
        sa.Column("platform", sa.String(length=100), nullable=True),
        sa.Column("order_number", sa.String(length=200), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_cents", sa.Integer(), nullable=True),
        sa.Column("total_amount_cents", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "collecting",
                "submitted",
                "reimbursed",
                "archived",
                name="item_reimbursement_status",
                native_enum=False,
                create_constraint=False,
            ),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity > 0", name="ck_items_quantity_positive"
        ),
        sa.CheckConstraint(
            "sequence_number > 0", name="ck_items_sequence_positive"
        ),
        sa.CheckConstraint(
            "total_amount_cents >= 0",
            name="ck_items_total_amount_non_negative",
        ),
        sa.CheckConstraint(
            "unit_price_cents IS NULL OR unit_price_cents >= 0",
            name="ck_items_unit_price_non_negative",
        ),
        sa.CheckConstraint(
            "status IN ('collecting', 'submitted', 'reimbursed', 'archived')",
            name="item_reimbursement_status",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["reimbursement_batches.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_id", "sequence_number", name="uq_items_batch_sequence"
        ),
    )
    op.create_index("ix_items_batch_id", "items", ["batch_id"], unique=False)
    op.create_index("ix_items_merchant", "items", ["merchant"], unique=False)
    op.create_index("ix_items_name", "items", ["name"], unique=False)
    op.create_index(
        "ix_items_order_number", "items", ["order_number"], unique=False
    )

    op.create_table(
        "template_materials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("material_type_id", sa.Integer(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sort_order >= 0", name="ck_template_materials_sort_non_negative"
        ),
        sa.ForeignKeyConstraint(
            ["material_type_id"], ["material_types.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["template_id"], ["templates.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "template_id",
            "material_type_id",
            name="uq_template_materials_template_type",
        ),
    )
    op.create_index(
        "ix_template_materials_material_type_id",
        "template_materials",
        ["material_type_id"],
        unique=False,
    )
    op.create_index(
        "ix_template_materials_template_id",
        "template_materials",
        ["template_id"],
        unique=False,
    )

    op.create_table(
        "attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("material_type_id", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("relative_path", sa.String(length=1024), nullable=False),
        sa.Column("file_extension", sa.String(length=32), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "health",
            sa.Enum(
                "ok",
                "missing",
                name="attachment_health",
                native_enum=False,
                create_constraint=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "file_size >= 0", name="ck_attachments_file_size_non_negative"
        ),
        sa.CheckConstraint(
            "health IN ('ok', 'missing')", name="attachment_health"
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["items.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["material_type_id"], ["material_types.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "item_id", "sha256", name="uq_attachments_item_sha256"
        ),
        sa.UniqueConstraint(
            "relative_path", name="uq_attachments_relative_path"
        ),
    )
    op.create_index(
        "ix_attachments_item_id", "attachments", ["item_id"], unique=False
    )
    op.create_index(
        "ix_attachments_material_type_id",
        "attachments",
        ["material_type_id"],
        unique=False,
    )

    op.create_table(
        "material_requirements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("material_type_id", sa.Integer(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sort_order >= 0",
            name="ck_material_requirements_sort_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["material_type_id"], ["material_types.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "item_id",
            "material_type_id",
            name="uq_material_requirements_item_type",
        ),
    )
    op.create_index(
        "ix_material_requirements_item_id",
        "material_requirements",
        ["item_id"],
        unique=False,
    )
    op.create_index(
        "ix_material_requirements_material_type_id",
        "material_requirements",
        ["material_type_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_material_requirements_material_type_id",
        table_name="material_requirements",
    )
    op.drop_index(
        "ix_material_requirements_item_id", table_name="material_requirements"
    )
    op.drop_table("material_requirements")

    op.drop_index("ix_attachments_material_type_id", table_name="attachments")
    op.drop_index("ix_attachments_item_id", table_name="attachments")
    op.drop_table("attachments")

    op.drop_index(
        "ix_template_materials_template_id", table_name="template_materials"
    )
    op.drop_index(
        "ix_template_materials_material_type_id",
        table_name="template_materials",
    )
    op.drop_table("template_materials")

    op.drop_index("ix_items_order_number", table_name="items")
    op.drop_index("ix_items_name", table_name="items")
    op.drop_index("ix_items_merchant", table_name="items")
    op.drop_index("ix_items_batch_id", table_name="items")
    op.drop_table("items")

    op.drop_index("ix_templates_name", table_name="templates")
    op.drop_table("templates")

    op.drop_index(
        "ix_reimbursement_batches_name", table_name="reimbursement_batches"
    )
    op.drop_table("reimbursement_batches")

    op.drop_index("ix_material_types_name", table_name="material_types")
    op.drop_index("ix_material_types_code", table_name="material_types")
    op.drop_table("material_types")
