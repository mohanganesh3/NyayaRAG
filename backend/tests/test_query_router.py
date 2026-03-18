from __future__ import annotations

from datetime import date as date_value

from app.db.base import Base
from app.db.session import build_engine
from app.models import (
    CRIMINAL_CODE_CUTOVER,
    CaseContext,
    CaseType,
    CriminalCode,
    CriminalCodeMappingStatus,
)
from app.rag import QueryRouter
from app.schemas import PipelineType, PracticeArea, QueryType
from app.services.criminal_code_mappings import CriminalCodeMappingResolver
from sqlalchemy.orm import Session


def test_query_router_routes_statutory_lookup_with_bns_equivalent(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'query_router_statutory.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    resolver = CriminalCodeMappingResolver()
    router = QueryRouter(resolver=resolver)

    with Session(engine) as session:
        resolver.upsert_mapping(
            session,
            legacy_code=CriminalCode.IPC,
            legacy_section="302",
            new_code=CriminalCode.BNS,
            new_section="101",
            mapping_status=CriminalCodeMappingStatus.DIRECT,
            legacy_title="Murder",
            new_title="Murder",
        )
        session.commit()

        analysis = router.analyze(
            "What is the punishment under Section 302 IPC?",
            session=session,
            reference_date=CRIMINAL_CODE_CUTOVER,
        )

    assert analysis.query_type is QueryType.STATUTORY_LOOKUP
    assert analysis.selected_pipeline is PipelineType.HYBRID_CRAG
    assert "IPC 302" in analysis.sections_mentioned
    assert "BNS 101" in analysis.bnss_equivalents
    assert analysis.post_july_2024 is True
    assert analysis.practice_area is PracticeArea.CRIMINAL
    engine.dispose()


def test_query_router_recognizes_code_first_criminal_section_references() -> None:
    router = QueryRouter()

    analysis = router.analyze("What does BNS 101 say and how have courts interpreted it?")

    assert analysis.query_type is QueryType.STATUTORY_LOOKUP
    assert analysis.selected_pipeline is PipelineType.HYBRID_CRAG
    assert "BNS 101" in analysis.sections_mentioned
    assert analysis.practice_area is PracticeArea.CRIMINAL


def test_query_router_routes_case_specific_queries() -> None:
    router = QueryRouter()

    analysis = router.analyze("What was held in Maneka Gandhi v Union of India?")

    assert analysis.query_type is QueryType.CASE_SPECIFIC
    assert analysis.selected_pipeline is PipelineType.HYBRID_CRAG
    assert any(entity.text == "Maneka Gandhi v Union of India" for entity in analysis.entities)


def test_query_router_routes_constitutional_queries_to_graph_rag() -> None:
    router = QueryRouter()

    analysis = router.analyze("Is Section 66A IT Act constitutionally valid?")

    assert analysis.query_type is QueryType.CONSTITUTIONAL
    assert analysis.selected_pipeline is PipelineType.GRAPH_RAG
    assert analysis.practice_area is PracticeArea.CONSTITUTIONAL
    assert "IT Act 66A" in analysis.sections_mentioned


def test_query_router_routes_vague_landlord_fact_pattern_to_hyde() -> None:
    router = QueryRouter()

    analysis = router.analyze("My landlord changed the locks without notice, what can I do?")

    assert analysis.query_type is QueryType.VAGUE_NATURAL
    assert analysis.selected_pipeline is PipelineType.HYDE_HYBRID
    assert analysis.is_vague is True
    assert analysis.practice_area is PracticeArea.PROPERTY


def test_query_router_routes_comparative_queries_with_multiple_courts() -> None:
    router = QueryRouter()

    analysis = router.analyze(
        "How does Bombay High Court vs Delhi High Court treat anticipatory bail?"
    )

    assert analysis.query_type is QueryType.COMPARATIVE
    assert analysis.selected_pipeline is PipelineType.GRAPH_HYBRID
    assert analysis.requires_comparison is True
    assert analysis.practice_area is PracticeArea.CRIMINAL


def test_query_router_uses_case_context_for_uploaded_doc_routing() -> None:
    router = QueryRouter()
    case_context = CaseContext(
        case_id="case-001",
        court="Bombay High Court",
        case_type=CaseType.CRIMINAL,
        uploaded_docs=[{"name": "fir.pdf", "doc_type": "fir"}],
    )

    analysis = router.analyze("What are my bail arguments?", case_context=case_context)

    assert analysis.query_type is QueryType.DOCUMENT_SPECIFIC
    assert analysis.selected_pipeline is PipelineType.AGENTIC_RAG
    assert analysis.has_uploaded_docs is True
    assert analysis.jurisdiction_court == "Bombay High Court"
    assert analysis.jurisdiction_state == "Maharashtra"
    assert analysis.practice_area is PracticeArea.CRIMINAL


def test_query_router_routes_multi_hop_doctrine_queries() -> None:
    router = QueryRouter()

    analysis = router.analyze("How has the right to privacy developed in India?")

    assert analysis.query_type is QueryType.MULTI_HOP_DOCTRINE
    assert analysis.selected_pipeline is PipelineType.GRAPH_RAG
    assert analysis.requires_multi_hop is True
    assert analysis.practice_area is PracticeArea.CONSTITUTIONAL


def test_query_router_falls_back_to_case_context_jurisdiction_when_query_is_silent() -> None:
    router = QueryRouter()
    case_context = CaseContext(
        case_id="case-002",
        court="Delhi High Court",
        case_type=CaseType.CIVIL,
    )

    analysis = router.analyze(
        "What is the limitation position here?",
        case_context=case_context,
        reference_date=date_value(2026, 3, 17),
    )

    assert analysis.jurisdiction_court == "Delhi High Court"
    assert analysis.jurisdiction_state == "Delhi"
    assert analysis.query_type is QueryType.GENERAL_LEGAL
    assert analysis.selected_pipeline is PipelineType.HYBRID_RAG
