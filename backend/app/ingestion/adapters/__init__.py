from app.ingestion.adapters.constitution import ConstitutionDocumentAdapter
from app.ingestion.adapters.criminal_codes_bundle import CriminalCodeStatuteAdapter
from app.ingestion.adapters.high_court_html import HighCourtHtmlAdapter
from app.ingestion.adapters.indiacode import IndiaCodeActAdapter
from app.ingestion.adapters.law_commission_report_text import LawCommissionReportTextAdapter
from app.ingestion.adapters.mock import MockIngestionAdapter
from app.ingestion.adapters.pdf_legal_document import PdfLegalDocumentAdapter
from app.ingestion.adapters.supreme_court_html import SupremeCourtHtmlAdapter
from app.ingestion.adapters.tribunal_html import TribunalOrderHtmlAdapter

__all__ = [
    "ConstitutionDocumentAdapter",
    "CriminalCodeStatuteAdapter",
    "HighCourtHtmlAdapter",
    "IndiaCodeActAdapter",
    "LawCommissionReportTextAdapter",
    "MockIngestionAdapter",
    "PdfLegalDocumentAdapter",
    "SupremeCourtHtmlAdapter",
    "TribunalOrderHtmlAdapter",
]
