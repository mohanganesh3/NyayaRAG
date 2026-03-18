from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from app.db.session import build_engine
from app.ingestion import QdrantCollectionManager
from app.ingestion.embeddings import DeterministicBgeM3EmbeddingService
from app.models import (
    CRIMINAL_CODE_CUTOVER,
    CriminalCode,
    CriminalCodeMappingStatus,
    DocumentChunk,
    LegalDocument,
    LegalDocumentType,
    ValidityStatus,
    VectorStoreBackend,
    VectorStorePoint,
)
from app.rag import HybridRAGPipeline, QueryRouter
from app.services.criminal_code_mappings import CriminalCodeMappingResolver
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
    service = DeterministicBgeM3EmbeddingService(
        embedding_version="test-v1",
        vector_dimension=vector_dimension,
    )
    vector = service.embed_texts([text])[0]
    point_payload = payload or {}
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
        payload=point_payload,
        is_active=True,
    )
    session.add(document)
    session.add(chunk)
    session.add(point)


def test_hybrid_rag_returns_binding_statutory_context_and_prioritizes_supreme_court(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'hybrid_rag_statutory.db'}"
    command.upgrade(_make_alembic_config(database_url), "head")
    engine = build_engine(database_url)
    resolver = CriminalCodeMappingResolver()
    router = QueryRouter(resolver=resolver)
    pipeline = HybridRAGPipeline(router=router)

    with Session(engine) as session:
        QdrantCollectionManager(default_vector_size=12).ensure_default_collections(
            session,
            vector_size=12,
        )
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
        _seed_chunk_with_point(
            session,
            doc_id="doc-bns-101",
            chunk_id="chunk-bns-101",
            doc_type=LegalDocumentType.STATUTE,
            collection_name="statutes",
            text="Whoever commits murder shall be punished with death or imprisonment for life.",
            section_header="Section 101 - Murder",
            act_name="Bharatiya Nyaya Sanhita, 2023",
            section_number="101",
            practice_areas=["criminal"],
            jurisdiction_binding=["All India"],
            payload={
                "current_validity": "GOOD_LAW",
                "act_name": "Bharatiya Nyaya Sanhita, 2023",
                "section_number": "101",
                "is_in_force": True,
                "jurisdiction": "Central",
                "amendment_date": "2024-07-01",
            },
        )
        _seed_chunk_with_point(
            session,
            doc_id="doc-sc-murder",
            chunk_id="chunk-sc-murder",
            doc_type=LegalDocumentType.JUDGMENT,
            collection_name="sc_judgments",
            text=(
                "The Supreme Court held that murder under Section 302 IPC, now BNS 101, "
                "carries death or life imprisonment and must be assessed on mens rea."
            ),
            section_header="Holding",
            court="Supreme Court",
            citation="(2024) 2 SCC 500",
            parties={"appellant": "State of Maharashtra", "respondent": "Arjun Rao"},
            practice_areas=["criminal"],
            jurisdiction_binding=["All India"],
            coram=3,
            bench=["Justice A", "Justice B", "Justice C"],
            payload={
                "current_validity": "GOOD_LAW",
                "date": "2024-02-01",
                "jurisdiction_binding": ["All India"],
                "bench_size": 3,
                "court": "Supreme Court",
                "practice_area": ["criminal"],
            },
        )
        _seed_chunk_with_point(
            session,
            doc_id="doc-hc-murder",
            chunk_id="chunk-hc-murder",
            doc_type=LegalDocumentType.JUDGMENT,
            collection_name="hc_judgments",
            text=(
                "Bombay High Court discussed sentencing factors for murder and the "
                "transition from IPC 302 to BNS 101."
            ),
            section_header="Observation",
            court="Bombay High Court",
            citation="2024 Bom HC 99",
            parties={"appellant": "State of Maharashtra", "respondent": "Ravi Patil"},
            practice_areas=["criminal"],
            jurisdiction_binding=["Bombay High Court"],
            coram=2,
            bench=["Justice X", "Justice Y"],
            payload={
                "current_validity": "GOOD_LAW",
                "date": "2024-03-11",
                "jurisdiction_binding": ["Bombay High Court"],
                "court": "Bombay High Court",
                "state": "Maharashtra",
                "practice_area": ["criminal"],
            },
        )
        _seed_chunk_with_point(
            session,
            doc_id="doc-irrelevant",
            chunk_id="chunk-irrelevant",
            doc_type=LegalDocumentType.STATUTE,
            collection_name="statutes",
            text="Cheating and dishonestly inducing delivery of property.",
            section_header="Section 318 - Cheating",
            act_name="Bharatiya Nyaya Sanhita, 2023",
            section_number="318",
            practice_areas=["criminal"],
            jurisdiction_binding=["All India"],
            payload={
                "current_validity": "GOOD_LAW",
                "act_name": "Bharatiya Nyaya Sanhita, 2023",
                "section_number": "318",
                "is_in_force": True,
                "jurisdiction": "Central",
                "amendment_date": "2024-07-01",
            },
        )
        session.commit()

        analysis = router.analyze(
            "What does Section 302 IPC say and how have courts interpreted it?",
            session=session,
            reference_date=CRIMINAL_CODE_CUTOVER,
        )
        results = pipeline.retrieve(
            session,
            "What does Section 302 IPC say and how have courts interpreted it?",
            analysis=analysis,
        )

    assert results
    assert results[0].doc_id == "doc-bns-101"
    assert results[0].authority_class == "binding"
    returned_ids = [result.doc_id for result in results]
    assert "doc-sc-murder" in returned_ids
    assert "doc-hc-murder" in returned_ids
    assert returned_ids.index("doc-sc-murder") < returned_ids.index("doc-hc-murder")
    engine.dispose()


def test_hybrid_rag_returns_case_specific_supreme_court_binding_context(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'hybrid_rag_case.db'}"
    command.upgrade(_make_alembic_config(database_url), "head")
    engine = build_engine(database_url)
    QdrantCollectionManager(default_vector_size=12)
    pipeline = HybridRAGPipeline()

    with Session(engine) as session:
        QdrantCollectionManager(default_vector_size=12).ensure_default_collections(
            session,
            vector_size=12,
        )
        _seed_chunk_with_point(
            session,
            doc_id="doc-puttaswamy",
            chunk_id="chunk-puttaswamy",
            doc_type=LegalDocumentType.JUDGMENT,
            collection_name="sc_judgments",
            text=(
                "The nine-judge Bench held that privacy is a fundamental right under "
                "Article 21 and Part III of the Constitution."
            ),
            section_header="Holding",
            court="Supreme Court",
            citation="(2017) 10 SCC 1",
            parties={
                "appellant": "Justice K.S. Puttaswamy",
                "respondent": "Union of India",
            },
            practice_areas=["constitutional"],
            jurisdiction_binding=["All India"],
            coram=9,
            bench=[f"Justice {index}" for index in range(1, 10)],
            payload={
                "current_validity": "GOOD_LAW",
                "date": "2017-08-24",
                "jurisdiction_binding": ["All India"],
                "bench_size": 9,
                "court": "Supreme Court",
                "practice_area": ["constitutional"],
            },
        )
        _seed_chunk_with_point(
            session,
            doc_id="doc-hc-privacy",
            chunk_id="chunk-hc-privacy",
            doc_type=LegalDocumentType.JUDGMENT,
            collection_name="hc_judgments",
            text="Delhi High Court discussed informational privacy in service records.",
            section_header="Observation",
            court="Delhi High Court",
            citation="2018 Del HC 22",
            parties={"appellant": "Asha Sharma", "respondent": "Union of India"},
            practice_areas=["constitutional"],
            jurisdiction_binding=["Delhi High Court"],
            coram=2,
            bench=["Justice D", "Justice E"],
            payload={
                "current_validity": "GOOD_LAW",
                "date": "2018-03-14",
                "jurisdiction_binding": ["Delhi High Court"],
                "court": "Delhi High Court",
                "state": "Delhi",
                "practice_area": ["constitutional"],
            },
        )
        session.commit()

        results = pipeline.retrieve(
            session,
            "What was held in Justice K.S. Puttaswamy v Union of India?",
        )

    assert results
    assert results[0].doc_id == "doc-puttaswamy"
    assert results[0].authority_class == "binding"
    assert results[0].authority_tier == 1
    engine.dispose()
