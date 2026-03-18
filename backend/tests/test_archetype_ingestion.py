from __future__ import annotations

import pytest
from app.db.base import Base
from app.db.session import build_engine
from app.ingestion import IngestionJobContext, IngestionOrchestrator
from app.ingestion.adapters import (
    ConstitutionDocumentAdapter,
    CriminalCodeStatuteAdapter,
    HighCourtHtmlAdapter,
    IndiaCodeActAdapter,
    SupremeCourtHtmlAdapter,
    TribunalOrderHtmlAdapter,
)
from app.models import (
    IngestionRun,
    IngestionRunStatus,
    LegalDocument,
    LegalDocumentType,
    SourceRegistry,
)
from sqlalchemy.orm import Session

CONSTITUTION_SAMPLE = """
Constitution of India
Effective Date: 1950-01-26
Article 14: Equality before law
The State shall not deny to any person equality before the law.
Article 21: Protection of life and personal liberty
No person shall be deprived of his life or personal liberty except according
to procedure established by law.
"""

INDIACODE_SAMPLE = """
Act: Companies Act, 2013
Short Title: Companies Act
Jurisdiction: Central
Enforcement Date: 2013-08-30
Section 2: Definitions
In this Act, unless the context otherwise requires, company means a company
incorporated under this Act.
Section 185: Loan to directors
No company shall, directly or indirectly, advance any loan to any of its
directors except as provided.
"""

BNS_SAMPLE = """
Act: Bharatiya Nyaya Sanhita, 2023
Short Title: BNS
Jurisdiction: Central
Enforcement Date: 2024-07-01
Section 101: Murder
Whoever commits murder shall be punished with death or imprisonment for life.
Section 61: Criminal conspiracy
When two or more persons agree to do an illegal act, they commit criminal conspiracy.
"""

SUPREME_COURT_SAMPLE = """
<html>
  <body>
    <h1>Justice K.S. Puttaswamy v Union of India</h1>
    <p>Bench: J.S. Khehar, D.Y. Chandrachud</p>
    <p>Decision Date: August 24, 2017</p>
    <p>Neutral Citation: 2017 INSC 800</p>
    <p>Official Citation: (2017) 10 SCC 1</p>
    <h2>Background</h2>
    <p>Appeal from the judgment of the Delhi High Court dated 2016-10-15.</p>
    <p>The Court considered Maneka Gandhi v Union of India, AIR 1978 SC 597.</p>
    <h2>Holding</h2>
    <p>The right to privacy is a fundamental right under Article 21.</p>
  </body>
</html>
"""

HIGH_COURT_SAMPLE = """
<html>
  <body>
    <h1>State of Maharashtra v Arun Kumar</h1>
    <p>Bench: Justice Revati Mohite Dere, Justice Prithviraj Chavan</p>
    <p>Decision Date: 2025-02-27</p>
    <p>Official Citation: AIR 2025 Bom 10</p>
    <h2>Facts</h2>
    <p>The Court followed Gudikanti Narasimhulu v Public Prosecutor, AIR 1978 SC 429.</p>
    <h2>Holding</h2>
    <p>Prolonged incarceration was a material bail consideration.</p>
  </body>
</html>
"""

TRIBUNAL_SAMPLE = """
<html>
  <body>
    <h1>ABC Infrastructure Ltd v Registrar of Companies</h1>
    <p>Bench: Member Judicial A, Member Technical B</p>
    <p>Decision Date: 2025-03-10</p>
    <p>Official Citation: 2025 SCC OnLine NCLT 10</p>
    <h2>Background</h2>
    <p>Appeal from the company petition order dated 2024-12-01.</p>
    <p>The Tribunal relied on Innoventive Industries v ICICI Bank, (2018) 1 SCC 407.</p>
    <h2>Order</h2>
    <p>The petition was admitted and the moratorium was directed to operate.</p>
  </body>
</html>
"""


@pytest.mark.parametrize(
    ("adapter", "context", "expected_doc_type", "expects_statute"),
    [
        (
            ConstitutionDocumentAdapter(),
            IngestionJobContext(
                source_key="constitution_of_india",
                source_url="https://www.indiacode.nic.in/constitution",
                parser_version="constitution-text-v1",
                external_id="constitution-1950",
                inline_payload=CONSTITUTION_SAMPLE,
            ),
            LegalDocumentType.CONSTITUTION,
            False,
        ),
        (
            IndiaCodeActAdapter(),
            IngestionJobContext(
                source_key="india_code",
                source_url="https://www.indiacode.nic.in/companies-act-2013",
                parser_version="indiacode-text-v1",
                external_id="companies-act-2013",
                inline_payload=INDIACODE_SAMPLE,
            ),
            LegalDocumentType.STATUTE,
            True,
        ),
        (
            CriminalCodeStatuteAdapter(),
            IngestionJobContext(
                source_key="bns_bundle",
                source_url="https://www.indiacode.nic.in/bns-2023",
                parser_version="criminal-code-text-v1",
                external_id="bns-2023",
                inline_payload=BNS_SAMPLE,
            ),
            LegalDocumentType.STATUTE,
            True,
        ),
        (
            SupremeCourtHtmlAdapter(),
            IngestionJobContext(
                source_key="supreme_court",
                source_url="https://www.sci.gov.in/judgment/puttaswamy",
                parser_version="supreme-court-html-v1",
                external_id="puttaswamy-2017",
                inline_payload=SUPREME_COURT_SAMPLE,
            ),
            LegalDocumentType.JUDGMENT,
            False,
        ),
        (
            HighCourtHtmlAdapter(),
            IngestionJobContext(
                source_key="bombay_high_court",
                source_url="https://bombayhighcourt.nic.in/judgment/arun-kumar",
                parser_version="high-court-html-v1",
                external_id="bombay-hc-bail-2025",
                inline_payload=HIGH_COURT_SAMPLE,
                metadata={"court_name": "Bombay High Court", "practice_areas": ["criminal"]},
            ),
            LegalDocumentType.JUDGMENT,
            False,
        ),
        (
            TribunalOrderHtmlAdapter(),
            IngestionJobContext(
                source_key="nclt",
                source_url="https://nclt.gov.in/order/abc-infrastructure",
                parser_version="tribunal-html-v1",
                external_id="nclt-abc-infrastructure-2025",
                inline_payload=TRIBUNAL_SAMPLE,
                metadata={"court_name": "NCLT Principal Bench", "practice_areas": ["corporate"]},
            ),
            LegalDocumentType.ORDER,
            False,
        ),
    ],
)
def test_archetype_source_ingestion_persists_into_canonical_db(
    tmp_path,
    adapter,
    context,
    expected_doc_type,
    expects_statute,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'archetype_ingestion.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    orchestrator = IngestionOrchestrator()

    with Session(engine) as session:
        persisted = orchestrator.ingest(session, adapter, context)

        legal_document = session.get(LegalDocument, persisted.doc_id)
        assert legal_document is not None
        assert legal_document.doc_type is expected_doc_type
        assert legal_document.source_system == context.source_key
        assert legal_document.source_url == context.source_url
        assert legal_document.source_document_ref == context.external_id
        assert legal_document.checksum is not None
        assert legal_document.parser_version == context.parser_version
        assert legal_document.ingestion_run_id == persisted.ingestion_run_id
        assert len(legal_document.chunks) > 0

        source_registry = session.get(SourceRegistry, context.source_key)
        assert source_registry is not None
        assert source_registry.default_parser_version == context.parser_version

        ingestion_run = session.get(IngestionRun, persisted.ingestion_run_id)
        assert ingestion_run is not None
        assert ingestion_run.source_key == context.source_key
        assert ingestion_run.status is IngestionRunStatus.SUCCEEDED
        assert ingestion_run.document_count == 1

        if expects_statute:
            assert legal_document.statute_document is not None
            assert len(legal_document.statute_document.sections) > 0
        else:
            assert legal_document.statute_document is None

    engine.dispose()
