from __future__ import annotations

from datetime import date as date_value
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import (
    AppealOutcome,
    ApprovalStatus,
    CaseStage,
    CaseType,
    LegalDocumentType,
    ValidityStatus,
)
from app.schemas.provenance import IngestionRunRead, SourceRegistryRead


class AppealNodeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    court_level: int
    court_name: str
    judgment_date: date_value | None = None
    citation: str | None = None
    outcome: AppealOutcome
    is_final_authority: bool
    modifies_ratio: bool
    parent_doc_id: str | None = None
    child_doc_id: str | None = None


class DocumentChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_id: str
    doc_id: str
    doc_type: LegalDocumentType
    text: str
    chunk_index: int
    total_chunks: int
    section_header: str | None = None
    current_validity: ValidityStatus
    embedding_id: str | None = None
    embedding_model: str | None = None
    embedding_version: str | None = None
    vector_collection: str | None = None
    embedded_at: datetime | None = None
    last_validated_at: datetime | None = None
    needs_reembedding: bool
    projection_stale: bool
    stale_reason: str | None = None


class CitationEdgeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_doc_id: str
    target_doc_id: str
    citation_type: str


class StatuteAmendmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    amendment_label: str
    amendment_date: date_value | None = None
    effective_date: date_value | None = None
    summary: str | None = None


class StatuteSectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    section_number: str
    heading: str | None = None
    text: str
    original_text: str | None = None
    is_in_force: bool
    corresponding_new_section: str | None = None
    punishment: str | None = None
    cases_interpreting: list[str]
    amendments: list[StatuteAmendmentRead]


class StatuteDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    doc_id: str
    act_name: str
    short_title: str | None = None
    replaced_by: str | None = None
    replaced_on: date_value | None = None
    current_sections_in_force: list[str]
    jurisdiction: str
    enforcement_date: date_value | None = None
    current_validity: bool
    sections: list[StatuteSectionRead]


class LegalDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    doc_id: str
    doc_type: LegalDocumentType
    court: str | None = None
    bench: list[str]
    coram: int | None = None
    date: date_value | None = None
    citation: str | None = None
    neutral_citation: str | None = None
    parties: dict[str, str]
    jurisdiction_binding: list[str]
    jurisdiction_persuasive: list[str]
    current_validity: ValidityStatus
    overruled_by: str | None = None
    overruled_date: date_value | None = None
    distinguished_by: list[str]
    followed_by: list[str]
    statutes_interpreted: list[dict[str, object]]
    statutes_applied: list[dict[str, object]]
    citations_made: list[str]
    headnotes: list[str]
    ratio_decidendi: str | None = None
    obiter_dicta: list[str]
    practice_areas: list[str]
    language: str
    full_text: str | None = None
    source_system: str | None = None
    source_url: str | None = None
    source_document_ref: str | None = None
    fetched_at: datetime | None = None
    checksum: str | None = None
    parser_version: str
    ingestion_run_id: str | None = None
    approval_status: ApprovalStatus
    validity_checked_at: datetime | None = None
    projection_stale: bool
    stale_reason: str | None = None
    appeal_history: list[AppealNodeRead]
    chunks: list[DocumentChunkRead]
    outgoing_citation_edges: list[CitationEdgeRead]
    statute_document: StatuteDocumentRead | None = None
    source_registry: SourceRegistryRead | None = None
    ingestion_run: IngestionRunRead | None = None


class CaseContextRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    case_id: str
    appellant_petitioner: str | None = None
    respondent_opposite_party: str | None = None
    advocates: list[str]
    case_type: CaseType | None = None
    court: str | None = None
    case_number: str | None = None
    stage: CaseStage | None = None
    charges_sections: list[str]
    bnss_equivalents: list[str]
    statutes_involved: list[str]
    key_facts: list[dict[str, object]]
    previous_orders: list[dict[str, object]]
    bail_history: list[dict[str, object]]
    open_legal_issues: list[str]
    uploaded_docs: list[dict[str, object]]
    doc_extraction_confidence: float
