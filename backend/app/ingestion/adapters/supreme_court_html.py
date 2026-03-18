from __future__ import annotations

import re
from datetime import UTC, datetime
from hashlib import sha256
from html import unescape
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

_TAG_BREAK_PATTERN = re.compile(r"<(?:/p|/div|/h1|/h2|/h3|br\s*/?)>", re.IGNORECASE)
_TAG_STRIP_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"\s+")
_TITLE_PATTERN = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_HEADING_PATTERN = re.compile(r"<h[23][^>]*>(.*?)</h[23]>", re.IGNORECASE | re.DOTALL)
_PARAGRAPH_PATTERN = re.compile(r"<p[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
_DATE_PATTERN = re.compile(
    r"(\d{4}-\d{2}-\d{2}|[A-Z][a-z]+ \d{1,2}, \d{4})",
    re.IGNORECASE,
)
_CITATION_PATTERN = re.compile(r"(\(\d{4}\)\s*\d+\s*SCC\s*\d+|AIR\s+\d{4}\s+SC\s+\d+)")
_NEUTRAL_CITATION_PATTERN = re.compile(r"(\d{4}\s+INSC\s+\d+)", re.IGNORECASE)
_CASE_PATTERN = re.compile(
    r"([A-Z][A-Za-z0-9 .,&'-]+?\s+v(?:s\.?|\.?)\s+[A-Z][A-Za-z0-9 .,&'-]+)"
)
_BENCH_PATTERN = re.compile(r"(?:Coram|Bench)\s*:\s*([^\n]+)", re.IGNORECASE)
_APPEAL_PATTERN = re.compile(r"Appeal from ([^.]+)\.", re.IGNORECASE)


class SupremeCourtHtmlAdapter(BaseIngestionAdapter):
    chunker = LegalAwareChunker()

    @property
    def adapter_name(self) -> str:
        return "supreme-court-html-adapter"

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
            content_type="text/html",
            fetched_at=datetime.now(UTC),
            checksum=sha256(raw_content.encode("utf-8")).hexdigest(),
        )

    def normalize(
        self,
        fetched: FetchedPayload,
        context: IngestionJobContext,
    ) -> NormalizedPayload:
        text_with_breaks = _TAG_BREAK_PATTERN.sub("\n", fetched.raw_content)
        plain_text = _TAG_STRIP_PATTERN.sub(" ", text_with_breaks)
        clean_text = unescape(plain_text)
        lines = [
            _WHITESPACE_PATTERN.sub(" ", line).strip()
            for line in clean_text.splitlines()
            if line.strip()
        ]
        return NormalizedPayload(
            source_key=fetched.source_key,
            source_url=fetched.source_url,
            raw_content=fetched.raw_content,
            clean_text="\n".join(lines),
            lines=lines,
            checksum=fetched.checksum,
        )

    def parse(
        self,
        normalized: NormalizedPayload,
        context: IngestionJobContext,
    ) -> ParsedDocument:
        title_match = _TITLE_PATTERN.search(normalized.raw_content)
        title = self._clean_fragment(title_match.group(1)) if title_match else normalized.lines[0]
        paragraphs = [
            self._clean_fragment(fragment)
            for fragment in _PARAGRAPH_PATTERN.findall(normalized.raw_content)
            if self._clean_fragment(fragment)
        ]
        if not paragraphs:
            paragraphs = normalized.lines[1:] if len(normalized.lines) > 1 else normalized.lines

        section_headers = [
            self._clean_fragment(fragment)
            for fragment in _HEADING_PATTERN.findall(normalized.raw_content)
            if self._clean_fragment(fragment)
        ]
        body_text = "\n".join(paragraphs)

        return ParsedDocument(
            title=title,
            body_text=body_text,
            paragraphs=paragraphs,
            section_headers=section_headers,
            source_document_ref=(
                context.external_id
                or context.source_url.rstrip("/").split("/")[-1]
            ),
        )

    def extract_metadata(
        self,
        parsed: ParsedDocument,
        context: IngestionJobContext,
    ) -> ExtractedMetadata:
        title_and_body = f"{parsed.title}\n{parsed.body_text}"
        citation_match = _CITATION_PATTERN.search(title_and_body)
        neutral_citation_match = _NEUTRAL_CITATION_PATTERN.search(title_and_body)
        date_match = _DATE_PATTERN.search(title_and_body)
        bench_match = _BENCH_PATTERN.search(title_and_body)
        bench = self._split_bench(bench_match.group(1)) if bench_match else []
        parties = self._extract_parties(parsed.title)

        return ExtractedMetadata(
            doc_type=LegalDocumentType.JUDGMENT,
            court="Supreme Court",
            date_text=date_match.group(1) if date_match else None,
            citation=citation_match.group(1) if citation_match else None,
            neutral_citation=neutral_citation_match.group(1) if neutral_citation_match else None,
            bench=bench,
            parties=parties,
            language="en",
            source_document_ref=parsed.source_document_ref,
            attributes={
                "jurisdiction_binding": ["All India"],
                "jurisdiction_persuasive": [],
                "practice_areas": self._practice_areas(context),
            },
        )

    def extract_citations(
        self,
        parsed: ParsedDocument,
        metadata: ExtractedMetadata,
        context: IngestionJobContext,
    ) -> list[CitationCandidate]:
        candidates: list[CitationCandidate] = []
        seen: set[tuple[str | None, str | None]] = set()
        for paragraph in parsed.paragraphs:
            citation_match = _CITATION_PATTERN.search(paragraph)
            if citation_match is None:
                continue
            case_match = _CASE_PATTERN.search(paragraph)
            if case_match is None and citation_match.group(1) == metadata.citation:
                continue
            key = (
                case_match.group(1) if case_match else None,
                citation_match.group(1),
            )
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                CitationCandidate(
                    raw_text=paragraph,
                    case_name=case_match.group(1) if case_match else None,
                    citation_text=citation_match.group(1),
                    citation_type="refers_to",
                )
            )
        return candidates

    def resolve_appeal_links(
        self,
        parsed: ParsedDocument,
        metadata: ExtractedMetadata,
        citations: list[CitationCandidate],
        context: IngestionJobContext,
    ) -> list[AppealLinkCandidate]:
        links: list[AppealLinkCandidate] = []
        for paragraph in parsed.paragraphs:
            appeal_match = _APPEAL_PATTERN.search(paragraph)
            if appeal_match is None:
                continue
            links.append(
                AppealLinkCandidate(
                    source_reference=metadata.citation or parsed.title,
                    target_reference=None,
                    relation="appeal_from",
                    note=appeal_match.group(1),
                )
            )
        return links

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
                    "parser_version": context.parser_version,
                    "document": {
                        "court": metadata.court,
                        "citation": metadata.citation,
                        "neutral_citation": metadata.neutral_citation,
                        "jurisdiction_binding": metadata.attributes.get("jurisdiction_binding", []),
                        "jurisdiction_persuasive": metadata.attributes.get(
                            "jurisdiction_persuasive",
                            [],
                        ),
                        "practice_areas": metadata.attributes.get("practice_areas", []),
                        "full_text": "\n".join(chunk.text for chunk in chunks),
                    },
                },
            ),
            ProjectionPlan(
                target=ProjectionTarget.VECTOR_STORE,
                payload={
                    "embedding_model": "BGE-M3-v1.5",
                    "chunks": [chunk.chunk_key for chunk in chunks],
                    "tasks": [task.chunk_key for task in embedding_tasks],
                },
            ),
            ProjectionPlan(
                target=ProjectionTarget.GRAPH_STORE,
                payload={
                    "citation_edges": [candidate.citation_text for candidate in citations],
                    "appeal_links": [link.note for link in appeal_links],
                },
            ),
        ]

    def _clean_fragment(self, fragment: str) -> str:
        plain_text = _TAG_STRIP_PATTERN.sub(" ", fragment)
        return _WHITESPACE_PATTERN.sub(" ", unescape(plain_text)).strip()

    def _extract_parties(self, title: str) -> dict[str, str]:
        if " v " in title:
            appellant, respondent = title.split(" v ", maxsplit=1)
        elif " vs " in title:
            appellant, respondent = title.split(" vs ", maxsplit=1)
        elif " vs. " in title:
            appellant, respondent = title.split(" vs. ", maxsplit=1)
        else:
            return {}
        return {
            "appellant": appellant.strip(),
            "respondent": respondent.strip(),
        }

    def _split_bench(self, raw_bench: str) -> list[str]:
        return [name.strip() for name in raw_bench.split(",") if name.strip()]

    def _practice_areas(self, context: IngestionJobContext) -> list[str]:
        value = context.metadata.get("practice_areas", [])
        if isinstance(value, list):
            return [str(area) for area in value]
        return []
