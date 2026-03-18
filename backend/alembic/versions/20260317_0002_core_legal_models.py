"""core legal models"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260317_0002"
down_revision: str | None = "20260316_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


LEGAL_DOCUMENT_TYPE = sa.Enum(
    "judgment",
    "statute",
    "amendment",
    "circular",
    "notification",
    "order",
    "constitution",
    "bill",
    "lc_report",
    "cab_debate",
    name="legaldocumenttype",
    native_enum=False,
)

VALIDITY_STATUS = sa.Enum(
    "GOOD_LAW",
    "OVERRULED",
    "DISTINGUISHED",
    "REVERSED_ON_APPEAL",
    "REPEALED",
    "AMENDED",
    "PENDING_APPEAL",
    name="validitystatus",
    native_enum=False,
)

APPROVAL_STATUS = sa.Enum(
    "PENDING",
    "APPROVED",
    "BLOCKED",
    name="approvalstatus",
    native_enum=False,
)

APPEAL_OUTCOME = sa.Enum(
    "upheld",
    "reversed",
    "modified",
    "remanded",
    "dismissed",
    name="appealoutcome",
    native_enum=False,
)

CASE_TYPE = sa.Enum(
    "criminal",
    "civil",
    "constitutional",
    "family",
    "corporate",
    "tax",
    "labour",
    "property",
    "consumer",
    "arbitration",
    name="casetype",
    native_enum=False,
)

CASE_STAGE = sa.Enum(
    "investigation",
    "bail",
    "charges",
    "trial",
    "appeal",
    "execution",
    "revision",
    name="casestage",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "legal_documents",
        sa.Column("doc_id", sa.String(length=36), nullable=False),
        sa.Column("doc_type", LEGAL_DOCUMENT_TYPE, nullable=False),
        sa.Column("court", sa.String(length=255), nullable=True),
        sa.Column("bench", sa.JSON(), nullable=False),
        sa.Column("coram", sa.Integer(), nullable=True),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("citation", sa.String(length=255), nullable=True),
        sa.Column("neutral_citation", sa.String(length=255), nullable=True),
        sa.Column("parties", sa.JSON(), nullable=False),
        sa.Column("jurisdiction_binding", sa.JSON(), nullable=False),
        sa.Column("jurisdiction_persuasive", sa.JSON(), nullable=False),
        sa.Column("current_validity", VALIDITY_STATUS, nullable=False),
        sa.Column("overruled_by", sa.String(length=36), nullable=True),
        sa.Column("overruled_date", sa.Date(), nullable=True),
        sa.Column("distinguished_by", sa.JSON(), nullable=False),
        sa.Column("followed_by", sa.JSON(), nullable=False),
        sa.Column("statutes_interpreted", sa.JSON(), nullable=False),
        sa.Column("statutes_applied", sa.JSON(), nullable=False),
        sa.Column("citations_made", sa.JSON(), nullable=False),
        sa.Column("headnotes", sa.JSON(), nullable=False),
        sa.Column("ratio_decidendi", sa.Text(), nullable=True),
        sa.Column("obiter_dicta", sa.JSON(), nullable=False),
        sa.Column("practice_areas", sa.JSON(), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("full_text", sa.Text(), nullable=True),
        sa.Column("source_system", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("source_document_ref", sa.String(length=255), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checksum", sa.String(length=255), nullable=True),
        sa.Column("parser_version", sa.String(length=50), nullable=False),
        sa.Column("ingestion_run_id", sa.String(length=36), nullable=True),
        sa.Column("approval_status", APPROVAL_STATUS, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("doc_id", name=op.f("pk_legal_documents")),
    )

    op.create_table(
        "appeal_nodes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_doc_id", sa.String(length=36), nullable=False),
        sa.Column("court_level", sa.Integer(), nullable=False),
        sa.Column("court_name", sa.String(length=255), nullable=False),
        sa.Column("judgment_date", sa.Date(), nullable=True),
        sa.Column("citation", sa.String(length=255), nullable=True),
        sa.Column("outcome", APPEAL_OUTCOME, nullable=False),
        sa.Column("is_final_authority", sa.Boolean(), nullable=False),
        sa.Column("modifies_ratio", sa.Boolean(), nullable=False),
        sa.Column("parent_doc_id", sa.String(length=36), nullable=True),
        sa.Column("child_doc_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_doc_id"],
            ["legal_documents.doc_id"],
            name=op.f("fk_appeal_nodes_document_doc_id_legal_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appeal_nodes")),
    )

    op.create_table(
        "statute_documents",
        sa.Column("doc_id", sa.String(length=36), nullable=False),
        sa.Column("act_name", sa.String(length=255), nullable=False),
        sa.Column("short_title", sa.String(length=100), nullable=True),
        sa.Column("replaced_by", sa.String(length=255), nullable=True),
        sa.Column("replaced_on", sa.Date(), nullable=True),
        sa.Column("current_sections_in_force", sa.JSON(), nullable=False),
        sa.Column("jurisdiction", sa.String(length=255), nullable=False),
        sa.Column("enforcement_date", sa.Date(), nullable=True),
        sa.Column("current_validity", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["legal_documents.doc_id"],
            name=op.f("fk_statute_documents_doc_id_legal_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("doc_id", name=op.f("pk_statute_documents")),
    )

    op.create_table(
        "document_chunks",
        sa.Column("chunk_id", sa.String(length=36), nullable=False),
        sa.Column("doc_id", sa.String(length=36), nullable=False),
        sa.Column("doc_type", LEGAL_DOCUMENT_TYPE, nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_normalized", sa.Text(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("total_chunks", sa.Integer(), nullable=False),
        sa.Column("section_header", sa.String(length=500), nullable=True),
        sa.Column("court", sa.String(length=255), nullable=True),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("citation", sa.String(length=255), nullable=True),
        sa.Column("jurisdiction_binding", sa.JSON(), nullable=False),
        sa.Column("jurisdiction_persuasive", sa.JSON(), nullable=False),
        sa.Column("current_validity", VALIDITY_STATUS, nullable=False),
        sa.Column("practice_area", sa.JSON(), nullable=False),
        sa.Column("act_name", sa.String(length=255), nullable=True),
        sa.Column("section_number", sa.String(length=50), nullable=True),
        sa.Column("is_in_force", sa.Boolean(), nullable=True),
        sa.Column("amendment_date", sa.Date(), nullable=True),
        sa.Column("embedding_id", sa.String(length=255), nullable=True),
        sa.Column("embedding_model", sa.String(length=100), nullable=True),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["legal_documents.doc_id"],
            name=op.f("fk_document_chunks_doc_id_legal_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("chunk_id", name=op.f("pk_document_chunks")),
        sa.UniqueConstraint("doc_id", "chunk_index", name="uq_document_chunks_doc_index"),
    )

    op.create_table(
        "citation_edges",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_doc_id", sa.String(length=36), nullable=False),
        sa.Column("target_doc_id", sa.String(length=36), nullable=False),
        sa.Column("citation_type", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_doc_id"],
            ["legal_documents.doc_id"],
            name=op.f("fk_citation_edges_source_doc_id_legal_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_doc_id"],
            ["legal_documents.doc_id"],
            name=op.f("fk_citation_edges_target_doc_id_legal_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_citation_edges")),
        sa.UniqueConstraint(
            "source_doc_id",
            "target_doc_id",
            "citation_type",
            name="uq_citation_edges_source_target_type",
        ),
    )

    op.create_table(
        "statute_sections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("statute_doc_id", sa.String(length=36), nullable=False),
        sa.Column("section_number", sa.String(length=50), nullable=False),
        sa.Column("heading", sa.String(length=500), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=True),
        sa.Column("is_in_force", sa.Boolean(), nullable=False),
        sa.Column("corresponding_new_section", sa.String(length=100), nullable=True),
        sa.Column("punishment", sa.Text(), nullable=True),
        sa.Column("cases_interpreting", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["statute_doc_id"],
            ["statute_documents.doc_id"],
            name=op.f("fk_statute_sections_statute_doc_id_statute_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_statute_sections")),
        sa.UniqueConstraint("statute_doc_id", "section_number", name="uq_statute_sections_doc_section"),
    )

    op.create_table(
        "statute_amendments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("section_id", sa.String(length=36), nullable=False),
        sa.Column("amendment_label", sa.String(length=255), nullable=False),
        sa.Column("amendment_date", sa.Date(), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("previous_text", sa.Text(), nullable=True),
        sa.Column("updated_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["statute_sections.id"],
            name=op.f("fk_statute_amendments_section_id_statute_sections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_statute_amendments")),
    )

    op.create_table(
        "case_contexts",
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("appellant_petitioner", sa.String(length=255), nullable=True),
        sa.Column("respondent_opposite_party", sa.String(length=255), nullable=True),
        sa.Column("advocates", sa.JSON(), nullable=False),
        sa.Column("case_type", CASE_TYPE, nullable=True),
        sa.Column("court", sa.String(length=255), nullable=True),
        sa.Column("case_number", sa.String(length=100), nullable=True),
        sa.Column("stage", CASE_STAGE, nullable=True),
        sa.Column("charges_sections", sa.JSON(), nullable=False),
        sa.Column("bnss_equivalents", sa.JSON(), nullable=False),
        sa.Column("statutes_involved", sa.JSON(), nullable=False),
        sa.Column("key_facts", sa.JSON(), nullable=False),
        sa.Column("previous_orders", sa.JSON(), nullable=False),
        sa.Column("bail_history", sa.JSON(), nullable=False),
        sa.Column("open_legal_issues", sa.JSON(), nullable=False),
        sa.Column("uploaded_docs", sa.JSON(), nullable=False),
        sa.Column("doc_extraction_confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("case_id", name=op.f("pk_case_contexts")),
    )


def downgrade() -> None:
    op.drop_table("case_contexts")
    op.drop_table("statute_amendments")
    op.drop_table("statute_sections")
    op.drop_table("citation_edges")
    op.drop_table("document_chunks")
    op.drop_table("statute_documents")
    op.drop_table("appeal_nodes")
    op.drop_table("legal_documents")
