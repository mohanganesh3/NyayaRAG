from __future__ import annotations

from pathlib import Path

from app.db.base import Base
from app.db.session import build_engine
from app.ingestion.collection_program import CollectionProgram
from app.models import LegalDocument, SourceRegistry
from sqlalchemy import select
from sqlalchemy.orm import Session


def _registry_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "collection" / "sources"


def _manifest(name: str) -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "data"
        / "collection"
        / "manifests"
        / name
    )


def test_collection_program_loads_registry_and_stage_manifests() -> None:
    program = CollectionProgram(registry_dir=_registry_dir())

    assert "constitution_of_india" in program.registry
    assert "supreme_court_official" in program.registry
    assert "ecourts_district_history" in program.registry
    assert program.registry["ecourts_district_history"].adapter_key is None

    stage_1 = program.load_manifest(_manifest("stage_1_national_core_sample.toml"))
    stage_2 = program.load_manifest(_manifest("stage_2_representative_fanout_sample.toml"))

    assert stage_1.name == "stage_1_national_core_sample"
    assert len(stage_1.jobs) == 4
    assert stage_2.name == "stage_2_representative_fanout_sample"
    assert len(stage_2.jobs) == 7


def test_collection_program_runs_stage_manifests_through_real_orchestrator(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'collection_program.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    program = CollectionProgram(registry_dir=_registry_dir())

    with Session(engine) as session:
        stage_1_result = program.run_manifest(
            session,
            _manifest("stage_1_national_core_sample.toml"),
        )
        stage_2_result = program.run_manifest(
            session,
            _manifest("stage_2_representative_fanout_sample.toml"),
        )

        assert stage_1_result.manifest_name == "stage_1_national_core_sample"
        assert [item.status for item in stage_1_result.items] == [
            "ingested",
            "ingested",
            "ingested",
            "ingested",
        ]

        assert stage_2_result.manifest_name == "stage_2_representative_fanout_sample"
        assert [item.status for item in stage_2_result.items[:-1]] == [
            "ingested",
            "ingested",
            "ingested",
            "ingested",
            "ingested",
            "ingested",
        ]
        assert stage_2_result.items[-1].status == "skipped"
        assert stage_2_result.items[-1].reason == "blocked_pending_adapter"

        documents = session.execute(select(LegalDocument)).scalars().all()
        registries = session.execute(select(SourceRegistry)).scalars().all()

        assert len(documents) == 10
        assert {registry.source_key for registry in registries} >= {
            "constitution_of_india",
            "india_code",
            "bns_bundle",
            "supreme_court",
            "bombay_high_court",
            "delhi_high_court",
            "madras_high_court",
            "nclt",
            "itat",
            "ngt",
        }
