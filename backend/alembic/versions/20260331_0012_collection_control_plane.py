"""add collection control plane tables and metadata columns

Revision ID: 20260331_0012
Revises: 20260320_0011
Create Date: 2026-03-31 23:35:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260331_0012"
down_revision: str | None = "20260320_0011"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


SOURCE_PARTITION_STATUS = sa.Enum(
    "DISCOVERING",
    "RUNNING",
    "VERIFIED",
    "BROKEN",
    "BLOCKED_EXTERNALLY",
    "DONE",
    name="sourcepartitionstatus",
    native_enum=False,
)

PROVENANCE_TIER = sa.Enum(
    "official",
    "gov_mirror",
    "archive_rescue",
    "other",
    name="provenancetier",
    native_enum=False,
)

ARTIFACT_PROMOTION_STATE = sa.Enum(
    "official",
    "gov_mirror_matched",
    "archive_quarantine",
    "rejected",
    name="artifactpromotionstate",
    native_enum=False,
)


def upgrade() -> None:
    with op.batch_alter_table("source_registries") as batch_op:
        batch_op.add_column(sa.Column("collector_type", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("canonical_surfaces", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("mirror_surfaces", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("partition_scheme", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("expected_proof_type", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("auth_mode", sa.String(length=100), nullable=True))
        batch_op.add_column(
            sa.Column("critical", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.add_column(sa.Column("metadata_profile", sa.JSON(), nullable=True))

    with op.batch_alter_table("legal_documents") as batch_op:
        batch_op.add_column(sa.Column("title", sa.String(length=1000), nullable=True))
        batch_op.add_column(sa.Column("date_text", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("decision_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("publication_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("collector_run_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("seed_url", sa.String(length=1000), nullable=True))
        batch_op.add_column(sa.Column("detail_url", sa.String(length=1000), nullable=True))
        batch_op.add_column(sa.Column("artifact_url", sa.String(length=1000), nullable=True))
        batch_op.add_column(sa.Column("source_surface", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("provenance_tier", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("mime_type", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("is_ocr", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("ocr_confidence", sa.Float(), nullable=True))

    op.create_table(
        "source_partitions",
        sa.Column("source_key", sa.String(length=255), nullable=False),
        sa.Column("ingestion_run_id", sa.String(length=36), nullable=True),
        sa.Column("partition_key", sa.String(length=255), nullable=False),
        sa.Column("surface_url", sa.String(length=1000), nullable=False),
        sa.Column("partition_kind", sa.String(length=100), nullable=True),
        sa.Column("expected_hint", sa.String(length=255), nullable=True),
        sa.Column("discovered_count", sa.Integer(), nullable=False),
        sa.Column("ingested_count", sa.Integer(), nullable=False),
        sa.Column("status", SOURCE_PARTITION_STATUS, nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_class", sa.String(length=255), nullable=True),
        sa.Column("proof_note", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_key"],
            ["source_registries.source_key"],
            name=op.f("fk_source_partitions_source_key_source_registries"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_source_partitions_ingestion_run_id_ingestion_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_partitions")),
        sa.UniqueConstraint(
            "source_key",
            "partition_key",
            "surface_url",
            name=op.f("uq_source_partitions_source_partition_surface"),
        ),
    )
    op.create_index(
        op.f("ix_source_partitions_source_key"),
        "source_partitions",
        ["source_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_source_partitions_ingestion_run_id"),
        "source_partitions",
        ["ingestion_run_id"],
        unique=False,
    )
    op.create_index(
        "idx_source_partitions_source_status",
        "source_partitions",
        ["source_key", "status"],
        unique=False,
    )

    op.create_table(
        "artifact_provenance",
        sa.Column("doc_id", sa.String(length=36), nullable=True),
        sa.Column("source_key", sa.String(length=255), nullable=True),
        sa.Column("ingestion_run_id", sa.String(length=36), nullable=True),
        sa.Column("canonical_url", sa.String(length=1000), nullable=True),
        sa.Column("mirror_url", sa.String(length=1000), nullable=True),
        sa.Column("retrieved_from", sa.String(length=1000), nullable=True),
        sa.Column("provenance_tier", PROVENANCE_TIER, nullable=False),
        sa.Column("sha256", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promotion_state", ARTIFACT_PROMOTION_STATE, nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["legal_documents.doc_id"],
            name=op.f("fk_artifact_provenance_doc_id_legal_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_key"],
            ["source_registries.source_key"],
            name=op.f("fk_artifact_provenance_source_key_source_registries"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_artifact_provenance_ingestion_run_id_ingestion_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifact_provenance")),
    )
    op.create_index(op.f("ix_artifact_provenance_doc_id"), "artifact_provenance", ["doc_id"], unique=False)
    op.create_index(op.f("ix_artifact_provenance_source_key"), "artifact_provenance", ["source_key"], unique=False)
    op.create_index(
        op.f("ix_artifact_provenance_ingestion_run_id"),
        "artifact_provenance",
        ["ingestion_run_id"],
        unique=False,
    )
    op.create_index(
        "idx_artifact_provenance_doc_sha",
        "artifact_provenance",
        ["doc_id", "sha256"],
        unique=False,
    )
    op.create_index(
        op.f("ix_artifact_provenance_sha256"),
        "artifact_provenance",
        ["sha256"],
        unique=False,
    )

    op.create_index(
        "idx_legal_documents_source_system_source_document_ref",
        "legal_documents",
        ["source_system", "source_document_ref"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_legal_documents_source_system_source_document_ref", table_name="legal_documents")

    op.drop_index(op.f("ix_artifact_provenance_sha256"), table_name="artifact_provenance")
    op.drop_index("idx_artifact_provenance_doc_sha", table_name="artifact_provenance")
    op.drop_index(op.f("ix_artifact_provenance_ingestion_run_id"), table_name="artifact_provenance")
    op.drop_index(op.f("ix_artifact_provenance_source_key"), table_name="artifact_provenance")
    op.drop_index(op.f("ix_artifact_provenance_doc_id"), table_name="artifact_provenance")
    op.drop_table("artifact_provenance")

    op.drop_index("idx_source_partitions_source_status", table_name="source_partitions")
    op.drop_index(op.f("ix_source_partitions_ingestion_run_id"), table_name="source_partitions")
    op.drop_index(op.f("ix_source_partitions_source_key"), table_name="source_partitions")
    op.drop_table("source_partitions")

    with op.batch_alter_table("legal_documents") as batch_op:
        batch_op.drop_column("ocr_confidence")
        batch_op.drop_column("is_ocr")
        batch_op.drop_column("mime_type")
        batch_op.drop_column("provenance_tier")
        batch_op.drop_column("source_surface")
        batch_op.drop_column("artifact_url")
        batch_op.drop_column("detail_url")
        batch_op.drop_column("seed_url")
        batch_op.drop_column("collector_run_id")
        batch_op.drop_column("publication_date")
        batch_op.drop_column("decision_date")
        batch_op.drop_column("date_text")
        batch_op.drop_column("title")

    with op.batch_alter_table("source_registries") as batch_op:
        batch_op.drop_column("metadata_profile")
        batch_op.drop_column("critical")
        batch_op.drop_column("auth_mode")
        batch_op.drop_column("expected_proof_type")
        batch_op.drop_column("partition_scheme")
        batch_op.drop_column("mirror_surfaces")
        batch_op.drop_column("canonical_surfaces")
        batch_op.drop_column("collector_type")
