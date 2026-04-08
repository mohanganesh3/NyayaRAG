from __future__ import annotations

import re
from datetime import UTC, datetime
from hashlib import sha256
from urllib.request import urlopen

from app.ingestion.chunker import LegalAwareChunker
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

_WHITESPACE_PATTERN = re.compile(r"\s+")
_YEAR_PATTERN = re.compile(r"\b(18\d{2}|19\d{2}|20\d{2})\b")


class LawCommissionReportTextAdapter(BaseIngestionAdapter):
    """Ingest Law Commission reports from extracted plain text.

    This adapter is intended to consume text extracted from PDFs (for example via
    `app.ingestion.scripts.law_commission_reports`) and project it into the canonical
    corpus as `LegalDocumentType.LC_REPORT`.
    """

    chunker = LegalAwareChunker()

    @property
    def adapter_name(self) -> str:
        return "law-commission-report-text-adapter"

    def fetch(self, context: IngestionJobContext) -> FetchedPayload:
        if context.inline_payload is not None:
            raw_content = context.inline_payload
        else:
            with urlopen(context.source_url, timeout=30) as response:
                raw_content = response.read().decode("utf-8", errors="ignore")

        return FetchedPayload(
            source_key=context.source_key,
            source_url=context.source_url,
            external_id=context.external_id,
            raw_content=raw_content,
            content_type="text/plain",
            fetched_at=datetime.now(UTC),
            checksum=sha256(raw_content.encode("utf-8")).hexdigest(),
        )

    def normalize(self, fetched: FetchedPayload, context: IngestionJobContext) -> NormalizedPayload:
        text = fetched.raw_content.replace("\r\n", "\n").replace("\r", "\n")
        # Keep line breaks for downstream paragraph detection.
        lines = [line.rstrip() for line in text.split("\n")]
        clean_text = "\n".join(lines).strip()
        return NormalizedPayload(
            source_key=fetched.source_key,
            source_url=fetched.source_url,
            raw_content=fetched.raw_content,
            clean_text=clean_text,
            lines=lines,
            checksum=fetched.checksum,
        )

    def parse(self, normalized: NormalizedPayload, context: IngestionJobContext) -> ParsedDocument:
        title = self._title_from_context(context) or self._title_from_text(normalized.clean_text)
        body_text = normalized.clean_text.strip()
        paragraphs = self._split_paragraphs(body_text)
        report_num = self._report_number(context)
        source_ref = context.external_id or (f"lc-report-{report_num}" if report_num else None)

        return ParsedDocument(
            title=title,
            body_text=body_text,
            paragraphs=paragraphs,
            section_headers=[],
            source_document_ref=source_ref,
            attributes={},
        )

    def extract_metadata(self, parsed: ParsedDocument, context: IngestionJobContext) -> ExtractedMetadata:
        report_num = self._report_number(context)
        topic = self._topic(context)
        submission_date = self._optional_str(context.metadata.get("submission_date"))
        year = self._year_from_value(submission_date) or self._year_from_value(topic) or None

        citation = None
        if report_num:
            citation = f"Law Commission Report No. {report_num}"

        return ExtractedMetadata(
            doc_type=LegalDocumentType.LC_REPORT,
            court="Law Commission of India",
            date_text=submission_date,
            citation=citation,
            neutral_citation=None,
            bench=[],
            parties={},
            language="en",
            source_document_ref=parsed.source_document_ref,
            attributes={
                "jurisdiction_binding": ["All India"],
                "jurisdiction_persuasive": [],
                "practice_areas": ["general"],
                "report_num": report_num,
                "topic": topic,
                "year": year,
            },
        )

    def extract_citations(
        self,
        parsed: ParsedDocument,
        metadata: ExtractedMetadata,
        context: IngestionJobContext,
    ) -> list[CitationCandidate]:
        return []

    def resolve_appeal_links(
        self,
        parsed: ParsedDocument,
        metadata: ExtractedMetadata,
        citations: list[CitationCandidate],
        context: IngestionJobContext,
    ) -> list[AppealLinkCandidate]:
        return []

    def chunk(
        self,
        parsed: ParsedDocument,
        metadata: ExtractedMetadata,
        context: IngestionJobContext,
    ) -> list[ChunkDraft]:
        chunks = self.chunker.chunk(parsed, metadata, context)
        # Enrich chunk attributes for vector-store payloads.
        for chunk in chunks:
            chunk.attributes.setdefault("report_num", metadata.attributes.get("report_num"))
            chunk.attributes.setdefault("topic", metadata.attributes.get("topic"))
            chunk.attributes.setdefault("year", metadata.attributes.get("year"))
        return chunks

    def embed(
        self,
        chunks: list[ChunkDraft],
        metadata: ExtractedMetadata,
        context: IngestionJobContext,
    ) -> list[EmbeddingTask]:
        return [
            EmbeddingTask(chunk_key=chunk.chunk_key, text=chunk.text, embedding_model="BGE-M3-v1.5")
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
        full_text = "\n".join(chunk.text for chunk in chunks)
        return [
            ProjectionPlan(
                target=ProjectionTarget.CANONICAL_DB,
                payload={
                    "parser_version": context.parser_version,
                    "document": {
                        "court": metadata.court,
                        "citation": metadata.citation,
                        "neutral_citation": metadata.neutral_citation,
                        "jurisdiction_binding": metadata.attributes.get("jurisdiction_binding", []),
                        "jurisdiction_persuasive": metadata.attributes.get(
                            "jurisdiction_persuasive", []
                        ),
                        "practice_areas": metadata.attributes.get("practice_areas", []),
                        "date": metadata.date_text,
                        "full_text": full_text,
                    },
                },
            ),
            ProjectionPlan(target=ProjectionTarget.VECTOR_STORE, payload={"chunk_count": len(chunks)}),
            ProjectionPlan(target=ProjectionTarget.GRAPH_STORE, payload={"citation_edges": []}),
        ]

    def _split_paragraphs(self, text: str) -> list[str]:
        if not text.strip():
            return []
        blocks = re.split(r"\n\s*\n+", text)
        paragraphs: list[str] = []
        for block in blocks:
            cleaned = self._normalize_inline(block)
            if cleaned:
                paragraphs.append(cleaned)
        return paragraphs

    def _normalize_inline(self, value: str) -> str:
        cleaned = value.strip().replace("\n", " ")
        return _WHITESPACE_PATTERN.sub(" ", cleaned).strip()

    def _title_from_context(self, context: IngestionJobContext) -> str | None:
        title = self._optional_str(context.metadata.get("report_title"))
        report_num = self._report_number(context)
        if title and report_num:
            return f"Law Commission Report No. {report_num}: {title}"
        if report_num:
            return f"Law Commission Report No. {report_num}"
        return title

    def _title_from_text(self, text: str) -> str | None:
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if not lines:
            return None
        head = self._normalize_inline(lines[0])
        if len(head) > 200:
            head = head[:200].rstrip() + "…"
        return head or None

    def _report_number(self, context: IngestionJobContext) -> str | None:
        raw = context.metadata.get("report_number")
        if raw is None:
            return None
        value = str(raw).strip()
        return value or None

    def _topic(self, context: IngestionJobContext) -> str | None:
        return self._optional_str(context.metadata.get("report_title"))

    def _year_from_value(self, value: str | None) -> str | None:
        if not value:
            return None
        match = _YEAR_PATTERN.search(value)
        return match.group(1) if match else None

    def _optional_str(self, value: object | None) -> str | None:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return None
