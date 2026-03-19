import json

from app.db.base import Base
from app.db.session import build_engine, get_db
from app.main import app
from app.models import (
    BillingPlanCode,
    BillingSubscriptionStatus,
    CaseContext,
    CaseStage,
    CaseType,
    DocumentChunk,
    LegalDocument,
    LegalDocumentType,
    ValidityStatus,
)
from app.rag import CitationBadgeStatus, StructuredAnswerSectionKind
from app.services.agentic_workflow import LangGraphAgenticWorkflow
from app.services.billing import billing_store
from app.services.model_runtime import JSONTaskModelClient
from app.services.query_runtime import query_runtime
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker


class FakePlanningModelClient(JSONTaskModelClient):
    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1400,
    ) -> dict[str, object]:
        assert "Charges:" in user_prompt
        return {
            "strategy": "model-backed uploaded-document research",
            "questions": [
                {
                    "question": "Which statutory bail framework applies after the code cutover?",
                    "focus": "statutory",
                    "priority": 1,
                },
                {
                    "question": "Which binding precedents best protect liberty on these facts?",
                    "focus": "precedent",
                    "priority": 2,
                },
            ],
        }


class FakeSynthesisModelClient(JSONTaskModelClient):
    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1400,
    ) -> dict[str, object]:
        assert "Statutory findings:" in user_prompt
        return {
            "synthesis": (
                "Legal Position: The uploaded bail record supports a liberty-first submission. "
                "Statutory Findings: Post-cutover sections must be addressed directly. "
                "Precedent Findings: Binding Supreme Court authorities should lead the note. "
                "Counterpoints: The earlier rejection order must be distinguished. "
                "Open Issues: The necessity of custody remains disputed."
            )
        }


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


def _seed_agentic_corpus(session: Session) -> None:
    murder_text = (
        "Whoever commits murder shall be punished with death or imprisonment for life."
    )
    anticipatory_bail_text = (
        "When any person accused of a non-bailable offence apprehends arrest, "
        "the High Court or Court of Session may grant anticipatory bail."
    )
    session.add(
        LegalDocument(
            doc_id="doc-bns-101",
            doc_type=LegalDocumentType.STATUTE,
            court="Parliament of India",
            current_validity=ValidityStatus.GOOD_LAW,
            practice_areas=["criminal"],
            jurisdiction_binding=["All India"],
            jurisdiction_persuasive=[],
            language="en",
            full_text=murder_text,
            parser_version="seed-v1",
        )
    )
    session.add(
        DocumentChunk(
            chunk_id="chunk-bns-101",
            doc_id="doc-bns-101",
            doc_type=LegalDocumentType.STATUTE,
            text=murder_text,
            text_normalized=murder_text.lower(),
            chunk_index=0,
            total_chunks=1,
            section_header="Section 101 - Murder",
            act_name="Bharatiya Nyaya Sanhita, 2023",
            section_number="101",
            court="Parliament of India",
            jurisdiction_binding=["All India"],
            jurisdiction_persuasive=[],
            current_validity=ValidityStatus.GOOD_LAW,
            practice_area=["criminal"],
            is_in_force=True,
        )
    )
    session.add(
        LegalDocument(
            doc_id="doc-bnss-480",
            doc_type=LegalDocumentType.STATUTE,
            court="Parliament of India",
            current_validity=ValidityStatus.GOOD_LAW,
            practice_areas=["criminal"],
            jurisdiction_binding=["All India"],
            jurisdiction_persuasive=[],
            language="en",
            full_text=anticipatory_bail_text,
            parser_version="seed-v1",
        )
    )
    session.add(
        DocumentChunk(
            chunk_id="chunk-bnss-480",
            doc_id="doc-bnss-480",
            doc_type=LegalDocumentType.STATUTE,
            text=anticipatory_bail_text,
            text_normalized=anticipatory_bail_text.lower(),
            chunk_index=0,
            total_chunks=1,
            section_header="Section 480 - Bail in non-bailable offence",
            act_name="Bharatiya Nagarik Suraksha Sanhita, 2023",
            section_number="480",
            court="Parliament of India",
            jurisdiction_binding=["All India"],
            jurisdiction_persuasive=[],
            current_validity=ValidityStatus.GOOD_LAW,
            practice_area=["criminal"],
            is_in_force=True,
        )
    )
    session.add(
        LegalDocument(
            doc_id="doc-sc-bail-liberty",
            doc_type=LegalDocumentType.JUDGMENT,
            court="Supreme Court",
            citation="(2025) 3 SCC 100",
            parties={"appellant": "Asha Rao", "respondent": "State of Maharashtra"},
            current_validity=ValidityStatus.GOOD_LAW,
            practice_areas=["criminal"],
            jurisdiction_binding=["All India"],
            jurisdiction_persuasive=[],
            bench=["Justice A", "Justice B"],
            coram=2,
            language="en",
            full_text=(
                "The Supreme Court held that bail decisions must protect liberty and "
                "that custody requires concrete investigative justification."
            ),
            parser_version="seed-v1",
        )
    )
    session.add(
        DocumentChunk(
            chunk_id="chunk-sc-bail-liberty",
            doc_id="doc-sc-bail-liberty",
            doc_type=LegalDocumentType.JUDGMENT,
            text=(
                "The Supreme Court held that bail decisions must protect liberty and "
                "that custody requires concrete investigative justification."
            ),
            text_normalized=(
                "the supreme court held that bail decisions must protect liberty and "
                "that custody requires concrete investigative justification."
            ),
            chunk_index=0,
            total_chunks=1,
            section_header="Holding",
            court="Supreme Court",
            citation="(2025) 3 SCC 100",
            jurisdiction_binding=["All India"],
            jurisdiction_persuasive=[],
            current_validity=ValidityStatus.GOOD_LAW,
            practice_area=["criminal"],
        )
    )
    session.commit()


def test_langgraph_agentic_workflow_runs_with_sqlite_checkpointer(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'agentic_workflow_grounded.db'}")
    Base.metadata.create_all(engine)
    workflow = LangGraphAgenticWorkflow(sqlite_path=tmp_path / "agentic.sqlite")
    try:
        with Session(engine) as session:
            _seed_agentic_corpus(session)
            result = workflow.run(
                user_query="What are my bail arguments?",
                case_context=_build_case_context(),
                thread_id="thread-agentic-1",
                session=session,
            )
    finally:
        workflow.close()
        engine.dispose()

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
    assert (
        result.structured_answer.section(
            StructuredAnswerSectionKind.APPLICABLE_LAW
        ).claims[0].citation_badges
    )
    assert (
        result.structured_answer.section(
            StructuredAnswerSectionKind.KEY_CASES
        ).claims[0].citation_badges
    )
    assert (
        result.structured_answer.section(
            StructuredAnswerSectionKind.KEY_CASES
        ).claims[0].citation_badges[0].doc_id
        == "doc-sc-bail-liberty"
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


def test_langgraph_agentic_workflow_can_use_model_clients(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'agentic_workflow_models.db'}")
    Base.metadata.create_all(engine)
    workflow = LangGraphAgenticWorkflow(
        sqlite_path=tmp_path / "agentic-models.sqlite",
        planner_model_client=FakePlanningModelClient(),
        synthesis_model_client=FakeSynthesisModelClient(),
    )
    try:
        with Session(engine) as session:
            _seed_agentic_corpus(session)
            result = workflow.run(
                user_query="What are my bail arguments?",
                case_context=_build_case_context(),
                thread_id="thread-agentic-models",
                session=session,
            )
    finally:
        workflow.close()
        engine.dispose()

    assert (
        result.research_plan[0].question
        == "Which statutory bail framework applies after the code cutover?"
    )
    assert result.synthesis.startswith(
        "Legal Position: The uploaded bail record supports a liberty-first submission."
    )


def test_workspace_query_stream_uses_agentic_path_and_emits_agent_logs(tmp_path) -> None:
    query_runtime.reset()
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'agentic_query_stream.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    with Session(engine) as session:
        session.add(_build_case_context())
        _seed_agentic_corpus(session)
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
    assert (
        answer_ready_event["answer"]["sections"][1]["claims"][0]["citation_badges"][0]["doc_id"]
        == "doc-bns-101"
    )
    assert (
        answer_ready_event["answer"]["sections"][2]["claims"][0]["citation_badges"][0]["doc_id"]
        == "doc-sc-bail-liberty"
    )
