"""add evaluation runs table"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260318_0008"
down_revision: str | None = "20260317_0007"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("suite_name", sa.String(length=100), nullable=False),
        sa.Column("benchmark_name", sa.String(length=255), nullable=False),
        sa.Column("benchmark_version", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column(
            "measured_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("query_count", sa.Integer(), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_runs")),
    )
    op.create_index(
        op.f("ix_evaluation_runs_is_public"),
        "evaluation_runs",
        ["is_public"],
        unique=False,
    )
    op.create_index(
        op.f("ix_evaluation_runs_measured_at"),
        "evaluation_runs",
        ["measured_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_evaluation_runs_status"),
        "evaluation_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_evaluation_runs_suite_name"),
        "evaluation_runs",
        ["suite_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_evaluation_runs_suite_name"), table_name="evaluation_runs")
    op.drop_index(op.f("ix_evaluation_runs_status"), table_name="evaluation_runs")
    op.drop_index(op.f("ix_evaluation_runs_measured_at"), table_name="evaluation_runs")
    op.drop_index(op.f("ix_evaluation_runs_is_public"), table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
