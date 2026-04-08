from __future__ import annotations

import io
import re
from datetime import UTC, datetime
from hashlib import sha256
from urllib.parse import urlparse

from pypdf import PdfReader

from app.ingestion.chunker import LegalAwareChunker
from app.ingestion.http_client import robust_get
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


class PdfLegalDocumentAdapter(BaseIngestionAdapter):
    """Ingest a PDF (or plain text) URL into the canonical corpus.

    This adapter is intentionally generic and driven by `context.metadata`.
    Expected metadata keys:
    - court_name: str | None
    - doc_type: one of {order, judgment, circular, notification, lc_report, cab_debate}
    - practice_areas: list[str]
    - jurisdiction_binding / jurisdiction_persuasive: list[str]
    - title: str | None
    - date_text: str | None
    - bench: list[str] | str | None
    - parties: dict[str, str] | None
    - ssl_verify: bool (defaults True)
    """

    chunker = LegalAwareChunker()

    @property
    def adapter_name(self) -> str:
        return "pdf-legal-document-adapter"

    def fetch(self, context: IngestionJobContext) -> FetchedPayload:
        if context.inline_payload is not None:
            raw_text = context.inline_payload
            checksum = sha256(raw_text.encode("utf-8")).hexdigest()
            return FetchedPayload(
                source_key=context.source_key,
                source_url=context.source_url,
                external_id=context.external_id,
                raw_content=raw_text,
                content_type="text/plain",
                fetched_at=datetime.now(UTC),
                checksum=checksum,
            )

        ssl_verify = bool(context.metadata.get("ssl_verify", True))
        headers = {
            # Mirror a normal browser UA; some portals serve PDFs only to realistic clients.
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

        # Optional per-source overrides for portals that require referrers/cookies.
        extra_headers = context.metadata.get("http_headers")
        if isinstance(extra_headers, dict):
            for k, v in extra_headers.items():
                if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip():
                    headers[k] = v

        resp = robust_get(
            context.source_url,
            headers=headers,
            timeout=60,
            verify=ssl_verify,
        )
        resp.raise_for_status()
        content = resp.content
        checksum = sha256(content).hexdigest()

        content_type = (resp.headers.get("content-type") or "").lower()
        magic = content.lstrip()[:4]
        is_pdf = "application/pdf" in content_type or magic == b"%PDF"

        if is_pdf:
            raw_text = self._extract_pdf_text(content)
        else:
            raw_text = resp.text

        return FetchedPayload(
            source_key=context.source_key,
            source_url=context.source_url,
            external_id=context.external_id,
            raw_content=raw_text,
            content_type="text/plain" if is_pdf else "text/html",
            fetched_at=datetime.now(UTC),
            checksum=checksum,
        )

    def normalize(self, fetched: FetchedPayload, context: IngestionJobContext) -> NormalizedPayload:
        text = fetched.raw_content.replace("\r\n", "\n").replace("\r", "\n")
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
        if title is None:
            title = self._title_from_url(context.source_url)

        body_text = normalized.clean_text.strip()
        paragraphs = self._split_paragraphs(body_text)
        source_ref = context.external_id or self._title_from_url(context.source_url)

        return ParsedDocument(
            title=title,
            body_text=body_text,
            paragraphs=paragraphs,
            section_headers=[],
            source_document_ref=source_ref,
            attributes={},
        )

    def extract_metadata(self, parsed: ParsedDocument, context: IngestionJobContext) -> ExtractedMetadata:
        court_name = self._optional_str(context.metadata.get("court_name"))
        date_text = (
            self._optional_str(context.metadata.get("date_text"))
            or self._optional_str(context.metadata.get("date"))
        )
        citation = self._optional_str(context.metadata.get("citation"))
        neutral_citation = self._optional_str(context.metadata.get("neutral_citation"))
        doc_type = self._doc_type_from_context(context)

        jurisdiction_binding = context.metadata.get("jurisdiction_binding")
        if not isinstance(jurisdiction_binding, list):
            jurisdiction_binding = [court_name] if court_name else ["All India"]

        jurisdiction_persuasive = context.metadata.get("jurisdiction_persuasive")
        if not isinstance(jurisdiction_persuasive, list):
            jurisdiction_persuasive = ["All India"]

        practice_areas = context.metadata.get("practice_areas")
        if not isinstance(practice_areas, list):
            practice_areas = []

        bench: list[str] = []
        bench_meta = context.metadata.get("bench")
        if isinstance(bench_meta, list):
            bench = [str(x).strip() for x in bench_meta if str(x).strip()]
        elif isinstance(bench_meta, str) and bench_meta.strip():
            bench = [bench_meta.strip()]

        parties: dict[str, str] = {}
        parties_meta = context.metadata.get("parties")
        if isinstance(parties_meta, dict):
            for key, value in parties_meta.items():
                key_text = str(key).strip()
                value_text = str(value).strip()
                if key_text and value_text:
                    parties[key_text] = value_text

        return ExtractedMetadata(
            doc_type=doc_type,
            court=court_name,
            date_text=date_text,
            citation=citation,
            neutral_citation=neutral_citation,
            bench=bench,
            parties=parties,
            language="en",
            source_document_ref=parsed.source_document_ref,
            attributes={
                "jurisdiction_binding": [str(x) for x in jurisdiction_binding if str(x).strip()],
                "jurisdiction_persuasive": [
                    str(x) for x in jurisdiction_persuasive if str(x).strip()
                ],
                "practice_areas": [str(x) for x in practice_areas if str(x).strip()],
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

    def _extract_pdf_text(self, pdf_bytes: bytes) -> str:
        # Prefer PyMuPDF when available; it's generally faster and more reliable on scanned/complex PDFs.
        try:
            import fitz  # type: ignore[import-not-found]

            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            try:
                parts: list[str] = []
                for page in doc:
                    text = page.get_text("text") or ""
                    text = _WHITESPACE_PATTERN.sub(" ", text).strip()
                    if text:
                        parts.append(text)
                joined = "\n".join(parts).strip()
                if joined:
                    return joined
            finally:
                doc.close()
        except Exception:
            # Fall back to pypdf below.
            pass

        reader = PdfReader(io.BytesIO(pdf_bytes))
        parts2: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            text = _WHITESPACE_PATTERN.sub(" ", text).strip()
            if text:
                parts2.append(text)
        return "\n".join(parts2).strip()

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
        return self._optional_str(context.metadata.get("title"))

    def _title_from_text(self, text: str) -> str | None:
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if not lines:
            return None
        head = self._normalize_inline(lines[0])
        if len(head) > 200:
            head = head[:200].rstrip() + "…"
        return head or None

    def _title_from_url(self, url: str) -> str:
        path = urlparse(url).path
        tail = path.rstrip("/").split("/")[-1] or "document"
        return tail

    def _optional_str(self, value: object | None) -> str | None:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return None

    def _doc_type_from_context(self, context: IngestionJobContext) -> LegalDocumentType:
        raw = context.metadata.get("doc_type")
        if isinstance(raw, LegalDocumentType):
            return raw
        key = str(raw or "order").strip().lower()
        if key in {"order", "final_order"}:
            return LegalDocumentType.ORDER
        if key in {"judgment", "judgement"}:
            return LegalDocumentType.JUDGMENT
        # Some sources (CBIC) publish "instructions" that are semantically close to circulars.
        # We currently map them to CIRCULAR to avoid expanding the LegalDocumentType enum.
        if key in {"circular", "instruction", "instructions"}:
            return LegalDocumentType.CIRCULAR
        if key in {"notification"}:
            return LegalDocumentType.NOTIFICATION
        if key in {"constitution", "constitutional_text"}:
            return LegalDocumentType.CONSTITUTION
        if key in {"lc_report", "law_commission_report", "law-commission-report"}:
            return LegalDocumentType.LC_REPORT
        if key in {"cab_debate", "ca_debate", "constituent_assembly_debate"}:
            return LegalDocumentType.CAB_DEBATE
        return LegalDocumentType.ORDER
