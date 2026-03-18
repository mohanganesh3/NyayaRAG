from __future__ import annotations

import pytest
from app.ingestion import (
    BaseIngestionAdapter,
    IngestionJobContext,
    IngestionPipelineRunner,
)
from app.ingestion.adapters import MockIngestionAdapter, SupremeCourtHtmlAdapter
from app.ingestion.contracts import ProjectionTarget
from app.models import LegalDocumentType

SUPREME_COURT_SAMPLE_HTML = """
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


@pytest.mark.parametrize(
    ("adapter", "context"),
    [
        (
            MockIngestionAdapter(),
            IngestionJobContext(
                source_key="mock_source",
                source_url="https://example.test/mock",
                parser_version="mock-parser-v1",
                external_id="mock-001",
            ),
        ),
        (
            SupremeCourtHtmlAdapter(),
            IngestionJobContext(
                source_key="supreme_court",
                source_url="https://www.sci.gov.in/judgment/puttaswamy",
                parser_version="supreme-court-html-v1",
                external_id="puttaswamy-2017",
                inline_payload=SUPREME_COURT_SAMPLE_HTML,
            ),
        ),
    ],
)
def test_adapters_conform_to_shared_ingestion_interface(
    adapter: BaseIngestionAdapter,
    context: IngestionJobContext,
) -> None:
    runner = IngestionPipelineRunner()
    result = runner.run(adapter, context)

    assert isinstance(adapter, BaseIngestionAdapter)
    assert result.adapter_name == adapter.adapter_name
    assert result.stage_trace == list(adapter.stage_names)
    assert result.metadata.doc_type is LegalDocumentType.JUDGMENT
    assert len(result.chunks) == len(result.embedding_tasks)
    assert {projection.target for projection in result.projections} == {
        ProjectionTarget.CANONICAL_DB,
        ProjectionTarget.VECTOR_STORE,
        ProjectionTarget.GRAPH_STORE,
    }


def test_supreme_court_html_adapter_extracts_realistic_metadata_and_links() -> None:
    adapter = SupremeCourtHtmlAdapter()
    context = IngestionJobContext(
        source_key="supreme_court",
        source_url="https://www.sci.gov.in/judgment/puttaswamy",
        parser_version="supreme-court-html-v1",
        external_id="puttaswamy-2017",
        inline_payload=SUPREME_COURT_SAMPLE_HTML,
    )

    result = IngestionPipelineRunner().run(adapter, context)

    assert result.parsed.title == "Justice K.S. Puttaswamy v Union of India"
    assert result.metadata.court == "Supreme Court"
    assert result.metadata.citation == "(2017) 10 SCC 1"
    assert result.metadata.neutral_citation == "2017 INSC 800"
    assert result.metadata.date_text == "August 24, 2017"
    assert result.metadata.parties == {
        "appellant": "Justice K.S. Puttaswamy",
        "respondent": "Union of India",
    }
    assert len(result.citations) == 1
    assert result.citations[0].citation_text == "AIR 1978 SC 597"
    assert result.appeal_links[0].relation == "appeal_from"
    assert result.appeal_links[0].note == "the judgment of the Delhi High Court dated 2016-10-15"
    assert result.projections[0].payload["parser_version"] == "supreme-court-html-v1"
