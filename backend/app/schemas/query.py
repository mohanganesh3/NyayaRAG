from datetime import date as date_value
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class QueryType(StrEnum):
    STATUTORY_LOOKUP = "statutory_lookup"
    CASE_SPECIFIC = "case_specific"
    MULTI_HOP_DOCTRINE = "multi_hop_doctrine"
    CONSTITUTIONAL = "constitutional"
    VAGUE_NATURAL = "vague_natural"
    DOCUMENT_SPECIFIC = "document_specific"
    COMPARATIVE = "comparative"
    GENERAL_LEGAL = "general_legal"


class PipelineType(StrEnum):
    HYBRID_RAG = "hybrid_rag"
    HYBRID_CRAG = "hybrid_crag"
    GRAPH_RAG = "graph_rag"
    GRAPH_HYBRID = "graph_hybrid"
    HYDE_HYBRID = "hyde_hybrid"
    AGENTIC_RAG = "agentic_rag"


class PracticeArea(StrEnum):
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
    PROCEDURE = "procedure"
    GENERAL = "general"


class QueryEntityType(StrEnum):
    CASE_NAME = "case_name"
    COURT = "court"
    ACT = "act"
    SECTION = "section"
    ARTICLE = "article"


class QueryEntity(BaseModel):
    text: str
    entity_type: QueryEntityType


class QueryAnalysis(BaseModel):
    raw_query: str
    normalized_query: str
    query_type: QueryType
    confidence: float
    jurisdiction_court: str
    jurisdiction_state: str
    jurisdiction_binding: list[str] = Field(default_factory=list)
    time_sensitive: bool
    reference_date: date_value
    post_july_2024: bool
    practice_area: PracticeArea
    sections_mentioned: list[str] = Field(default_factory=list)
    bnss_equivalents: list[str] = Field(default_factory=list)
    entities: list[QueryEntity] = Field(default_factory=list)
    is_vague: bool
    requires_multi_hop: bool
    requires_comparison: bool
    has_uploaded_docs: bool
    selected_pipeline: PipelineType
    pipeline_reason: str


class QuerySubmissionRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    workspace_id: str | None = None


class QueryAcceptedData(BaseModel):
    query_id: str
    status: Literal["accepted"]
    stream_url: str
    created_at: datetime


class QueryAcceptedResponse(BaseModel):
    success: Literal[True] = True
    data: QueryAcceptedData


class QueryHistoryEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    query_id: str
    auth_user_id: str | None = None
    auth_session_id: str | None = None
    auth_provider: str | None = None
    workspace_id: str | None = None
    query_text: str
    pipeline: str | None = None
    status: str
    answer_preview: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class QueryHistoryResponse(BaseModel):
    success: Literal[True] = True
    data: list[QueryHistoryEntryRead]
