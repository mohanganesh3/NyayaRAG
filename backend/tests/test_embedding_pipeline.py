from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from app.db.session import build_engine
from app.ingestion import EmbeddingPipeline, EmbeddingUpgradePlanner, IngestionOrchestrator
from app.ingestion.adapters import SupremeCourtHtmlAdapter
from app.ingestion.contracts import IngestionJobContext
from app.ingestion.embeddings import DeterministicBgeM3EmbeddingService
from app.models import DocumentChunk, VectorStorePoint
from sqlalchemy import select
from sqlalchemy.orm import Session

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


def _make_alembic_config(database_url: str) -> Config:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_deterministic_bge_m3_embedding_service_is_stable() -> None:
    service = DeterministicBgeM3EmbeddingService(
        embedding_version="test-v1",
        vector_dimension=12,
    )

    first = service.embed_texts(["privacy is a fundamental right"])[0]
    second = service.embed_texts(["privacy is a fundamental right"])[0]

    assert first == second
    assert len(first) == 12


def test_embedding_pipeline_persists_vector_points_for_ingested_document(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'embedding_pipeline.db'}"
    command.upgrade(_make_alembic_config(database_url), "head")
    engine = build_engine(database_url)

    embedding_service = DeterministicBgeM3EmbeddingService(
        embedding_version="test-v1",
        vector_dimension=12,
    )
    orchestrator = IngestionOrchestrator(
        embedding_pipeline=EmbeddingPipeline(service=embedding_service)
    )
    adapter = SupremeCourtHtmlAdapter()
    context = IngestionJobContext(
        source_key="supreme_court",
        source_url="https://www.sci.gov.in/judgment/puttaswamy",
        parser_version="supreme-court-html-v1",
        external_id="puttaswamy-2017",
        inline_payload=SUPREME_COURT_SAMPLE_HTML,
    )

    with Session(engine) as session:
        persisted = orchestrator.ingest(session, adapter, context)

        chunks = session.execute(
            select(DocumentChunk).where(DocumentChunk.doc_id == persisted.doc_id)
        ).scalars().all()
        points = session.execute(
            select(VectorStorePoint).where(VectorStorePoint.doc_id == persisted.doc_id)
        ).scalars().all()

        assert len(points) == len(chunks)
        assert {point.collection_name for point in points} == {"sc_judgments"}
        assert {point.embedding_version for point in points} == {"test-v1"}
        assert all(chunk.embedding_id is not None for chunk in chunks)
        assert all(chunk.embedding_version == "test-v1" for chunk in chunks)
        assert all(chunk.vector_collection == "sc_judgments" for chunk in chunks)
        assert points[0].payload["doc_type"] == "judgment"
        assert points[0].payload["jurisdiction_binding"] == ["All India"]


def test_embedding_upgrade_planner_flags_chunks_for_model_version_change(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'embedding_upgrade.db'}"
    command.upgrade(_make_alembic_config(database_url), "head")
    engine = build_engine(database_url)

    embedding_service = DeterministicBgeM3EmbeddingService(
        embedding_version="test-v1",
        vector_dimension=12,
    )
    orchestrator = IngestionOrchestrator(
        embedding_pipeline=EmbeddingPipeline(service=embedding_service)
    )
    planner = EmbeddingUpgradePlanner()
    adapter = SupremeCourtHtmlAdapter()
    context = IngestionJobContext(
        source_key="supreme_court",
        source_url="https://www.sci.gov.in/judgment/puttaswamy",
        parser_version="supreme-court-html-v1",
        external_id="puttaswamy-2017",
        inline_payload=SUPREME_COURT_SAMPLE_HTML,
    )

    with Session(engine) as session:
        persisted = orchestrator.ingest(session, adapter, context)
        plan = planner.flag_for_reembedding(
            session,
            target_model="BGE-M3-v1.5",
            target_version="test-v2",
        )
        session.commit()

        chunks = session.execute(
            select(DocumentChunk).where(DocumentChunk.doc_id == persisted.doc_id)
        ).scalars().all()

        assert len(plan.chunk_ids) == len(chunks)
        assert all(chunk.needs_reembedding is True for chunk in chunks)
        assert all(chunk.projection_stale is True for chunk in chunks)
        assert all(chunk.stale_reason is not None for chunk in chunks)
