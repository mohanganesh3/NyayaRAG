from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.base import Base
from app.db.session import build_engine, get_db
from app.main import app
from app.services.evaluations import evaluation_run_store
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_trust_endpoint_returns_latest_public_completed_run(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'trust_dashboard.db'}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        evaluation_run_store.create_run(
            session,
            suite_name="india_legal",
            benchmark_name="Weekly Trust Benchmark",
            benchmark_version="v1",
            status="completed",
            measured_at=datetime.now(UTC) - timedelta(days=2),
            query_count=2000,
            is_public=True,
            metrics={"citation_existence_rate": 1.0},
            notes="older public run",
        )
        evaluation_run_store.create_run(
            session,
            suite_name="india_legal",
            benchmark_name="Weekly Trust Benchmark",
            benchmark_version="v2",
            status="completed",
            measured_at=datetime.now(UTC),
            query_count=2500,
            is_public=False,
            metrics={"citation_existence_rate": 0.8},
            notes="private draft run",
        )
        latest_public = evaluation_run_store.create_run(
            session,
            suite_name="india_legal",
            benchmark_name="Weekly Trust Benchmark",
            benchmark_version="v3",
            status="completed",
            measured_at=datetime.now(UTC) - timedelta(hours=1),
            query_count=3000,
            is_public=True,
            metrics={
                "citation_existence_rate": 1.0,
                "citation_accuracy_rate": 0.99,
            },
            notes="public measured run",
            payload={"benchmark_window": "weekly"},
        )
        latest_public_id = latest_public.id
        session.commit()

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get("/api/trust")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["run_id"] == latest_public_id
    assert body["data"]["benchmark_version"] == "v3"
    assert body["data"]["query_count"] == 3000
    assert body["data"]["metrics"]["citation_existence_rate"] == 1.0
    assert body["data"]["payload"]["benchmark_window"] == "weekly"


def test_trust_endpoint_rejects_when_no_public_measured_run_exists(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'trust_dashboard_empty.db'}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        evaluation_run_store.create_run(
            session,
            suite_name="india_legal",
            benchmark_name="Weekly Trust Benchmark",
            benchmark_version="draft",
            status="running",
            measured_at=datetime.now(UTC),
            query_count=500,
            is_public=False,
            metrics={"citation_existence_rate": 0.0},
        )
        session.commit()

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get("/api/trust")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "trust_metrics_not_found"
