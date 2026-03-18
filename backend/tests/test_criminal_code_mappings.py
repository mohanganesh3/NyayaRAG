from __future__ import annotations

from datetime import date as date_value
from pathlib import Path

from alembic import command
from alembic.config import Config
from app.db.base import Base
from app.db.session import build_engine
from app.models import (
    CRIMINAL_CODE_CUTOVER,
    CriminalCode,
    CriminalCodeMapping,
    CriminalCodeMappingStatus,
)
from app.services.criminal_code_mappings import CriminalCodeMappingResolver
from sqlalchemy import inspect
from sqlalchemy.orm import Session


def _make_alembic_config(database_url: str) -> Config:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_criminal_code_mapping_model_imports_are_stable() -> None:
    assert CriminalCodeMapping.__tablename__ == "criminal_code_mappings"


def test_mapping_resolver_handles_pre_and_post_cutover_queries(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'criminal_code_mappings.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    resolver = CriminalCodeMappingResolver()

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
            transition_note="Use BNS 101 for offences committed on or after July 1, 2024.",
            source_reference="NyayaRAG canonical mapping table",
        )
        resolver.upsert_mapping(
            session,
            legacy_code=CriminalCode.CRPC,
            legacy_section="437",
            new_code=CriminalCode.BNSS,
            new_section="480",
            mapping_status=CriminalCodeMappingStatus.DIRECT,
            legacy_title="Bail in non-bailable offence",
            new_title="Bail in non-bailable offence",
            transition_note="BNSS 480 replaces CrPC 437 after the criminal-code cutover.",
            source_reference="NyayaRAG canonical mapping table",
        )
        session.commit()

        pre_cutover = resolver.resolve_reference(
            session,
            "IPC 302",
            reference_date=date_value(2024, 6, 30),
        )
        assert pre_cutover.preferred_reference.code is CriminalCode.IPC
        assert pre_cutover.preferred_reference.section == "302"
        assert pre_cutover.equivalent_reference is not None
        assert pre_cutover.equivalent_reference.code is CriminalCode.BNS
        assert pre_cutover.equivalent_reference.section == "101"
        assert pre_cutover.applies_new_code is False

        post_cutover = resolver.resolve_reference(
            session,
            "IPC 302",
            reference_date=CRIMINAL_CODE_CUTOVER,
        )
        assert post_cutover.preferred_reference.code is CriminalCode.BNS
        assert post_cutover.preferred_reference.section == "101"
        assert post_cutover.equivalent_reference is not None
        assert post_cutover.equivalent_reference.code is CriminalCode.IPC
        assert post_cutover.equivalent_reference.section == "302"
        assert post_cutover.applies_new_code is True

        reverse_pre_cutover = resolver.resolve_reference(
            session,
            "BNSS 480",
            reference_date=date_value(2024, 6, 30),
        )
        assert reverse_pre_cutover.preferred_reference.code is CriminalCode.CRPC
        assert reverse_pre_cutover.preferred_reference.section == "437"

        expanded = resolver.expand_references_for_query(
            session,
            ["IPC 302", "CrPC 437"],
            reference_date=CRIMINAL_CODE_CUTOVER,
        )
        assert expanded == ["BNS 101", "IPC 302", "BNSS 480", "CrPC 437"]

    engine.dispose()


def test_alembic_head_contains_criminal_code_mapping_table(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'criminal_code_head.db'}"
    config = _make_alembic_config(database_url)

    command.upgrade(config, "head")
    engine = build_engine(database_url)
    inspector = inspect(engine)

    assert "criminal_code_mappings" in inspector.get_table_names()
    engine.dispose()
