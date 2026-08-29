"""Add a marker for generated submission attachments.

Revision ID: 20260829_0002
Revises: 20260828_0001
Create Date: 2026-08-29
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_0002"
down_revision: str | None = "20260828_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("attachments") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_derived",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("attachments") as batch_op:
        batch_op.drop_column("is_derived")
