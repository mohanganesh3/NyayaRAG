from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from app.models import LegalDocumentType


class ProjectionTarget(StrEnum):
    CANONICAL_DB = "canonical_db"
    VECTOR_STORE = "vector_store"
    GRAPH_STORE = "graph_store"


@dataclass(slots=True)
class IngestionJobContext:
    source_key: str
    source_url: str
    parser_version: str
    external_id: str | None = None
    inline_payload: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class FetchedPayload:
    source_key: str
    source_url: str
    external_id: str | None
    raw_content: str
    content_type: str
    fetched_at: datetime
    checksum: str


@dataclass(slots=True)
class NormalizedPayload:
    source_key: str
    source_url: str
    raw_content: str
    clean_text: str
    lines: list[str]
    checksum: str


@dataclass(slots=True)
class ParsedDocument:
    title: str
    body_text: str
    paragraphs: list[str]
    section_headers: list[str]
    source_document_ref: str | None
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedMetadata:
    doc_type: LegalDocumentType
    court: str | None
    date_text: str | None
    citation: str | None
    neutral_citation: str | None
    bench: list[str]
    parties: dict[str, str]
    language: str
    source_document_ref: str | None
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class CitationCandidate:
    raw_text: str
    case_name: str | None
    citation_text: str | None
    citation_type: str


@dataclass(slots=True)
class AppealLinkCandidate:
    source_reference: str
    target_reference: str | None
    relation: str
    note: str | None = None
    court_name: str | None = None
    court_level: int | None = None
    judgment_date: str | None = None
    outcome: str | None = None
    is_final_authority: bool | None = None
    modifies_ratio: bool = False


@dataclass(slots=True)
class ChunkDraft:
    chunk_key: str
    text: str
    section_header: str | None
    chunk_index: int
    total_chunks: int
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class EmbeddingTask:
    chunk_key: str
    text: str
    embedding_model: str
    embedding_version: str | None = None
    vector_dimension: int | None = None
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ProjectionPlan:
    target: ProjectionTarget
    payload: dict[str, object]


@dataclass(slots=True)
class IngestionExecutionResult:
    adapter_name: str
    stage_trace: list[str]
    fetched: FetchedPayload
    normalized: NormalizedPayload
    parsed: ParsedDocument
    metadata: ExtractedMetadata
    citations: list[CitationCandidate]
    appeal_links: list[AppealLinkCandidate]
    chunks: list[ChunkDraft]
    embedding_tasks: list[EmbeddingTask]
    projections: list[ProjectionPlan]


class BaseIngestionAdapter(ABC):
    stage_names = (
        "fetch",
        "normalize",
        "parse",
        "extract_metadata",
        "extract_citations",
        "resolve_appeal_links",
        "chunk",
        "embed",
        "project",
    )

    @property
    @abstractmethod
    def adapter_name(self) -> str: ...

    @abstractmethod
    def fetch(self, context: IngestionJobContext) -> FetchedPayload: ...

    @abstractmethod
    def normalize(
        self,
        fetched: FetchedPayload,
        context: IngestionJobContext,
    ) -> NormalizedPayload: ...

    @abstractmethod
    def parse(
        self,
        normalized: NormalizedPayload,
        context: IngestionJobContext,
    ) -> ParsedDocument: ...

    @abstractmethod
    def extract_metadata(
        self,
        parsed: ParsedDocument,
        context: IngestionJobContext,
    ) -> ExtractedMetadata: ...

    @abstractmethod
    def extract_citations(
        self,
        parsed: ParsedDocument,
        metadata: ExtractedMetadata,
        context: IngestionJobContext,
    ) -> list[CitationCandidate]: ...

    @abstractmethod
    def resolve_appeal_links(
        self,
        parsed: ParsedDocument,
        metadata: ExtractedMetadata,
        citations: list[CitationCandidate],
        context: IngestionJobContext,
    ) -> list[AppealLinkCandidate]: ...

    @abstractmethod
    def chunk(
        self,
        parsed: ParsedDocument,
        metadata: ExtractedMetadata,
        context: IngestionJobContext,
    ) -> list[ChunkDraft]: ...

    @abstractmethod
    def embed(
        self,
        chunks: list[ChunkDraft],
        metadata: ExtractedMetadata,
        context: IngestionJobContext,
    ) -> list[EmbeddingTask]: ...

    @abstractmethod
    def project(
        self,
        metadata: ExtractedMetadata,
        citations: list[CitationCandidate],
        appeal_links: list[AppealLinkCandidate],
        chunks: list[ChunkDraft],
        embedding_tasks: list[EmbeddingTask],
        context: IngestionJobContext,
    ) -> list[ProjectionPlan]: ...
