from __future__ import annotations

from datetime import date

from app.db.base import Base
from app.db.session import build_engine
from app.models import CitationEdge, DocumentChunk, LegalDocument, LegalDocumentType, ValidityStatus
from app.rag import GraphRAGPipeline, QueryRouter
from sqlalchemy.orm import Session


def _seed_doctrinal_judgment(
    session: Session,
    *,
    doc_id: str,
    citation: str,
    court: str,
    judgment_date: date,
    coram: int,
    case_name: tuple[str, str],
    text: str,
    validity: ValidityStatus = ValidityStatus.GOOD_LAW,
) -> None:
    session.add(
        LegalDocument(
            doc_id=doc_id,
            doc_type=LegalDocumentType.JUDGMENT,
            court=court,
            bench=[f"Justice {index}" for index in range(coram)],
            coram=coram,
            date=judgment_date,
            citation=citation,
            parties={"appellant": case_name[0], "respondent": case_name[1]},
            jurisdiction_binding=["All India"],
            jurisdiction_persuasive=[],
            current_validity=validity,
            distinguished_by=[],
            followed_by=[],
            statutes_interpreted=[],
            statutes_applied=[],
            citations_made=[],
            headnotes=["Privacy and Article 21 doctrine"],
            ratio_decidendi=text,
            obiter_dicta=[],
            practice_areas=["constitutional"],
            language="en",
            full_text=text,
            parser_version="seed-v1",
        )
    )
    session.add(
        DocumentChunk(
            chunk_id=f"{doc_id}-chunk-0",
            doc_id=doc_id,
            doc_type=LegalDocumentType.JUDGMENT,
            text=text,
            text_normalized=text.lower(),
            chunk_index=0,
            total_chunks=1,
            section_header="Holding",
            court=court,
            citation=citation,
            jurisdiction_binding=["All India"],
            jurisdiction_persuasive=[],
            current_validity=validity,
            practice_area=["constitutional"],
        )
    )


def _seed_edge(
    session: Session,
    *,
    edge_id: str,
    source_doc_id: str,
    target_doc_id: str,
    citation_type: str,
) -> None:
    session.add(
        CitationEdge(
            id=edge_id,
            source_doc_id=source_doc_id,
            target_doc_id=target_doc_id,
            citation_type=citation_type,
        )
    )


def test_graph_rag_returns_ordered_privacy_doctrine_chain_and_prunes_overruled_nodes(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'graph_rag.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    pipeline = GraphRAGPipeline(router=QueryRouter())

    with Session(engine) as session:
        _seed_doctrinal_judgment(
            session,
            doc_id="doc-gopalan-1950",
            citation="AIR 1950 SC 27",
            court="Supreme Court",
            judgment_date=date(1950, 5, 19),
            coram=6,
            case_name=("A.K. Gopalan", "State of Madras"),
            text="A.K. Gopalan adopted a narrow reading of liberty under Article 21.",
            validity=ValidityStatus.OVERRULED,
        )
        _seed_doctrinal_judgment(
            session,
            doc_id="doc-maneka-1978",
            citation="AIR 1978 SC 597",
            court="Supreme Court",
            judgment_date=date(1978, 1, 25),
            coram=7,
            case_name=("Maneka Gandhi", "Union of India"),
            text=(
                "Maneka Gandhi held that procedure under Article 21 must be fair, just, "
                "and reasonable, expanding the due process doctrine."
            ),
        )
        _seed_doctrinal_judgment(
            session,
            doc_id="doc-rajagopal-1994",
            citation="(1994) 6 SCC 632",
            court="Supreme Court",
            judgment_date=date(1994, 10, 7),
            coram=2,
            case_name=("R. Rajagopal", "State of Tamil Nadu"),
            text="R. Rajagopal recognized privacy as part of Article 21 in the press context.",
        )
        _seed_doctrinal_judgment(
            session,
            doc_id="doc-pucl-1996",
            citation="(1997) 1 SCC 301",
            court="Supreme Court",
            judgment_date=date(1996, 12, 18),
            coram=2,
            case_name=("PUCL", "Union of India"),
            text="PUCL held that telephone tapping infringes privacy protected by Article 21.",
        )
        _seed_doctrinal_judgment(
            session,
            doc_id="doc-puttaswamy-2017",
            citation="(2017) 10 SCC 1",
            court="Supreme Court",
            judgment_date=date(2017, 8, 24),
            coram=9,
            case_name=("Justice K.S. Puttaswamy", "Union of India"),
            text=(
                "Puttaswamy held that privacy is a fundamental right under Article 21 "
                "and affirmed the full constitutional privacy doctrine."
            ),
        )
        _seed_edge(
            session,
            edge_id="edge-maneka-gopalan-overrules",
            source_doc_id="doc-maneka-1978",
            target_doc_id="doc-gopalan-1950",
            citation_type="overrules",
        )
        _seed_edge(
            session,
            edge_id="edge-rajagopal-maneka-follows",
            source_doc_id="doc-rajagopal-1994",
            target_doc_id="doc-maneka-1978",
            citation_type="follows",
        )
        _seed_edge(
            session,
            edge_id="edge-pucl-rajagopal-follows",
            source_doc_id="doc-pucl-1996",
            target_doc_id="doc-rajagopal-1994",
            citation_type="follows",
        )
        _seed_edge(
            session,
            edge_id="edge-puttaswamy-pucl-follows",
            source_doc_id="doc-puttaswamy-2017",
            target_doc_id="doc-pucl-1996",
            citation_type="follows",
        )
        _seed_edge(
            session,
            edge_id="edge-puttaswamy-maneka-explains",
            source_doc_id="doc-puttaswamy-2017",
            target_doc_id="doc-maneka-1978",
            citation_type="explains",
        )
        session.commit()

        results = pipeline.retrieve(
            session,
            "How has the right to privacy developed in India?",
        )

    ordered_ids = [result.doc_id for result in results]
    assert ordered_ids == [
        "doc-maneka-1978",
        "doc-rajagopal-1994",
        "doc-pucl-1996",
        "doc-puttaswamy-2017",
    ]
    assert "doc-gopalan-1950" not in ordered_ids
    assert [result.timeline_phase for result in results] == [
        "foundational",
        "development",
        "current",
        "current",
    ]
    assert [result.document.date for result in results] == sorted(
        result.document.date for result in results
    )
    assert results[-1].is_anchor is True
    engine.dispose()
