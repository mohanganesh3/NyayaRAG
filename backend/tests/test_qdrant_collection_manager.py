from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.db.session import build_engine
from app.ingestion import QdrantCollectionManager
from app.models import VectorStoreBackend, VectorStoreCollection, VectorStorePoint
from sqlalchemy import select
from sqlalchemy.orm import Session


def _make_alembic_config(database_url: str) -> Config:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _point(
    *,
    point_id: str,
    chunk_id: str,
    doc_id: str,
    collection_name: str,
    payload: dict[str, object],
) -> VectorStorePoint:
    return VectorStorePoint(
        point_id=point_id,
        chunk_id=chunk_id,
        doc_id=doc_id,
        backend=VectorStoreBackend.QDRANT,
        collection_name=collection_name,
        embedding_model="BGE-M3-v1.5",
        embedding_version="test-v1",
        vector_dimension=12,
        vector=[0.1] * 12,
        payload=payload,
        is_active=True,
    )


def test_qdrant_collection_manager_creates_all_default_collections(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'qdrant_collections.db'}"
    command.upgrade(_make_alembic_config(database_url), "head")
    engine = build_engine(database_url)
    manager = QdrantCollectionManager(default_vector_size=12)

    with Session(engine) as session:
        collections = manager.ensure_default_collections(session)
        session.commit()

        persisted = session.execute(select(VectorStoreCollection)).scalars().all()

        assert len(collections) == 7
        assert {collection.name for collection in persisted} == {
            "sc_judgments",
            "hc_judgments",
            "statutes",
            "constitution",
            "tribunal_orders",
            "lc_reports",
            "doctrine_clusters",
        }
        assert all(collection.vector_size == 12 for collection in persisted)


def test_qdrant_collection_filters_support_validity_date_jurisdiction_and_bench_size(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'qdrant_filters_sc.db'}"
    command.upgrade(_make_alembic_config(database_url), "head")
    engine = build_engine(database_url)
    manager = QdrantCollectionManager(default_vector_size=12)

    with Session(engine) as session:
        manager.ensure_default_collections(session)
        session.add_all(
            [
                _point(
                    point_id="point-sc-1",
                    chunk_id="chunk-sc-1",
                    doc_id="doc-sc-1",
                    collection_name="sc_judgments",
                    payload={
                        "current_validity": "GOOD_LAW",
                        "date": "2017-08-24",
                        "jurisdiction_binding": ["All India"],
                        "bench_size": 9,
                        "court": "Supreme Court",
                        "practice_area": ["constitutional"],
                    },
                ),
                _point(
                    point_id="point-sc-2",
                    chunk_id="chunk-sc-2",
                    doc_id="doc-sc-2",
                    collection_name="sc_judgments",
                    payload={
                        "current_validity": "OVERRULED",
                        "date": "1950-01-26",
                        "jurisdiction_binding": ["All India"],
                        "bench_size": 6,
                        "court": "Supreme Court",
                        "practice_area": ["constitutional"],
                    },
                ),
            ]
        )
        session.commit()

        filtered = manager.filter_points(
            session,
            "sc_judgments",
            {
                "must": [
                    {"key": "current_validity", "match": {"value": "GOOD_LAW"}},
                    {
                        "key": "date",
                        "range": {"gte": "2017-01-01", "lte": "2018-01-01"},
                    },
                    {"key": "bench_size", "range": {"gte": 5}},
                ],
                "should": [
                    {"key": "jurisdiction_binding", "match": {"value": "All India"}}
                ],
            },
        )

        assert [point.point_id for point in filtered] == ["point-sc-1"]


def test_qdrant_collection_filters_support_act_section_and_doctrine_fields(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'qdrant_filters_domain.db'}"
    command.upgrade(_make_alembic_config(database_url), "head")
    engine = build_engine(database_url)
    manager = QdrantCollectionManager(default_vector_size=12)

    with Session(engine) as session:
        manager.ensure_default_collections(session)
        session.add_all(
            [
                _point(
                    point_id="point-st-1",
                    chunk_id="chunk-st-1",
                    doc_id="doc-st-1",
                    collection_name="statutes",
                    payload={
                        "current_validity": "GOOD_LAW",
                        "act_name": "Indian Penal Code, 1860",
                        "section_number": "302",
                        "is_in_force": True,
                        "jurisdiction": "Central",
                        "amendment_date": "2024-07-01",
                    },
                ),
                _point(
                    point_id="point-st-2",
                    chunk_id="chunk-st-2",
                    doc_id="doc-st-2",
                    collection_name="statutes",
                    payload={
                        "current_validity": "GOOD_LAW",
                        "act_name": "Indian Penal Code, 1860",
                        "section_number": "420",
                        "is_in_force": True,
                        "jurisdiction": "Central",
                        "amendment_date": "2024-07-01",
                    },
                ),
                _point(
                    point_id="point-doc-1",
                    chunk_id="chunk-doc-1",
                    doc_id="doc-doc-1",
                    collection_name="doctrine_clusters",
                    payload={
                        "doctrine_name": "Right to Privacy",
                        "area_of_law": "constitutional",
                        "current_validity": "GOOD_LAW",
                        "practice_area": ["constitutional"],
                    },
                ),
            ]
        )
        session.commit()

        statute_points = manager.filter_points(
            session,
            "statutes",
            {
                "must": [
                    {
                        "key": "act_name",
                        "match": {"value": "Indian Penal Code, 1860"},
                    },
                    {"key": "section_number", "match": {"value": "302"}},
                ]
            },
        )
        doctrine_points = manager.filter_points(
            session,
            "doctrine_clusters",
            {
                "must": [
                    {"key": "doctrine_name", "match": {"value": "Right to Privacy"}},
                    {"key": "area_of_law", "match": {"value": "constitutional"}},
                ]
            },
        )

        assert [point.point_id for point in statute_points] == ["point-st-1"]
        assert [point.point_id for point in doctrine_points] == ["point-doc-1"]


def test_qdrant_collection_manager_rejects_unindexed_filter_keys(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'qdrant_filters_invalid.db'}"
    command.upgrade(_make_alembic_config(database_url), "head")
    engine = build_engine(database_url)
    manager = QdrantCollectionManager(default_vector_size=12)

    with Session(engine) as session:
        manager.ensure_default_collections(session)
        with pytest.raises(ValueError, match="not indexed"):
            manager.filter_points(
                session,
                "sc_judgments",
                {"must": [{"key": "doctrine_name", "match": {"value": "Privacy"}}]},
            )
