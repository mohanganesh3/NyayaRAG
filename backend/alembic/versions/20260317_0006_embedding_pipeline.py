"""embedding pipeline tables and chunk version tracking"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260317_0006"
down_revision: str | None = "20260317_0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column("embedding_version", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("vector_collection", sa.String(length=100), nullable=True),
    )

    op.create_table(
        "vector_store_points",
        sa.Column("point_id", sa.String(length=255), nullable=False),
        sa.Column("chunk_id", sa.String(length=36), nullable=False),
        sa.Column("doc_id", sa.String(length=36), nullable=False),
        sa.Column("backend", sa.Enum("QDRANT", name="vectorstorebackend", native_enum=False), nullable=False),
        sa.Column("collection_name", sa.String(length=100), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column("embedding_version", sa.String(length=100), nullable=False),
        sa.Column("vector_dimension", sa.Integer(), nullable=False),
        sa.Column("vector", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("projected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.chunk_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["doc_id"], ["legal_documents.doc_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("point_id", name=op.f("pk_vector_store_points")),
        sa.UniqueConstraint("chunk_id", name=op.f("uq_vector_store_points_chunk_id")),
    )


def downgrade() -> None:
    op.drop_table("vector_store_points")
    op.drop_column("document_chunks", "vector_collection")
    op.drop_column("document_chunks", "embedding_version")
