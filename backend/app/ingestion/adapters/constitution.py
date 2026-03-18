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

_ARTICLE_PATTERN = re.compile(r"^Article\s+([0-9A-Z]+)\s*[:.-]\s*(.+)$")


class ConstitutionDocumentAdapter(BaseIngestionAdapter):
    chunker = LegalAwareChunker()

    @property
    def adapter_name(self) -> str:
        return "constitution-document-adapter"

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
        title = normalized.lines[0]
        effective_date = None
        articles: list[dict[str, str]] = []
        current_article: dict[str, str] | None = None

        for line in normalized.lines[1:]:
            if line.startswith("Effective Date:"):
                effective_date = line.split(":", maxsplit=1)[1].strip()
                continue
            match = _ARTICLE_PATTERN.match(line)
            if match:
                if current_article is not None:
                    articles.append(current_article)
                current_article = {
                    "article_number": match.group(1),
                    "heading": match.group(2),
                    "text": "",
                }
                continue
            if current_article is not None:
                current_article["text"] = f"{current_article['text']} {line}".strip()

        if current_article is not None:
            articles.append(current_article)

        paragraphs = [article["text"] for article in articles]
        section_headers = [
            f"Article {article['article_number']} - {article['heading']}"
            for article in articles
        ]
        return ParsedDocument(
            title=title,
            body_text="\n".join(paragraphs),
            paragraphs=paragraphs,
            section_headers=section_headers,
            source_document_ref=context.external_id or "constitution-of-india",
            attributes={
                "effective_date": effective_date,
                "articles": articles,
                "headnotes": section_headers,
            },
        )

    def extract_metadata(
        self,
        parsed: ParsedDocument,
        context: IngestionJobContext,
    ) -> ExtractedMetadata:
        return ExtractedMetadata(
            doc_type=LegalDocumentType.CONSTITUTION,
            court="Republic of India",
            date_text=str(parsed.attributes.get("effective_date") or "1950-01-26"),
            citation="Constitution of India",
            neutral_citation=None,
            bench=[],
            parties={},
            language="en",
            source_document_ref=parsed.source_document_ref,
            attributes={
                "jurisdiction_binding": ["All India"],
                "jurisdiction_persuasive": [],
                "practice_areas": ["constitutional"],
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
                        "practice_areas": ["constitutional"],
                    },
                },
            ),
            ProjectionPlan(
                target=ProjectionTarget.VECTOR_STORE,
                payload={"chunk_count": len(chunks)},
            ),
            ProjectionPlan(target=ProjectionTarget.GRAPH_STORE, payload={"citation_edges": []}),
        ]

    def _articles_from_parsed(self, parsed: ParsedDocument) -> list[dict[str, str]]:
        raw_articles = parsed.attributes.get("articles", [])
        if isinstance(raw_articles, list):
            return [article for article in raw_articles if isinstance(article, dict)]
        return []
