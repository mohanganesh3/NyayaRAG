"""add workspace saved answers

Revision ID: 20260320_0011
Revises: 20260319_0010
Create Date: 2026-03-20 02:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260320_0011"
down_revision: str | None = "20260319_0010"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_workspace_answers",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("auth_user_id", sa.String(length=255), nullable=False),
        sa.Column("query_text", sa.String(length=4000), nullable=False),
        sa.Column("overall_status", sa.String(length=50), nullable=False),
        sa.Column("answer_payload", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_workspace_answers")),
    )
    op.create_index(
        op.f("ix_saved_workspace_answers_auth_user_id"),
        "saved_workspace_answers",
        ["auth_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_saved_workspace_answers_overall_status"),
        "saved_workspace_answers",
        ["overall_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_saved_workspace_answers_workspace_id"),
        "saved_workspace_answers",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_saved_workspace_answers_workspace_id"), table_name="saved_workspace_answers")
    op.drop_index(op.f("ix_saved_workspace_answers_overall_status"), table_name="saved_workspace_answers")
    op.drop_index(op.f("ix_saved_workspace_answers_auth_user_id"), table_name="saved_workspace_answers")
    op.drop_table("saved_workspace_answers")
