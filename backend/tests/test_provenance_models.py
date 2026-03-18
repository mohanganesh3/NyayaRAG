from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from app.db.base import Base
from app.db.session import build_engine
from app.models import (
    ApprovalStatus,
    IngestionRun,
    IngestionRunStatus,
    LegalDocument,
    LegalDocumentType,
    SourceRegistry,
    SourceType,
    ValidityStatus,
)
from app.schemas import IngestionRunRead, LegalDocumentRead, SourceRegistryRead
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session, selectinload


def _make_alembic_config(database_url: str) -> Config:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_provenance_model_imports_are_stable() -> None:
    assert SourceRegistry.__tablename__ == "source_registries"
    assert IngestionRun.__tablename__ == "ingestion_runs"


def test_legal_document_can_be_traced_to_source_registry_and_ingestion_run(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'provenance.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        source_registry = SourceRegistry(
            source_key="supremecourt.gov.in",
            display_name="Supreme Court of India",
            source_type=SourceType.COURT_PORTAL,
            base_url="https://www.sci.gov.in",
            canonical_hostname="www.sci.gov.in",
            jurisdiction_scope=["All India"],
            update_frequency="daily",
            access_method="scraper",
            is_public=True,
            is_active=True,
            approval_status=ApprovalStatus.APPROVED,
            default_parser_version="sc-judgment-parser-v1",
            notes="Primary source for Supreme Court judgments.",
        )
        ingestion_run = IngestionRun(
            source_registry=source_registry,
            status=IngestionRunStatus.SUCCEEDED,
            parser_version="sc-judgment-parser-v1",
            triggered_by="scheduler",
            document_count=125,
            new_document_count=120,
            updated_document_count=5,
            failed_document_count=0,
            checksum_algorithm="sha256",
            source_snapshot_url="https://www.sci.gov.in/recent-judgments",
            approval_status=ApprovalStatus.APPROVED,
            payload={"window": "2026-03-17"},
        )
        legal_document = LegalDocument(
            doc_id="doc-provenance-000000000000000000000001",
            doc_type=LegalDocumentType.JUDGMENT,
            court="Supreme Court",
            bench=["Justice A", "Justice B"],
            coram=2,
            citation="(2026) 1 SCC 1",
            parties={"appellant": "X", "respondent": "Union of India"},
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
            full_text="Judgment text",
            source_registry=source_registry,
            source_url="https://www.sci.gov.in/judgment/2026-1-scc-1",
            source_document_ref="SCI-2026-0001",
            checksum="sha256:abc123",
            parser_version="sc-judgment-parser-v1",
            ingestion_run=ingestion_run,
            approval_status=ApprovalStatus.APPROVED,
        )

        session.add(legal_document)
        session.commit()
        session.expire_all()

        loaded_document = session.scalar(
            select(LegalDocument)
            .where(LegalDocument.doc_id == "doc-provenance-000000000000000000000001")
            .options(
                selectinload(LegalDocument.source_registry),
                selectinload(LegalDocument.ingestion_run),
            )
        )
        assert loaded_document is not None
        assert loaded_document.source_registry is not None
        assert loaded_document.ingestion_run is not None

        loaded_source = session.get(SourceRegistry, "supremecourt.gov.in")
        assert loaded_source is not None

        loaded_run = session.get(IngestionRun, loaded_document.ingestion_run_id)
        assert loaded_run is not None

        source_read = SourceRegistryRead.model_validate(loaded_source)
        run_read = IngestionRunRead.model_validate(loaded_run)
        document_read = LegalDocumentRead.model_validate(loaded_document)

        assert source_read.display_name == "Supreme Court of India"
        assert run_read.status is IngestionRunStatus.SUCCEEDED
        assert document_read.source_url == "https://www.sci.gov.in/judgment/2026-1-scc-1"
        assert document_read.checksum == "sha256:abc123"
        assert document_read.source_registry is not None
        assert document_read.source_registry.source_key == "supremecourt.gov.in"
        assert document_read.ingestion_run is not None
        assert document_read.ingestion_run.parser_version == "sc-judgment-parser-v1"

    engine.dispose()


def test_alembic_head_contains_provenance_tables_and_legal_document_fks(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'provenance_head.db'}"
    config = _make_alembic_config(database_url)

    command.upgrade(config, "head")
    engine = build_engine(database_url)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    assert "source_registries" in table_names
    assert "ingestion_runs" in table_names

    foreign_tables = {
        foreign_key["referred_table"]
        for foreign_key in inspector.get_foreign_keys("legal_documents")
    }
    assert "source_registries" in foreign_tables
    assert "ingestion_runs" in foreign_tables

    engine.dispose()
