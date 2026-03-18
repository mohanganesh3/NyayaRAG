import json

from app.main import app
from app.services.query_runtime import query_runtime
from fastapi.testclient import TestClient


def test_submit_query_returns_stream_contract() -> None:
    query_runtime.reset()
    client = TestClient(app)

    response = client.post("/api/query", json={"query": "Dummy bootstrap query"})

    assert response.status_code == 202
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "accepted"
    assert body["data"]["stream_url"].startswith("/api/query/")


def test_stream_query_emits_expected_sse_events() -> None:
    query_runtime.reset()
    client = TestClient(app)
    accepted = client.post("/api/query", json={"query": "Stream me"}).json()
    stream_url = accepted["data"]["stream_url"]

    response = client.get(stream_url)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    chunks = [chunk for chunk in response.text.strip().split("\n\n") if chunk]
    payloads = [json.loads(chunk.removeprefix("data: ")) for chunk in chunks]

    assert payloads[0]["type"] == "STEP_START"
    assert payloads[1]["type"] == "STEP_COMPLETE"
    assert payloads[2]["type"] == "TOKEN"
    assert payloads[-1]["type"] == "COMPLETE"


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

