from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from app.ingestion.contracts import (
    AppealLinkCandidate,
    BaseIngestionAdapter,
    ChunkDraft,
    CitationCandidate,
    EmbeddingTask,
    ExtractedMetadata,
    FetchedPayload,
    IngestionJobContext,
    NormalizedPayload,
    ParsedDocument,
    ProjectionPlan,
    ProjectionTarget,
)
from app.models import LegalDocumentType


class MockIngestionAdapter(BaseIngestionAdapter):
    @property
    def adapter_name(self) -> str:
        return "mock-ingestion-adapter"

    def fetch(self, context: IngestionJobContext) -> FetchedPayload:
        raw_content = context.inline_payload or (
            "Mock judgment title\n"
            "Mock Bench: Justice A, Justice B\n"
            "Mock Citation: (2025) 1 SCC 999\n"
            "The mock adapter cites Test Case v Union of India, AIR 1978 SC 597."
        )
        return FetchedPayload(
            source_key=context.source_key,
            source_url=context.source_url,
            external_id=context.external_id,
            raw_content=raw_content,
            content_type="text/plain",
            fetched_at=datetime.now(UTC),
            checksum=sha256(raw_content.encode("utf-8")).hexdigest(),
        )

    def normalize(
        self,
        fetched: FetchedPayload,
        context: IngestionJobContext,
    ) -> NormalizedPayload:
        clean_text = "\n".join(
            line.strip()
            for line in fetched.raw_content.splitlines()
            if line.strip()
        )
        return NormalizedPayload(
            source_key=fetched.source_key,
            source_url=fetched.source_url,
            raw_content=fetched.raw_content,
            clean_text=clean_text,
            lines=clean_text.splitlines(),
            checksum=fetched.checksum,
        )

    def parse(
        self,
        normalized: NormalizedPayload,
        context: IngestionJobContext,
    ) -> ParsedDocument:
        lines = normalized.lines
        title = lines[0] if lines else "Mock judgment title"
        paragraphs = lines[1:] if len(lines) > 1 else [normalized.clean_text]
        return ParsedDocument(
            title=title,
            body_text="\n".join(paragraphs),
            paragraphs=paragraphs,
            section_headers=["Mock Facts", "Mock Holding"],
            source_document_ref=context.external_id or "mock-doc-1",
        )

    def extract_metadata(
        self,
        parsed: ParsedDocument,
        context: IngestionJobContext,
    ) -> ExtractedMetadata:
        return ExtractedMetadata(
            doc_type=LegalDocumentType.JUDGMENT,
            court="Supreme Court",
            date_text="2025-01-15",
            citation="(2025) 1 SCC 999",
            neutral_citation="2025 INSC 999",
            bench=["Justice A", "Justice B"],
            parties={"appellant": "Mock Appellant", "respondent": "Union of India"},
            language="en",
            source_document_ref=parsed.source_document_ref,
        )

    def extract_citations(
        self,
        parsed: ParsedDocument,
        metadata: ExtractedMetadata,
        context: IngestionJobContext,
    ) -> list[CitationCandidate]:
        return [
            CitationCandidate(
                raw_text="Test Case v Union of India, AIR 1978 SC 597",
                case_name="Test Case v Union of India",
                citation_text="AIR 1978 SC 597",
                citation_type="refers_to",
            )
        ]

    def resolve_appeal_links(
        self,
        parsed: ParsedDocument,
        metadata: ExtractedMetadata,
        citations: list[CitationCandidate],
        context: IngestionJobContext,
    ) -> list[AppealLinkCandidate]:
        return [
            AppealLinkCandidate(
                source_reference=metadata.citation or parsed.title,
                target_reference="AIR 1978 SC 597",
                relation="follows",
                note="Mock appeal-link resolution output.",
            )
        ]

    def chunk(
        self,
        parsed: ParsedDocument,
        metadata: ExtractedMetadata,
        context: IngestionJobContext,
    ) -> list[ChunkDraft]:
        paragraphs = parsed.paragraphs or [parsed.body_text]
        return [
            ChunkDraft(
                chunk_key=f"{parsed.source_document_ref}-chunk-{index}",
                text=paragraph,
                section_header="Mock Facts" if index == 0 else "Mock Holding",
                chunk_index=index,
                total_chunks=len(paragraphs),
            )
            for index, paragraph in enumerate(paragraphs)
        ]

    def embed(
        self,
        chunks: list[ChunkDraft],
        metadata: ExtractedMetadata,
        context: IngestionJobContext,
    ) -> list[EmbeddingTask]:
        return [
            EmbeddingTask(
                chunk_key=chunk.chunk_key,
                text=chunk.text,
                embedding_model="BGE-M3-v1.5",
            )
            for chunk in chunks
        ]

    def project(
        self,
        metadata: ExtractedMetadata,
        citations: list[CitationCandidate],
        appeal_links: list[AppealLinkCandidate],
        chunks: list[ChunkDraft],
        embedding_tasks: list[EmbeddingTask],
        context: IngestionJobContext,
    ) -> list[ProjectionPlan]:
        return [
            ProjectionPlan(
                target=ProjectionTarget.CANONICAL_DB,
                payload={
                    "source_key": context.source_key,
                    "citation": metadata.citation,
                    "doc_type": metadata.doc_type.value,
                    "chunk_count": len(chunks),
                    "parser_version": context.parser_version,
                },
            ),
            ProjectionPlan(
                target=ProjectionTarget.VECTOR_STORE,
                payload={
                    "embedding_model": "BGE-M3-v1.5",
                    "chunk_keys": [task.chunk_key for task in embedding_tasks],
                },
            ),
            ProjectionPlan(
                target=ProjectionTarget.GRAPH_STORE,
                payload={
                    "citation_count": len(citations),
                    "appeal_link_count": len(appeal_links),
                },
            ),
        ]
