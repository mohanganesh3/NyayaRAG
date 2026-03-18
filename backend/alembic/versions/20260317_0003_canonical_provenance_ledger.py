"""canonical provenance ledger"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260317_0003"
down_revision: str | None = "20260317_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


SOURCE_TYPE = sa.Enum(
    "court_portal",
    "statute_portal",
    "api",
    "tribunal_portal",
    "reports_portal",
    "user_upload",
    "other",
    name="sourcetype",
    native_enum=False,
)

INGESTION_RUN_STATUS = sa.Enum(
    "pending",
    "running",
    "succeeded",
    "failed",
    "partial",
    name="ingestionrunstatus",
    native_enum=False,
)

APPROVAL_STATUS = sa.Enum(
    "PENDING",
    "APPROVED",
    "BLOCKED",
    name="approvalstatus",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "source_registries",
        sa.Column("source_key", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("source_type", SOURCE_TYPE, nullable=False),
        sa.Column("base_url", sa.String(length=1000), nullable=True),
        sa.Column("canonical_hostname", sa.String(length=255), nullable=True),
        sa.Column("jurisdiction_scope", sa.JSON(), nullable=False),
        sa.Column("update_frequency", sa.String(length=100), nullable=True),
        sa.Column("access_method", sa.String(length=100), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("approval_status", APPROVAL_STATUS, nullable=False),
        sa.Column("default_parser_version", sa.String(length=50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("source_key", name=op.f("pk_source_registries")),
    )

    op.create_table(
        "ingestion_runs",
        sa.Column("source_key", sa.String(length=255), nullable=False),
        sa.Column("status", INGESTION_RUN_STATUS, nullable=False),
        sa.Column("parser_version", sa.String(length=50), nullable=False),
        sa.Column("triggered_by", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_count", sa.Integer(), nullable=False),
        sa.Column("new_document_count", sa.Integer(), nullable=False),
        sa.Column("updated_document_count", sa.Integer(), nullable=False),
        sa.Column("failed_document_count", sa.Integer(), nullable=False),
        sa.Column("checksum_algorithm", sa.String(length=30), nullable=False),
        sa.Column("source_snapshot_url", sa.String(length=1000), nullable=True),
        sa.Column("approval_status", APPROVAL_STATUS, nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_key"],
            ["source_registries.source_key"],
            name=op.f("fk_ingestion_runs_source_key_source_registries"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_runs")),
    )
    op.create_index(op.f("ix_ingestion_runs_source_key"), "ingestion_runs", ["source_key"], unique=False)

    with op.batch_alter_table("legal_documents") as batch_op:
        batch_op.create_index(
            op.f("ix_legal_documents_source_system"),
            ["source_system"],
            unique=False,
        )
        batch_op.create_index(
            op.f("ix_legal_documents_ingestion_run_id"),
            ["ingestion_run_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            op.f("fk_legal_documents_source_system_source_registries"),
            "source_registries",
            ["source_system"],
            ["source_key"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            op.f("fk_legal_documents_ingestion_run_id_ingestion_runs"),
            "ingestion_runs",
            ["ingestion_run_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("legal_documents") as batch_op:
        batch_op.drop_constraint(
            op.f("fk_legal_documents_ingestion_run_id_ingestion_runs"),
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            op.f("fk_legal_documents_source_system_source_registries"),
            type_="foreignkey",
        )
        batch_op.drop_index(op.f("ix_legal_documents_ingestion_run_id"))
        batch_op.drop_index(op.f("ix_legal_documents_source_system"))

    op.drop_index(op.f("ix_ingestion_runs_source_key"), table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
    op.drop_table("source_registries")
