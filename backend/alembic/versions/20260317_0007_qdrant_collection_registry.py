"""qdrant collection registry"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260317_0007"
down_revision: str | None = "20260317_0006"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vector_store_collections",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "backend",
            sa.Enum("QDRANT", name="vectorstorebackend", native_enum=False),
            nullable=False,
        ),
        sa.Column("vector_size", sa.Integer(), nullable=False),
        sa.Column(
            "distance_metric",
            sa.Enum("COSINE", name="vectordistancemetric", native_enum=False),
            nullable=False,
        ),
        sa.Column("indexed_payload_fields", sa.JSON(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_vector_store_collections")),
    )


def downgrade() -> None:
    op.drop_table("vector_store_collections")
