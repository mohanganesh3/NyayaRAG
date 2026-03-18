from app.main import app
from fastapi.testclient import TestClient


def test_healthcheck_reports_ok(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.health.check_database_connection",
        lambda: (True, None),
    )

    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"]["status"] == "ok"


def test_healthcheck_reports_degraded(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.health.check_database_connection",
        lambda: (False, "OperationalError"),
    )

    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"]["status"] == "error"
