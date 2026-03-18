import json

from app.db.base import Base
from app.db.session import build_engine, get_db
from app.main import app
from app.services.query_runtime import query_runtime
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker


def test_submit_query_returns_stream_contract(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'query_contract_accept.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def override_get_db():
        with Session(engine) as session:
            yield session

    query_runtime.reset()
    query_runtime.set_session_factory_provider(lambda: session_factory)
    app.dependency_overrides[get_db] = override_get_db

    try:
        client = TestClient(app)
        response = client.post("/api/query", json={"query": "Dummy bootstrap query"})
    finally:
        query_runtime.reset()
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 202
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "accepted"
    assert body["data"]["stream_url"].startswith("/api/query/")


def test_stream_query_emits_expected_sse_events(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'query_contract_stream.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def override_get_db():
        with Session(engine) as session:
            yield session

    query_runtime.reset()
    query_runtime.set_session_factory_provider(lambda: session_factory)
    app.dependency_overrides[get_db] = override_get_db

    try:
        client = TestClient(app)
        accepted = client.post("/api/query", json={"query": "Stream me"}).json()
        stream_url = accepted["data"]["stream_url"]
        response = client.get(stream_url)
    finally:
        query_runtime.reset()
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    chunks = [chunk for chunk in response.text.strip().split("\n\n") if chunk]
    payloads = [json.loads(chunk.removeprefix("data: ")) for chunk in chunks]

    assert payloads[0]["type"] == "STEP_START"
    assert any(payload["type"] == "TOKEN" for payload in payloads)
    assert payloads[-1]["type"] == "COMPLETE"
    assert payloads[-1]["metrics"]["mode"] == "verified_query_execution"


def test_missing_stream_returns_standardized_error() -> None:
    query_runtime.reset()
    client = TestClient(app)

    response = client.get("/api/query/missing-query/stream")

    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "query_not_found"


def test_invalid_query_payload_returns_validation_envelope() -> None:
    query_runtime.reset()
    client = TestClient(app)

    response = client.post("/api/query", json={"query": ""})

    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "validation_error"
