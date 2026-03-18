from __future__ import annotations

from datetime import date as date_value
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.provenance import IngestionRun, SourceRegistry
    from app.models.vector_store import VectorStorePoint


class LegalDocumentType(StrEnum):
    JUDGMENT = "judgment"
    STATUTE = "statute"
    AMENDMENT = "amendment"
    CIRCULAR = "circular"
    NOTIFICATION = "notification"
    ORDER = "order"
    CONSTITUTION = "constitution"
    BILL = "bill"
    LC_REPORT = "lc_report"
    CAB_DEBATE = "cab_debate"


class ValidityStatus(StrEnum):
    GOOD_LAW = "GOOD_LAW"
    OVERRULED = "OVERRULED"
    DISTINGUISHED = "DISTINGUISHED"
    REVERSED_ON_APPEAL = "REVERSED_ON_APPEAL"
    REPEALED = "REPEALED"
    AMENDED = "AMENDED"
    PENDING_APPEAL = "PENDING_APPEAL"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"


class AppealOutcome(StrEnum):
    UPHELD = "upheld"
    REVERSED = "reversed"
    MODIFIED = "modified"
    REMANDED = "remanded"
    DISMISSED = "dismissed"


class CaseType(StrEnum):
    CRIMINAL = "criminal"
    CIVIL = "civil"
    CONSTITUTIONAL = "constitutional"
    FAMILY = "family"
    CORPORATE = "corporate"
    TAX = "tax"
    LABOUR = "labour"
    PROPERTY = "property"
    CONSUMER = "consumer"
    ARBITRATION = "arbitration"


class CaseStage(StrEnum):
    INVESTIGATION = "investigation"
    BAIL = "bail"
    CHARGES = "charges"
    TRIAL = "trial"
    APPEAL = "appeal"
    EXECUTION = "execution"
    REVISION = "revision"


class LegalDocument(TimestampMixin, Base):
    __tablename__ = "legal_documents"

    doc_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    doc_type: Mapped[LegalDocumentType] = mapped_column(
        Enum(LegalDocumentType, native_enum=False),
        nullable=False,
    )
    court: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bench: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    coram: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date: Mapped[date_value | None] = mapped_column(Date, nullable=True)
    citation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    neutral_citation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parties: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    jurisdiction_binding: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    jurisdiction_persuasive: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    current_validity: Mapped[ValidityStatus] = mapped_column(
        Enum(ValidityStatus, native_enum=False),
        nullable=False,
        default=ValidityStatus.GOOD_LAW,
    )
    overruled_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    overruled_date: Mapped[date_value | None] = mapped_column(Date, nullable=True)
    distinguished_by: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    followed_by: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    statutes_interpreted: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    statutes_applied: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    citations_made: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    headnotes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    ratio_decidendi: Mapped[str | None] = mapped_column(Text, nullable=True)
    obiter_dicta: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    practice_areas: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="en")
    full_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_system: Mapped[str | None] = mapped_column(
        ForeignKey("source_registries.source_key", ondelete="SET NULL"),
        nullable=True,
    )
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_document_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parser_version: Mapped[str] = mapped_column(String(50), nullable=False, default="v0")
    ingestion_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, native_enum=False),
        nullable=False,
        default=ApprovalStatus.PENDING,
    )
    validity_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    projection_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stale_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    appeal_history: Mapped[list[AppealNode]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )
    statute_document: Mapped[StatuteDocument | None] = relationship(
        back_populates="document",
        uselist=False,
        cascade="all, delete-orphan",
    )
    outgoing_citation_edges: Mapped[list[CitationEdge]] = relationship(
        back_populates="source_document",
        foreign_keys="CitationEdge.source_doc_id",
        cascade="all, delete-orphan",
    )
    incoming_citation_edges: Mapped[list[CitationEdge]] = relationship(
        back_populates="target_document",
        foreign_keys="CitationEdge.target_doc_id",
    )
    source_registry: Mapped[SourceRegistry | None] = relationship(
        "SourceRegistry",
        back_populates="documents",
    )
    ingestion_run: Mapped[IngestionRun | None] = relationship(
        "IngestionRun",
        back_populates="documents",
    )


class AppealNode(TimestampMixin, Base):
    __tablename__ = "appeal_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_doc_id: Mapped[str] = mapped_column(
        ForeignKey("legal_documents.doc_id", ondelete="CASCADE"),
        nullable=False,
    )
    court_level: Mapped[int] = mapped_column(Integer, nullable=False)
    court_name: Mapped[str] = mapped_column(String(255), nullable=False)
    judgment_date: Mapped[date_value | None] = mapped_column(Date, nullable=True)
    citation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    outcome: Mapped[AppealOutcome] = mapped_column(
        Enum(AppealOutcome, native_enum=False),
        nullable=False,
    )
    is_final_authority: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    modifies_ratio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parent_doc_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    child_doc_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    document: Mapped[LegalDocument] = relationship(back_populates="appeal_history")


class StatuteDocument(TimestampMixin, Base):
    __tablename__ = "statute_documents"

    doc_id: Mapped[str] = mapped_column(
        ForeignKey("legal_documents.doc_id", ondelete="CASCADE"),
        primary_key=True,
    )
    act_name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    replaced_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    replaced_on: Mapped[date_value | None] = mapped_column(Date, nullable=True)
    current_sections_in_force: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    jurisdiction: Mapped[str] = mapped_column(String(255), nullable=False)
    enforcement_date: Mapped[date_value | None] = mapped_column(Date, nullable=True)
    current_validity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    document: Mapped[LegalDocument] = relationship(back_populates="statute_document")
    sections: Mapped[list[StatuteSection]] = relationship(
        back_populates="statute_document",
        cascade="all, delete-orphan",
    )


class StatuteSection(TimestampMixin, Base):
    __tablename__ = "statute_sections"
    __table_args__ = (
        UniqueConstraint(
            "statute_doc_id",
            "section_number",
            name="uq_statute_sections_doc_section",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    statute_doc_id: Mapped[str] = mapped_column(
        ForeignKey("statute_documents.doc_id", ondelete="CASCADE"),
        nullable=False,
    )
    section_number: Mapped[str] = mapped_column(String(50), nullable=False)
    heading: Mapped[str | None] = mapped_column(String(500), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_in_force: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    corresponding_new_section: Mapped[str | None] = mapped_column(String(100), nullable=True)
    punishment: Mapped[str | None] = mapped_column(Text, nullable=True)
    cases_interpreting: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    statute_document: Mapped[StatuteDocument] = relationship(back_populates="sections")
    amendments: Mapped[list[StatuteAmendment]] = relationship(
        back_populates="section",
        cascade="all, delete-orphan",
    )


class StatuteAmendment(TimestampMixin, Base):
    __tablename__ = "statute_amendments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    section_id: Mapped[str] = mapped_column(
        ForeignKey("statute_sections.id", ondelete="CASCADE"),
        nullable=False,
    )
    amendment_label: Mapped[str] = mapped_column(String(255), nullable=False)
    amendment_date: Mapped[date_value | None] = mapped_column(Date, nullable=True)
    effective_date: Mapped[date_value | None] = mapped_column(Date, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    section: Mapped[StatuteSection] = relationship(back_populates="amendments")


class DocumentChunk(TimestampMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("doc_id", "chunk_index", name="uq_document_chunks_doc_index"),
    )

    chunk_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    doc_id: Mapped[str] = mapped_column(
        ForeignKey("legal_documents.doc_id", ondelete="CASCADE"),
        nullable=False,
    )
    doc_type: Mapped[LegalDocumentType] = mapped_column(
        Enum(LegalDocumentType, native_enum=False),
        nullable=False,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_normalized: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False)
    section_header: Mapped[str | None] = mapped_column(String(500), nullable=True)
    court: Mapped[str | None] = mapped_column(String(255), nullable=True)
    date: Mapped[date_value | None] = mapped_column(Date, nullable=True)
    citation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    jurisdiction_binding: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    jurisdiction_persuasive: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    current_validity: Mapped[ValidityStatus] = mapped_column(
        Enum(ValidityStatus, native_enum=False),
        nullable=False,
        default=ValidityStatus.GOOD_LAW,
    )
    practice_area: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    act_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    section_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_in_force: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    amendment_date: Mapped[date_value | None] = mapped_column(Date, nullable=True)
    embedding_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vector_collection: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    needs_reembedding: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    projection_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stale_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    document: Mapped[LegalDocument] = relationship(back_populates="chunks")
    vector_point: Mapped[VectorStorePoint | None] = relationship(
        "VectorStorePoint",
        back_populates="chunk",
        uselist=False,
        cascade="all, delete-orphan",
    )


class CitationEdge(TimestampMixin, Base):
    __tablename__ = "citation_edges"
    __table_args__ = (
        UniqueConstraint(
            "source_doc_id",
            "target_doc_id",
            "citation_type",
            name="uq_citation_edges_source_target_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_doc_id: Mapped[str] = mapped_column(
        ForeignKey("legal_documents.doc_id", ondelete="CASCADE"),
        nullable=False,
    )
    target_doc_id: Mapped[str] = mapped_column(
        ForeignKey("legal_documents.doc_id", ondelete="CASCADE"),
        nullable=False,
    )
    citation_type: Mapped[str] = mapped_column(String(100), nullable=False)

    source_document: Mapped[LegalDocument] = relationship(
        back_populates="outgoing_citation_edges",
        foreign_keys=[source_doc_id],
    )
    target_document: Mapped[LegalDocument] = relationship(
        back_populates="incoming_citation_edges",
        foreign_keys=[target_doc_id],
    )


class CaseContext(TimestampMixin, Base):
    __tablename__ = "case_contexts"

    case_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    appellant_petitioner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    respondent_opposite_party: Mapped[str | None] = mapped_column(String(255), nullable=True)
    advocates: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    case_type: Mapped[CaseType | None] = mapped_column(
        Enum(CaseType, native_enum=False),
        nullable=True,
    )
    court: Mapped[str | None] = mapped_column(String(255), nullable=True)
    case_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stage: Mapped[CaseStage | None] = mapped_column(
        Enum(CaseStage, native_enum=False),
        nullable=True,
    )
    charges_sections: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    bnss_equivalents: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    statutes_involved: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    key_facts: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    previous_orders: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    bail_history: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    open_legal_issues: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    uploaded_docs: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    doc_extraction_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
