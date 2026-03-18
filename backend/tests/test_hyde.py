from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from app.db.session import build_engine
from app.ingestion import QdrantCollectionManager
from app.ingestion.embeddings import DeterministicBgeM3EmbeddingService
from app.models import (
    DocumentChunk,
    LegalDocument,
    LegalDocumentType,
    ValidityStatus,
    VectorStoreBackend,
    VectorStorePoint,
)
from app.rag import HyDEPipeline, QueryRouter
from app.schemas import QueryType
from sqlalchemy.orm import Session


def _make_alembic_config(database_url: str) -> Config:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _seed_chunk_with_point(
    session: Session,
    *,
    doc_id: str,
    chunk_id: str,
    doc_type: LegalDocumentType,
    collection_name: str,
    text: str,
    section_header: str | None = None,
    act_name: str | None = None,
    section_number: str | None = None,
    court: str | None = None,
    citation: str | None = None,
    parties: dict[str, str] | None = None,
    practice_areas: list[str] | None = None,
    jurisdiction_binding: list[str] | None = None,
    coram: int | None = None,
    bench: list[str] | None = None,
    payload: dict[str, object] | None = None,
    vector_dimension: int = 12,
) -> None:
    practice_area_values = practice_areas or []
    binding = jurisdiction_binding or []
    document = LegalDocument(
        doc_id=doc_id,
        doc_type=doc_type,
        court=court,
        coram=coram,
        bench=bench or [],
        citation=citation,
        parties=parties or {},
        jurisdiction_binding=binding,
        jurisdiction_persuasive=[],
        current_validity=ValidityStatus.GOOD_LAW,
        practice_areas=practice_area_values,
        language="en",
        full_text=text,
        parser_version="test-v1",
    )
    chunk = DocumentChunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        doc_type=doc_type,
        text=text,
        text_normalized=text.lower(),
        chunk_index=0,
        total_chunks=1,
        section_header=section_header,
        court=court,
        citation=citation,
        jurisdiction_binding=binding,
        jurisdiction_persuasive=[],
        current_validity=ValidityStatus.GOOD_LAW,
        practice_area=practice_area_values,
        act_name=act_name,
        section_number=section_number,
        is_in_force=doc_type is LegalDocumentType.STATUTE,
        embedding_id=chunk_id,
        embedding_model="BGE-M3-v1.5",
        embedding_version="test-v1",
        vector_collection=collection_name,
    )
    vector = DeterministicBgeM3EmbeddingService(
        embedding_version="test-v1",
        vector_dimension=vector_dimension,
    ).embed_texts([text])[0]
    point = VectorStorePoint(
        point_id=chunk_id,
        chunk_id=chunk_id,
        doc_id=doc_id,
        backend=VectorStoreBackend.QDRANT,
        collection_name=collection_name,
        embedding_model="BGE-M3-v1.5",
        embedding_version="test-v1",
        vector_dimension=vector_dimension,
        vector=vector,
        payload=payload or {},
        is_active=True,
    )
    session.add(document)
    session.add(chunk)
    session.add(point)


def test_hyde_improves_vague_landlord_query_over_hybrid_baseline(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'hyde_landlord.db'}"
    command.upgrade(_make_alembic_config(database_url), "head")
    engine = build_engine(database_url)
    router = QueryRouter()
    pipeline = HyDEPipeline(router=router)

    with Session(engine) as session:
        QdrantCollectionManager(default_vector_size=12).ensure_default_collections(
            session,
            vector_size=12,
        )
        _seed_chunk_with_point(
            session,
            doc_id="doc-tpa-notice",
            chunk_id="chunk-tpa-notice",
            doc_type=LegalDocumentType.JUDGMENT,
            collection_name="sc_judgments",
            text=(
                "A landlord who seeks eviction of a monthly tenant must ordinarily "
                "serve a valid notice terminating the tenancy before filing eviction proceedings."
            ),
            section_header="Notice requirement",
            court="Supreme Court",
            citation="(2014) 1 SCC 100",
            practice_areas=["property"],
            jurisdiction_binding=["All India"],
            coram=2,
            bench=["Justice A", "Justice B"],
            payload={
                "current_validity": "GOOD_LAW",
                "date": "2014-01-20",
                "jurisdiction_binding": ["All India"],
                "bench_size": 2,
                "court": "Supreme Court",
                "practice_area": ["property"],
            },
        )
        _seed_chunk_with_point(
            session,
            doc_id="doc-sra-6",
            chunk_id="chunk-sra-6",
            doc_type=LegalDocumentType.STATUTE,
            collection_name="statutes",
            text=(
                "If any person is dispossessed of immovable property otherwise than in due "
                "course of law, that person may recover possession by suit under Section 6 "
                "of the Specific Relief Act, 1963."
            ),
            section_header="Section 6 - Recovery of possession",
            act_name="Specific Relief Act, 1963",
            section_number="6",
            practice_areas=["property"],
            jurisdiction_binding=["All India"],
            payload={
                "current_validity": "GOOD_LAW",
                "act_name": "Specific Relief Act, 1963",
                "section_number": "6",
                "is_in_force": True,
                "jurisdiction": "Central",
            },
        )
        _seed_chunk_with_point(
            session,
            doc_id="doc-sc-dispossession",
            chunk_id="chunk-sc-dispossession",
            doc_type=LegalDocumentType.JUDGMENT,
            collection_name="sc_judgments",
            text=(
                "The Court held that self-help eviction and illegal dispossession require "
                "restoration of possession and injunctive relief under Section 6 of the "
                "Specific Relief Act."
            ),
            section_header="Illegal dispossession",
            court="Supreme Court",
            citation="(2018) 4 SCC 250",
            practice_areas=["property"],
            jurisdiction_binding=["All India"],
            coram=3,
            bench=["Justice X", "Justice Y", "Justice Z"],
            payload={
                "current_validity": "GOOD_LAW",
                "date": "2018-04-18",
                "jurisdiction_binding": ["All India"],
                "bench_size": 3,
                "court": "Supreme Court",
                "practice_area": ["property"],
            },
        )
        session.commit()

        query = "My landlord changed the locks without notice, what can I do?"
        analysis = router.analyze(query, session=session)
        baseline_results = pipeline.baseline_retrieve(session, query, analysis=analysis)
        hyde_result = pipeline.retrieve(session, query, analysis=analysis)

    relevant_ids = {"doc-sra-6", "doc-sc-dispossession"}
    baseline_score = sum(
        1 for result in baseline_results[:2] if result.doc_id in relevant_ids
    )
    hyde_score = sum(
        1 for result in hyde_result.crag_result.results[:2] if result.doc_id in relevant_ids
    )

    assert analysis.query_type is QueryType.VAGUE_NATURAL
    assert hyde_result.used_hypothetical is True
    assert hyde_result.hypothetical is not None
    assert hyde_result.hypothetical.strategy == "property_dispossession"
    assert hyde_score > baseline_score
    assert hyde_result.crag_result.results
    assert hyde_result.crag_result.results[0].doc_id in relevant_ids
    engine.dispose()


def test_hyde_falls_back_to_hybrid_when_hypothetical_confidence_is_low(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'hyde_fallback.db'}"
    command.upgrade(_make_alembic_config(database_url), "head")
    engine = build_engine(database_url)
    router = QueryRouter()
    pipeline = HyDEPipeline(router=router)

    with Session(engine) as session:
        QdrantCollectionManager(default_vector_size=12).ensure_default_collections(
            session,
            vector_size=12,
        )
        _seed_chunk_with_point(
            session,
            doc_id="doc-generic-procedure",
            chunk_id="chunk-generic-procedure",
            doc_type=LegalDocumentType.JUDGMENT,
            collection_name="sc_judgments",
            text=(
                "Courts require pleadings, primary evidence, and procedural compliance "
                "before granting interlocutory relief."
            ),
            section_header="Procedure",
            court="Supreme Court",
            citation="(2019) 2 SCC 10",
            practice_areas=["civil"],
            jurisdiction_binding=["All India"],
            coram=2,
            bench=["Justice A", "Justice B"],
            payload={
                "current_validity": "GOOD_LAW",
                "date": "2019-02-10",
                "jurisdiction_binding": ["All India"],
                "bench_size": 2,
                "court": "Supreme Court",
                "practice_area": ["civil"],
            },
        )
        session.commit()

        query = "Need help with some issue, what law applies?"
        analysis = router.analyze(query, session=session)
        baseline_ids = [
            result.doc_id
            for result in pipeline.baseline_retrieve(
                session,
                query,
                analysis=analysis,
            )
        ]
        hyde_result = pipeline.retrieve(session, query, analysis=analysis)
        fallback_ids = [result.doc_id for result in hyde_result.crag_result.results]

    assert hyde_result.used_hypothetical is False
    assert hyde_result.hypothetical is not None
    assert hyde_result.hypothetical.quality_score < pipeline.minimum_quality_score
    assert hyde_result.fallback_reason == "HyDE fallback - low hypothetical confidence"
    assert fallback_ids == baseline_ids
    engine.dispose()
