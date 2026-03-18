from __future__ import annotations

from datetime import date

from app.db.base import Base
from app.db.session import build_engine
from app.ingestion import IngestionJobContext, IngestionOrchestrator
from app.ingestion.adapters import SupremeCourtHtmlAdapter
from app.ingestion.citation_graph import CitationGraphProjector
from app.models import (
    ApprovalStatus,
    CitationEdge,
    LegalDocument,
    LegalDocumentType,
    ValidityStatus,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

SOURCE_SAMPLE = """
<html>
  <body>
    <h1>People's Union of India v State</h1>
    <p>Bench: Justice A, Justice B, Justice C</p>
    <p>Decision Date: 2025-03-17</p>
    <p>Official Citation: (2025) 5 SCC 200</p>
    <p>The Court followed Maneka Gandhi v Union of India, AIR 1978 SC 597.</p>
    <p>It distinguished Sanjay Chandra v CBI, (2012) 1 SCC 40.</p>
    <p>It overruled Kharak Singh v State of UP, AIR 1963 SC 1295.</p>
  </body>
</html>
"""


def _seed_judgment(
    session: Session,
    *,
    doc_id: str,
    citation: str,
    case_name: tuple[str, str],
) -> None:
    session.add(
        LegalDocument(
            doc_id=doc_id,
            doc_type=LegalDocumentType.JUDGMENT,
            court="Supreme Court",
            bench=["Justice Seed A", "Justice Seed B"],
            coram=2,
            date=date(2000, 1, 1),
            citation=citation,
            parties={"appellant": case_name[0], "respondent": case_name[1]},
            jurisdiction_binding=["All India"],
            jurisdiction_persuasive=[],
            current_validity=ValidityStatus.GOOD_LAW,
            distinguished_by=[],
            followed_by=[],
            statutes_interpreted=[],
            statutes_applied=[],
            citations_made=[],
            headnotes=[],
            obiter_dicta=[],
            practice_areas=["constitutional"],
            language="en",
            full_text="Seed judgment text.",
            source_system="supremecourt.gov.in",
            parser_version="seed-v1",
            approval_status=ApprovalStatus.APPROVED,
        )
    )


def test_citation_graph_projection_persists_edges_and_returns_neighbors(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'citation_graph.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        _seed_judgment(
            session,
            doc_id="doc-maneka-1978",
            citation="AIR 1978 SC 597",
            case_name=("Maneka Gandhi", "Union of India"),
        )
        _seed_judgment(
            session,
            doc_id="doc-sanjay-2012",
            citation="(2012) 1 SCC 40",
            case_name=("Sanjay Chandra", "CBI"),
        )
        _seed_judgment(
            session,
            doc_id="doc-kharak-1963",
            citation="AIR 1963 SC 1295",
            case_name=("Kharak Singh", "State of UP"),
        )
        session.commit()

        projector = CitationGraphProjector()
        orchestrator = IngestionOrchestrator(graph_projector=projector)
        persisted = orchestrator.ingest(
            session,
            SupremeCourtHtmlAdapter(),
            IngestionJobContext(
                source_key="supreme_court",
                source_url="https://www.sci.gov.in/judgment/peoples-union-2025",
                parser_version="supreme-court-html-v1",
                external_id="peoples-union-2025",
                inline_payload=SOURCE_SAMPLE,
            ),
        )

        source_document = session.get(LegalDocument, persisted.doc_id)
        assert source_document is not None
        assert source_document.citations_made == [
            "doc-maneka-1978",
            "doc-sanjay-2012",
            "doc-kharak-1963",
        ]

        edges = session.scalars(
            select(CitationEdge).where(CitationEdge.source_doc_id == persisted.doc_id)
        ).all()
        assert {(edge.target_doc_id, edge.citation_type) for edge in edges} == {
            ("doc-maneka-1978", "follows"),
            ("doc-sanjay-2012", "distinguishes"),
            ("doc-kharak-1963", "overrules"),
        }

        followed = session.get(LegalDocument, "doc-maneka-1978")
        assert followed is not None
        assert persisted.doc_id in followed.followed_by

        distinguished = session.get(LegalDocument, "doc-sanjay-2012")
        assert distinguished is not None
        assert persisted.doc_id in distinguished.distinguished_by

        overruled = session.get(LegalDocument, "doc-kharak-1963")
        assert overruled is not None
        assert overruled.overruled_by == persisted.doc_id
        assert overruled.current_validity is ValidityStatus.OVERRULED

        outgoing_neighbors = projector.get_neighbors(session, persisted.doc_id)
        assert {(neighbor.doc_id, neighbor.citation_type) for neighbor in outgoing_neighbors} == {
            ("doc-maneka-1978", "follows"),
            ("doc-sanjay-2012", "distinguishes"),
            ("doc-kharak-1963", "overrules"),
        }

        incoming_neighbors = projector.get_neighbors(
            session,
            "doc-maneka-1978",
            direction="incoming",
        )
        assert [(neighbor.doc_id, neighbor.citation_type) for neighbor in incoming_neighbors] == [
            (persisted.doc_id, "follows")
        ]

        cypher_statements = projector.build_neo4j_projection(session, persisted.doc_id)
        assert any(
            f"MERGE (source:JudgmentNode {{doc_id: '{persisted.doc_id}'}})" in statement
            for statement in cypher_statements
        )
        assert any(
            "MERGE (source)-[:CITES {citation_type: 'follows'}]->(target)" in statement
            for statement in cypher_statements
        )

    engine.dispose()
