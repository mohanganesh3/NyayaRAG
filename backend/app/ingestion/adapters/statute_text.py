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

_SECTION_PATTERN = re.compile(r"^Section\s+([0-9A-Z()]+)\s*[:.-]\s*(.+)$", re.IGNORECASE)


class StructuredStatuteTextAdapter(BaseIngestionAdapter):
    practice_areas: list[str] = []
    chunker = LegalAwareChunker()

    def fetch(self, context: IngestionJobContext) -> FetchedPayload:
        if context.inline_payload is not None:
            raw_content = context.inline_payload
        else:
            with urlopen(context.source_url, timeout=20) as response:
                raw_content = response.read().decode("utf-8")

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
        lines = [line.strip() for line in fetched.raw_content.splitlines() if line.strip()]
        return NormalizedPayload(
            source_key=fetched.source_key,
            source_url=fetched.source_url,
            raw_content=fetched.raw_content,
            clean_text="\n".join(lines),
            lines=lines,
            checksum=fetched.checksum,
        )

    def parse(self, normalized: NormalizedPayload, context: IngestionJobContext) -> ParsedDocument:
        headers: dict[str, str] = {}
        sections: list[dict[str, object]] = []
        current_section: dict[str, object] | None = None

        for line in normalized.lines:
            if ":" in line and line.split(":", maxsplit=1)[0] in {
                "Act",
                "Short Title",
                "Jurisdiction",
                "Enforcement Date",
            }:
                key, value = line.split(":", maxsplit=1)
                headers[key.lower().replace(" ", "_")] = value.strip()
                continue

            match = _SECTION_PATTERN.match(line)
            if match:
                if current_section is not None:
                    sections.append(current_section)
                current_section = {
                    "section_number": match.group(1),
                    "heading": match.group(2),
                    "text": "",
                    "original_text": "",
                    "is_in_force": True,
                    "cases_interpreting": [],
                    "amendments": [],
                }
                continue

            if current_section is not None:
                current_section["text"] = f"{current_section['text']} {line}".strip()
                current_section["original_text"] = current_section["text"]

        if current_section is not None:
            sections.append(current_section)

        title = headers.get("act", normalized.lines[0])
        return ParsedDocument(
            title=title,
            body_text="\n".join(str(section["text"]) for section in sections),
            paragraphs=[str(section["text"]) for section in sections],
            section_headers=[
                f"Section {section['section_number']} - {section['heading']}"
                for section in sections
            ],
            source_document_ref=context.external_id or title.lower().replace(" ", "-"),
            attributes={
                "statute_document": {
                    "act_name": title,
                    "short_title": headers.get("short_title"),
                    "jurisdiction": headers.get("jurisdiction", "Central"),
                    "enforcement_date": headers.get("enforcement_date"),
                    "current_validity": True,
                    "current_sections_in_force": [
                        section["section_number"] for section in sections
                    ],
                    "sections": sections,
                },
            },
        )

    def extract_metadata(
        self,
        parsed: ParsedDocument,
        context: IngestionJobContext,
    ) -> ExtractedMetadata:
        statute_document = self._statute_document_from_parsed(parsed)
        return ExtractedMetadata(
            doc_type=LegalDocumentType.STATUTE,
            court="Parliament of India",
            date_text=str(statute_document.get("enforcement_date") or "1950-01-26"),
            citation=str(statute_document["act_name"]),
            neutral_citation=None,
            bench=[],
            parties={},
            language="en",
            source_document_ref=parsed.source_document_ref,
            attributes={
                "jurisdiction_binding": ["All India"],
                "jurisdiction_persuasive": [],
                "practice_areas": self.practice_areas,
                "statute_document": statute_document,
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
        return self.chunker.chunk(parsed, metadata, context)

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
        return [
            ProjectionPlan(
                target=ProjectionTarget.CANONICAL_DB,
                payload={
                    "document": {
                        "jurisdiction_binding": ["All India"],
                        "practice_areas": self.practice_areas,
                    },
                    "statute_document": metadata.attributes["statute_document"],
                },
            ),
            ProjectionPlan(
                target=ProjectionTarget.VECTOR_STORE,
                payload={"chunk_count": len(chunks)},
            ),
            ProjectionPlan(target=ProjectionTarget.GRAPH_STORE, payload={"citation_edges": []}),
        ]

    def _statute_document_from_parsed(self, parsed: ParsedDocument) -> dict[str, object]:
        raw_value = parsed.attributes.get("statute_document", {})
        if isinstance(raw_value, dict):
            return raw_value
        return {}

    def _sections_from_statute_payload(
        self,
        statute_document: dict[str, object],
    ) -> list[dict[str, object]]:
        raw_sections = statute_document.get("sections", [])
        if isinstance(raw_sections, list):
            return [section for section in raw_sections if isinstance(section, dict)]
        return []
