"""add auth ownership and query history"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260319_0009"
down_revision: str | None = "20260318_0008"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("case_contexts", sa.Column("owner_auth_user_id", sa.String(length=255), nullable=True))
    op.add_column("case_contexts", sa.Column("owner_display_name", sa.String(length=255), nullable=True))
    op.add_column("case_contexts", sa.Column("auth_provider", sa.String(length=50), nullable=True))
    op.create_index(
        op.f("ix_case_contexts_owner_auth_user_id"),
        "case_contexts",
        ["owner_auth_user_id"],
        unique=False,
    )

    op.create_table(
        "query_history_entries",
        sa.Column("query_id", sa.String(length=36), nullable=False),
        sa.Column("auth_user_id", sa.String(length=255), nullable=True),
        sa.Column("auth_session_id", sa.String(length=255), nullable=True),
        sa.Column("auth_provider", sa.String(length=50), nullable=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=True),
        sa.Column("query_text", sa.String(length=4000), nullable=False),
        sa.Column("pipeline", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("answer_preview", sa.String(length=1000), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["case_contexts.case_id"],
            name=op.f("fk_query_history_entries_workspace_id_case_contexts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_query_history_entries")),
    )
    op.create_index(
        op.f("ix_query_history_entries_query_id"),
        "query_history_entries",
        ["query_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_query_history_entries_auth_user_id"),
        "query_history_entries",
        ["auth_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_query_history_entries_auth_session_id"),
        "query_history_entries",
        ["auth_session_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_query_history_entries_workspace_id"),
        "query_history_entries",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_query_history_entries_status"),
        "query_history_entries",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_query_history_entries_status"), table_name="query_history_entries")
    op.drop_index(
        op.f("ix_query_history_entries_workspace_id"),
        table_name="query_history_entries",
    )
    op.drop_index(
        op.f("ix_query_history_entries_auth_session_id"),
        table_name="query_history_entries",
    )
    op.drop_index(
        op.f("ix_query_history_entries_auth_user_id"),
        table_name="query_history_entries",
    )
    op.drop_index(op.f("ix_query_history_entries_query_id"), table_name="query_history_entries")
    op.drop_table("query_history_entries")
    op.drop_index(op.f("ix_case_contexts_owner_auth_user_id"), table_name="case_contexts")
    op.drop_column("case_contexts", "auth_provider")
    op.drop_column("case_contexts", "owner_display_name")
    op.drop_column("case_contexts", "owner_auth_user_id")
