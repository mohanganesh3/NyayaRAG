"""bootstrap runtime tables"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260316_0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "background_task_runs",
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("queue_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_background_task_runs")),
    )
    op.create_index(
        op.f("ix_background_task_runs_task_name"),
        "background_task_runs",
        ["task_name"],
        unique=False,
    )

    op.create_table(
        "runtime_settings",
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("value", sa.String(length=2000), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_runtime_settings")),
    )


def downgrade() -> None:
    op.drop_table("runtime_settings")
    op.drop_index(op.f("ix_background_task_runs_task_name"), table_name="background_task_runs")
    op.drop_table("background_task_runs")
