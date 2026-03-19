from __future__ import annotations

from datetime import date as date_value
from typing import Literal

from pydantic import BaseModel

from app.models import AppealOutcome, LegalDocumentType, ValidityStatus
from app.rag.appeal import AppealSeverity, AppealValidationStatus
from app.rag.misgrounding import MisgroundingAction, MisgroundingStatus
from app.rag.resolution import CitationResolutionStatus
from app.schemas.legal import AppealNodeRead, LegalDocumentRead, StatuteSectionRead


class CitationSourceRead(BaseModel):
    doc_id: str
    effective_doc_id: str
    chunk_id: str | None = None
    effective_chunk_id: str | None = None
    doc_type: LegalDocumentType
    citation: str | None = None
    effective_citation: str | None = None
    title: str
    court: str | None = None
    date: date_value | None = None
    section_header: str | None = None
    act_name: str | None = None
    section_number: str | None = None
    current_validity: ValidityStatus
    is_in_force: bool | None = None
    source_passage: str | None = None
    source_url: str | None = None
    source_system: str | None = None
    source_document_ref: str | None = None
    appeal_status: AppealValidationStatus
    appeal_severity: AppealSeverity
    appeal_warning: str | None = None
    path_doc_ids: list[str]


class CitationSourceResponse(BaseModel):
    success: Literal[True] = True
    data: CitationSourceRead


class CitationVerificationRead(BaseModel):
    doc_id: str
    effective_doc_id: str
    chunk_id: str | None = None
    effective_chunk_id: str | None = None
    citation: str | None = None
    effective_citation: str | None = None
    resolution_status: CitationResolutionStatus
    current_validity: ValidityStatus
    is_in_force: bool | None = None
    appeal_status: AppealValidationStatus
    appeal_severity: AppealSeverity
    appeal_warning: str | None = None
    path_doc_ids: list[str]
    claim: str | None = None
    grounding_status: MisgroundingStatus | None = None
    grounding_action: MisgroundingAction | None = None
    grounding_confidence: float | None = None
    grounding_similarity: float | None = None
    source_passage: str | None = None
    message: str


class CitationVerificationResponse(BaseModel):
    success: Literal[True] = True
    data: CitationVerificationRead


class AppealChainRead(BaseModel):
    doc_id: str
    use_doc_id: str
    effective_outcome: AppealOutcome | None = None
    is_final_authority: bool
    warning: str | None = None
    path_doc_ids: list[str]
    nodes: list[AppealNodeRead]


class AppealChainResponse(BaseModel):
    success: Literal[True] = True
    data: AppealChainRead


class JudgmentResponse(BaseModel):
    success: Literal[True] = True
    data: LegalDocumentRead


class StatuteSectionLookupRead(BaseModel):
    act_id: str
    act_name: str
    section_number: str
    document: LegalDocumentRead
    section: StatuteSectionRead


class StatuteSectionLookupResponse(BaseModel):
    success: Literal[True] = True
    data: StatuteSectionLookupRead
