from __future__ import annotations

from app.ingestion.adapters.supreme_court_html import SupremeCourtHtmlAdapter
from app.ingestion.contracts import ExtractedMetadata, IngestionJobContext, ParsedDocument
from app.models import LegalDocumentType


class HighCourtHtmlAdapter(SupremeCourtHtmlAdapter):
    @property
    def adapter_name(self) -> str:
        return "high-court-html-adapter"

    def extract_metadata(
        self,
        parsed: ParsedDocument,
        context: IngestionJobContext,
    ) -> ExtractedMetadata:
        metadata = super().extract_metadata(parsed, context)
        court_name = str(context.metadata.get("court_name", "Bombay High Court"))
        return ExtractedMetadata(
            doc_type=LegalDocumentType.JUDGMENT,
            court=court_name,
            date_text=metadata.date_text,
            citation=metadata.citation,
            neutral_citation=metadata.neutral_citation,
            bench=metadata.bench,
            parties=metadata.parties,
            language=metadata.language,
            source_document_ref=metadata.source_document_ref,
            attributes={
                "jurisdiction_binding": [court_name],
                "jurisdiction_persuasive": ["All India"],
                "practice_areas": self._practice_areas(context) or ["criminal"],
            },
        )
