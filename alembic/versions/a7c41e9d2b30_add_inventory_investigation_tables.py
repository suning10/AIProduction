"""Add inventory gap investigation tables.

Revision ID: a7c41e9d2b30
Revises: f3a9c7e21b6d
Create Date: 2026-11-05 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c41e9d2b30"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "f3a9c7e21b6d"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "inventory_investigation",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("locations", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("total_gaps", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("report", sa.Text(), nullable=True),
        sa.Column("remediations", postgresql.JSONB(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_inventory_investigation_user_id"), "inventory_investigation", ["user_id"])
    op.create_index(op.f("ix_inventory_investigation_as_of_date"), "inventory_investigation", ["as_of_date"])

    op.create_table(
        "inventory_sku_finding",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("investigation_id", sa.String(), nullable=False),
        sa.Column("sku", sa.String(), nullable=False),
        sa.Column("sloc", sa.String(), nullable=False),
        sa.Column("gap", sa.Integer(), nullable=False),
        sa.Column("root_cause", sa.String(), nullable=False),
        sa.Column("explained", sa.Boolean(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["investigation_id"], ["inventory_investigation.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_inventory_sku_finding_investigation_id"), "inventory_sku_finding", ["investigation_id"])
    op.create_index(op.f("ix_inventory_sku_finding_sku"), "inventory_sku_finding", ["sku"])
    op.create_index(op.f("ix_inventory_sku_finding_root_cause"), "inventory_sku_finding", ["root_cause"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("inventory_sku_finding")
    op.drop_table("inventory_investigation")
