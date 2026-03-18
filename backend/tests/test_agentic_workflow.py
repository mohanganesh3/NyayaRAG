import json

from app.main import app
from app.models import CaseContext, CaseStage, CaseType
from app.services.agentic_workflow import LangGraphAgenticWorkflow
from app.services.query_runtime import query_runtime
from fastapi.testclient import TestClient


def _build_case_context() -> CaseContext:
    return CaseContext(
        case_id="case-agentic-001",
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
    assert agent_names == [
        "DocumentUnderstandingAgent",
        "ResearchPlannerAgent",
        "StatutoryResearchAgent",
        "PrecedentResearchAgent",
        "ContradictionCheckerAgent",
        "SynthesisAgent",
        "VerificationAgent",
    ]


def test_workspace_query_stream_uses_agentic_path_and_emits_agent_logs() -> None:
    query_runtime.reset()
    query_runtime.set_workspace_loader(lambda _: _build_case_context())
    client = TestClient(app)

    try:
        accepted = client.post(
            "/api/query",
            json={"query": "What are my bail arguments?", "workspace_id": "case-agentic-001"},
        )
        assert accepted.status_code == 202

        stream_url = accepted.json()["data"]["stream_url"]
        response = client.get(stream_url)
    finally:
        query_runtime.reset()

    assert response.status_code == 200
    payloads = [
        json.loads(chunk.removeprefix("data: "))
        for chunk in response.text.strip().split("\n\n")
        if chunk
    ]

    event_types = [payload["type"] for payload in payloads]
    agent_names = [payload["agent"] for payload in payloads if payload["type"] == "AGENT_LOG"]

    assert "AGENT_LOG" in event_types
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
