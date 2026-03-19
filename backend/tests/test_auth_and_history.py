from __future__ import annotations

from app.db.base import Base
from app.db.session import build_engine, get_db
from app.main import app
from app.models import (
    BillingInvoiceStatus,
    BillingPlanCode,
    BillingSubscriptionStatus,
    CaseContext,
    CaseStage,
    CaseType,
)
from app.services.billing import billing_store
from app.services.query_runtime import query_runtime
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker


def _seed_workspace(
    session: Session,
    *,
    owner_auth_user_id: str,
    case_id: str = "case-auth-001",
) -> str:
    context = CaseContext(
        case_id=case_id,
        owner_auth_user_id=owner_auth_user_id,
        owner_display_name="Mohan Ganesh",
        auth_provider="clerk",
        appellant_petitioner="Arjun Rao",
        respondent_opposite_party="State of Karnataka",
        advocates=["Mohan Ganesh"],
        case_type=CaseType.CRIMINAL,
        court="High Court of Karnataka",
        case_number="Criminal Petition No. 4812/2026",
        stage=CaseStage.BAIL,
        charges_sections=["IPC 420", "CrPC 438"],
        bnss_equivalents=["BNS 318", "BNSS 482"],
        statutes_involved=["IPC", "CrPC", "BNS", "BNSS"],
        key_facts=[{"date": "2026-03-18", "label": "FIR registered"}],
        previous_orders=[],
        bail_history=[],
        open_legal_issues=["Whether anticipatory bail should be granted."],
        uploaded_docs=[{"name": "fir.pdf", "document_mode": "typed_pdf"}],
        doc_extraction_confidence=0.92,
    )
    session.add(context)
    session.commit()
    return context.case_id


def test_workspace_list_and_saved_answers_are_scoped_to_authenticated_user(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'workspace_saved_answers.db'}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        first_case_id = _seed_workspace(
            session,
            owner_auth_user_id="clerk-user-1",
            case_id="case-auth-001",
        )
        second_case_id = _seed_workspace(
            session,
            owner_auth_user_id="clerk-user-1",
            case_id="case-auth-002",
        )
        _seed_workspace(
            session,
            owner_auth_user_id="clerk-user-2",
            case_id="case-auth-003",
        )

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        headers = {"X-Clerk-User-Id": "clerk-user-1"}

        list_response = client.get("/api/workspaces", headers=headers)
        create_saved_answer_response = client.post(
            f"/api/workspace/{first_case_id}/saved-answers",
            headers=headers,
            json={
                "query_text": "What are the strongest bail arguments?",
                "overall_status": "VERIFIED",
                "answer": {
                    "overall_status": "VERIFIED",
                    "query": "What are the strongest bail arguments?",
                    "sections": [],
                },
            },
        )
        saved_answers_response = client.get(
            f"/api/workspace/{first_case_id}/saved-answers",
            headers=headers,
        )
        forbidden_saved_answers_response = client.get(
            "/api/workspace/case-auth-003/saved-answers",
            headers=headers,
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert list_response.status_code == 200
    list_body = list_response.json()
    assert {item["case_id"] for item in list_body["data"]} == {
        first_case_id,
        second_case_id,
    }

    assert create_saved_answer_response.status_code == 200
    saved_answer_body = create_saved_answer_response.json()
    assert saved_answer_body["data"]["workspace_id"] == first_case_id
    assert saved_answer_body["data"]["overall_status"] == "VERIFIED"
    assert saved_answer_body["data"]["answer"]["query"] == "What are the strongest bail arguments?"

    assert saved_answers_response.status_code == 200
    saved_answers_body = saved_answers_response.json()
    assert len(saved_answers_body["data"]) == 1
    assert saved_answers_body["data"][0]["workspace_id"] == first_case_id

    assert forbidden_saved_answers_response.status_code == 403
    assert forbidden_saved_answers_response.json()["error"]["code"] == "workspace_forbidden"


def test_workspace_route_requires_auth(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'auth_required.db'}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        case_id = _seed_workspace(session, owner_auth_user_id="clerk-user-1")
        billing_store.upsert_subscription(
            session,
            auth_user_id="clerk-user-1",
            plan_code=BillingPlanCode.ADVOCATE_PRO,
            status=BillingSubscriptionStatus.ACTIVE,
        )
        billing_store.create_invoice(
            session,
            auth_user_id="clerk-user-1",
            amount_minor=79900,
            status=BillingInvoiceStatus.PAID,
            description="Advocate Pro monthly subscription",
        )
        session.commit()

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get(f"/api/workspace/{case_id}")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_required"


def test_auth_session_route_reflects_clerk_bridge_headers() -> None:
    client = TestClient(app)

    response = client.get(
        "/api/auth/session",
        headers={
            "X-Clerk-User-Id": "clerk-user-1",
            "X-Clerk-Session-Id": "sess-123",
            "X-Clerk-Display-Name": "Mohan Ganesh",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["is_authenticated"] is True
    assert body["data"]["provider"] == "clerk"
    assert body["data"]["user_id"] == "clerk-user-1"


def test_workspace_route_forbids_other_authenticated_user(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'auth_forbidden.db'}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        case_id = _seed_workspace(session, owner_auth_user_id="clerk-user-1")

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get(
            f"/api/workspace/{case_id}",
            headers={"X-Clerk-User-Id": "clerk-user-2"},
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "workspace_forbidden"


def test_authenticated_query_history_is_scoped_to_session_and_workspace(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'query_history.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    with Session(engine) as session:
        case_id = _seed_workspace(session, owner_auth_user_id="clerk-user-1")
        billing_store.upsert_subscription(
            session,
            auth_user_id="clerk-user-1",
            plan_code=BillingPlanCode.ADVOCATE_PRO,
            status=BillingSubscriptionStatus.ACTIVE,
        )
        session.commit()

    def override_get_db():
        with Session(engine) as session:
            yield session

    query_runtime.reset()
    query_runtime.set_session_factory_provider(lambda: session_factory)

    def workspace_loader(workspace_id: str) -> CaseContext | None:
        with Session(engine) as session:
            context = session.get(CaseContext, workspace_id)
            if context is None:
                return None
            session.expunge(context)
            return context

    query_runtime.set_workspace_loader(workspace_loader)
    app.dependency_overrides[get_db] = override_get_db

    try:
        client = TestClient(app)
        headers = {"X-Clerk-User-Id": "clerk-user-1", "X-Clerk-Session-Id": "sess-123"}

        general_query = client.post(
            "/api/query",
            json={"query": "What is Section 302 IPC?"},
            headers=headers,
        )
        assert general_query.status_code == 202
        general_stream = general_query.json()["data"]["stream_url"]
        assert client.get(general_stream, headers=headers).status_code == 200

        workspace_query = client.post(
            "/api/query",
            json={"query": "What are my bail arguments?", "workspace_id": case_id},
            headers=headers,
        )
        assert workspace_query.status_code == 202
        workspace_stream = workspace_query.json()["data"]["stream_url"]
        assert client.get(workspace_stream, headers=headers).status_code == 200

        history_response = client.get("/api/query/history", headers=headers)
        workspace_history_response = client.get(
            f"/api/workspace/{case_id}/history",
            headers=headers,
        )
    finally:
        query_runtime.reset()
        app.dependency_overrides.clear()
        engine.dispose()

    assert history_response.status_code == 200
    history_body = history_response.json()
    assert len(history_body["data"]) == 2
    assert history_body["data"][0]["auth_session_id"] == "sess-123"
    assert {entry["status"] for entry in history_body["data"]} == {"completed"}

    assert workspace_history_response.status_code == 200
    workspace_body = workspace_history_response.json()
    assert len(workspace_body["data"]) == 1
    assert workspace_body["data"][0]["workspace_id"] == case_id
    assert workspace_body["data"][0]["pipeline"] == "agentic_rag"


def test_stream_query_requires_same_authenticated_user(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'query_stream_forbidden.db'}")
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
        accepted = client.post(
            "/api/query",
            json={"query": "What is the privacy position?"},
            headers={"X-Clerk-User-Id": "clerk-user-1"},
        )
        stream_url = accepted.json()["data"]["stream_url"].split("?")[0]
        response = client.get(
            stream_url,
            headers={"X-Clerk-User-Id": "clerk-user-2"},
        )
    finally:
        query_runtime.reset()
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "query_forbidden"
