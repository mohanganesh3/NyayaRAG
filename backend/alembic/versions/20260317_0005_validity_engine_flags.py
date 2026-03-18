"""validity engine flags"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260317_0005"
down_revision: str | None = "20260317_0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "legal_documents",
        sa.Column("validity_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "legal_documents",
        sa.Column("projection_stale", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "legal_documents",
        sa.Column("stale_reason", sa.String(length=1000), nullable=True),
    )

    op.add_column(
        "document_chunks",
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("needs_reembedding", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "document_chunks",
        sa.Column("projection_stale", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "document_chunks",
        sa.Column("stale_reason", sa.String(length=1000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_chunks", "stale_reason")
    op.drop_column("document_chunks", "projection_stale")
    op.drop_column("document_chunks", "needs_reembedding")
    op.drop_column("document_chunks", "last_validated_at")
    op.drop_column("legal_documents", "stale_reason")
    op.drop_column("legal_documents", "projection_stale")
    op.drop_column("legal_documents", "validity_checked_at")
