"""Add RAG group and document tables.

Revision ID: f3a9c7e21b6d
Revises: b25d38b0cd7c
Create Date: 2026-09-14 00:00:00.000000

"""

from typing import Sequence, Union

import pgvector.sqlalchemy
import sqlalchemy as sa
import sqlmodel  # noqa: F401

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a9c7e21b6d"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "b25d38b0cd7c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Must match app.core.config.Settings.RAG_EMBEDDING_DIMENSIONS default —
# text-embedding-3-small produces 1536-dim vectors. Changing the embedder
# model to one with a different output size requires a follow-up migration.
EMBEDDING_DIMENSIONS = 1536


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "group",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_group_name"), "group", ["name"], unique=True)

    op.create_table(
        "groupmembership",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("role", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["group.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "group_id", name="uq_groupmembership_user_group"),
    )
    op.create_index(op.f("ix_groupmembership_user_id"), "groupmembership", ["user_id"])
    op.create_index(op.f("ix_groupmembership_group_id"), "groupmembership", ["group_id"])

    op.create_table(
        "document",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["group.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_document_group_id"), "document", ["group_id"])
    op.create_index(op.f("ix_document_owner_id"), "document", ["owner_id"])

    op.create_table(
        "documentchunk",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_documentchunk_document_id"), "documentchunk", ["document_id"])

    # ivfflat cosine index for approximate nearest-neighbor search — matches
    # the .cosine_distance() comparator used by app.services.rag.RAGService.
    op.execute(
        "CREATE INDEX ix_documentchunk_embedding_cosine ON documentchunk "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_documentchunk_embedding_cosine")
    op.drop_table("documentchunk")
    op.drop_table("document")
    op.drop_table("groupmembership")
    op.drop_index(op.f("ix_group_name"), table_name="group")
    op.drop_table("group")
