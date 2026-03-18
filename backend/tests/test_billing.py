from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.base import Base
from app.db.session import build_engine, get_db
from app.main import app
from app.models import (
    BillingInvoiceStatus,
    BillingPlanCode,
    BillingSubscriptionStatus,
    QueryHistoryEntry,
)
from app.services.billing import billing_store
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_billing_plans_endpoint_returns_catalog() -> None:
    client = TestClient(app)

    response = client.get("/api/billing/plans")

    assert response.status_code == 200
    body = response.json()
    assert [plan["code"] for plan in body["data"]] == [
        "free",
        "advocate_pro",
        "chamber_pro",
    ]
    assert body["data"][0]["daily_query_limit"] == 20


def test_billing_subscription_defaults_to_free_snapshot(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'billing_free.db'}")
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get(
            "/api/billing/subscription",
            headers={"X-Clerk-User-Id": "clerk-free-1"},
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["plan_code"] == "free"
    assert body["data"]["queries_remaining_today"] == 20
    assert body["data"]["workspace_access"] is False


def test_billing_checkout_creates_pending_razorpay_subscription(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'billing_checkout.db'}")
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/billing/checkout",
            json={"plan_code": "advocate_pro"},
            headers={"X-Clerk-User-Id": "clerk-paid-1"},
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["provider"] == "razorpay"
    assert body["data"]["plan_code"] == "advocate_pro"
    assert "checkout.razorpay.com" in body["data"]["checkout_url"]
    assert body["data"]["provider_subscription_id"].startswith("rzp_sub_preview_")


def test_free_plan_blocks_workspace_queries(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'billing_workspace_block.db'}")
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/query",
            json={"query": "What are my bail arguments?", "workspace_id": "case-auth-001"},
            headers={"X-Clerk-User-Id": "clerk-free-1"},
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "plan_upgrade_required"


def test_free_plan_daily_limit_is_enforced_for_authenticated_user(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'billing_limit.db'}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        for index in range(20):
            session.add(
                QueryHistoryEntry(
                    query_id=f"query-{index}",
                    auth_user_id="clerk-free-2",
                    auth_session_id="sess-20",
                    auth_provider="clerk",
                    query_text=f"query {index}",
                    status="completed",
                    created_at=start + timedelta(minutes=index),
                    updated_at=start + timedelta(minutes=index),
                )
            )
        session.commit()

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/query",
            json={"query": "One more free query please"},
            headers={"X-Clerk-User-Id": "clerk-free-2"},
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 429
    body = response.json()
    assert body["error"]["code"] == "free_tier_limit_reached"
    assert body["error"]["detail"]["daily_query_limit"] == 20


def test_billing_history_returns_paid_invoices(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'billing_history.db'}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        subscription = billing_store.upsert_subscription(
            session,
            auth_user_id="clerk-paid-2",
            plan_code=BillingPlanCode.ADVOCATE_PRO,
            status=BillingSubscriptionStatus.ACTIVE,
        )
        subscription_id = subscription.id
        billing_store.create_invoice(
            session,
            auth_user_id="clerk-paid-2",
            amount_minor=79900,
            status=BillingInvoiceStatus.PAID,
            description="Advocate Pro monthly subscription",
            subscription_id=subscription_id,
        )
        session.commit()

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get(
            "/api/billing/history",
            headers={"X-Clerk-User-Id": "clerk-paid-2"},
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["subscription_id"] == subscription_id
