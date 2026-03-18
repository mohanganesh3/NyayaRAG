import json

from app.db.base import Base
from app.db.session import build_engine, get_db
from app.main import app
from app.models import BillingPlanCode, BillingSubscriptionStatus, CaseContext, CaseStage, CaseType
from app.rag import CitationBadgeStatus, StructuredAnswerSectionKind
from app.services.agentic_workflow import LangGraphAgenticWorkflow
from app.services.billing import billing_store
from app.services.query_runtime import query_runtime
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker


def _build_case_context() -> CaseContext:
    return CaseContext(
        case_id="case-agentic-001",
        owner_auth_user_id="clerk-user-1",
        owner_display_name="Mohan Ganesh",
        auth_provider="clerk",
        appellant_petitioner="Arjun Rao",
        respondent_opposite_party="State of Maharashtra",
        advocates=["Meera Rao"],
        case_type=CaseType.CRIMINAL,
        court="Bombay High Court",
        case_number="BA/1234/2026",
        stage=CaseStage.BAIL,
        charges_sections=["IPC 302", "CrPC 437"],
        bnss_equivalents=["BNS 101", "BNSS 480"],
        statutes_involved=["IPC", "CrPC", "BNS", "BNSS"],
        key_facts=[{"date": "2026-03-17", "fact": "FIR registered"}],
        previous_orders=[
            {
                "court": "Sessions Court",
                "outcome": "rejected",
                "date": "2026-03-20",
                "summary": "Sessions Court rejected bail.",
            }
        ],
        bail_history=[{"date": "2026-03-20", "status": "rejected"}],
        open_legal_issues=[
            "Whether bail should be granted despite the seriousness of the offence."
        ],
        uploaded_docs=[
            {"name": "fir-scan.pdf", "document_mode": "scanned_pdf"},
            {"name": "bail-application.docx", "document_mode": "docx_text"},
        ],
        doc_extraction_confidence=0.91,
    )


def test_langgraph_agentic_workflow_runs_with_sqlite_checkpointer(tmp_path) -> None:
    workflow = LangGraphAgenticWorkflow(sqlite_path=tmp_path / "agentic.sqlite")
    try:
        result = workflow.run(
            user_query="What are my bail arguments?",
            case_context=_build_case_context(),
            thread_id="thread-agentic-1",
        )
    finally:
        workflow.close()

    agent_names = [entry.agent for entry in result.agent_logs]

    assert workflow.checkpointer_name == "SqliteSaver"
    assert result.research_plan
    assert result.verification_result["verified_claim_ratio"] == 0.96
    assert "Legal Position:" in result.synthesis
    assert result.structured_answer.query == "What are my bail arguments?"
    assert result.structured_answer.overall_status is CitationBadgeStatus.UNCERTAIN
    assert (
        result.structured_answer.section(StructuredAnswerSectionKind.LEGAL_POSITION).claims
    )
    assert (
        result.structured_answer.section(StructuredAnswerSectionKind.APPLICABLE_LAW).claims
    )
    assert result.structured_answer.section(
        StructuredAnswerSectionKind.VERIFICATION_STATUS
    ).status_items
    assert agent_names == [
        "DocumentUnderstandingAgent",
        "ResearchPlannerAgent",
        "StatutoryResearchAgent",
        "PrecedentResearchAgent",
        "ContradictionCheckerAgent",
        "SynthesisAgent",
        "VerificationAgent",
    ]


def test_workspace_query_stream_uses_agentic_path_and_emits_agent_logs(tmp_path) -> None:
    query_runtime.reset()
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'agentic_query_stream.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    with Session(engine) as session:
        session.add(_build_case_context())
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

    query_runtime.set_workspace_loader(lambda _: _build_case_context())
    query_runtime.set_session_factory_provider(lambda: session_factory)
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        accepted = client.post(
            "/api/query",
            json={"query": "What are my bail arguments?", "workspace_id": "case-agentic-001"},
            headers={"X-Clerk-User-Id": "clerk-user-1"},
        )
        assert accepted.status_code == 202

        stream_url = accepted.json()["data"]["stream_url"]
        response = client.get(
            stream_url,
            headers={"X-Clerk-User-Id": "clerk-user-1"},
        )
    finally:
        query_runtime.reset()
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    payloads = [
        json.loads(chunk.removeprefix("data: "))
        for chunk in response.text.strip().split("\n\n")
        if chunk
    ]

    event_types = [payload["type"] for payload in payloads]
    agent_names = [payload["agent"] for payload in payloads if payload["type"] == "AGENT_LOG"]

    assert "AGENT_LOG" in event_types
    assert "ANSWER_READY" in event_types
    assert payloads[1]["data"]["pipeline"] == "agentic_rag"
    assert agent_names == [
        "DocumentUnderstandingAgent",
        "ResearchPlannerAgent",
        "StatutoryResearchAgent",
        "PrecedentResearchAgent",
        "ContradictionCheckerAgent",
        "SynthesisAgent",
        "VerificationAgent",
    ]
    assert payloads[-1]["type"] == "COMPLETE"
    assert payloads[-1]["metrics"]["pipeline"] == "agentic_rag"
    assert payloads[-1]["metrics"]["structured_answer_ready"] is True
    answer_ready_event = next(
        payload for payload in payloads if payload["type"] == "ANSWER_READY"
    )
    assert answer_ready_event["answer"]["overall_status"] == "UNCERTAIN"
    assert answer_ready_event["answer"]["sections"][0]["kind"] == "LEGAL_POSITION"
