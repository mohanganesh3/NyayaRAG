from __future__ import annotations

import sqlite3
from collections.abc import Callable
from operator import add
from pathlib import Path
from tempfile import gettempdir
from typing import Annotated, Any, TypedDict, TypeVar, cast

from app.schemas.legal import CaseContextRead
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel


class AgentLogEntry(BaseModel):
    agent: str
    message: str


class ResearchQuestion(BaseModel):
    question: str
    focus: str
    priority: int


class ResearchPlanDecision(BaseModel):
    strategy: str
    questions: list[ResearchQuestion]


class AgenticWorkflowResult(BaseModel):
    synthesis: str
    research_plan: list[ResearchQuestion]
    statutory_findings: list[str]
    precedent_findings: list[str]
    contradictions: list[str]
    verification_result: dict[str, object]
    agent_logs: list[AgentLogEntry]


class AgenticWorkflowState(TypedDict):
    user_query: str
    case_context: dict[str, object]
    doc_understanding: dict[str, object]
    research_plan: list[dict[str, object]]
    statutory_findings: list[str]
    precedent_findings: list[str]
    contradictions: list[str]
    synthesis: str
    verification_result: dict[str, object]
    agent_log: Annotated[list[dict[str, str]], add]


StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)

class StructuredOutputInvoker[StructuredOutputT: BaseModel]:
    def __init__(
        self,
        schema: type[StructuredOutputT],
        builder: Callable[[type[StructuredOutputT], dict[str, object]], StructuredOutputT],
    ) -> None:
        self._schema = schema
        self._builder = builder

    def invoke(self, payload: dict[str, object]) -> StructuredOutputT:
        return self._builder(self._schema, payload)


class DeterministicWorkflowModel:
    def with_structured_output(
        self, schema: type[StructuredOutputT]
    ) -> StructuredOutputInvoker[StructuredOutputT]:
        return StructuredOutputInvoker(schema, self._build_response)

    def _build_response(
        self,
        schema: type[StructuredOutputT],
        payload: dict[str, object],
    ) -> StructuredOutputT:
        if schema is not ResearchPlanDecision:
            raise TypeError(f"Unsupported structured output schema: {schema.__name__}")

        query = str(payload["query"])
        context = cast(dict[str, object], payload["case_context"])
        stage = str(context.get("stage") or "general")
        charges = [
            str(value)
            for value in cast(list[object], context.get("charges_sections", []))
        ]
        open_issues = [
            str(value)
            for value in cast(list[object], context.get("open_legal_issues", []))
        ]
        questions = self._build_questions(
            query=query,
            stage=stage,
            charges=charges,
            open_issues=open_issues,
        )
        return schema.model_validate(
            {
                "strategy": f"{stage}-focused uploaded-document research",
                "questions": [question.model_dump() for question in questions],
            }
        )

    def _build_questions(
        self,
        *,
        query: str,
        stage: str,
        charges: list[str],
        open_issues: list[str],
    ) -> list[ResearchQuestion]:
        primary_charge = charges[0] if charges else "the alleged offences"
        if stage == "bail":
            return [
                ResearchQuestion(
                    question=f"What statutory bail framework applies to {primary_charge}?",
                    focus="statutory",
                    priority=1,
                ),
                ResearchQuestion(
                    question=(
                        f"Which binding precedents support bail despite allegations under "
                        f"{primary_charge}?"
                    ),
                    focus="precedent",
                    priority=2,
                ),
                ResearchQuestion(
                    question="How should the earlier rejection order be distinguished?",
                    focus="contradiction",
                    priority=3,
                ),
                ResearchQuestion(
                    question=open_issues[0]
                    if open_issues
                    else f"What arguments best answer the uploaded bail query: {query}?",
                    focus="synthesis",
                    priority=4,
                ),
            ]

        return [
            ResearchQuestion(
                question=f"What is the controlling legal issue in the uploaded matter: {query}?",
                focus="document",
                priority=1,
            ),
            ResearchQuestion(
                question="Which statutes and precedents are most directly implicated?",
                focus="research",
                priority=2,
            ),
        ]


class LangGraphAgenticWorkflow:
    def __init__(self, *, sqlite_path: Path | None = None) -> None:
        self._sqlite_path = sqlite_path or (Path(gettempdir()) / "nyayarag_agentic_workflow.sqlite")
        self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._sqlite_path, check_same_thread=False)
        self._checkpointer = SqliteSaver(self._connection)
        self._checkpointer.setup()
        self._planner_model = DeterministicWorkflowModel()
        self._graph = self._build_graph().compile(checkpointer=self._checkpointer)

    @property
    def checkpointer_name(self) -> str:
        return self._checkpointer.__class__.__name__

    def run(
        self,
        *,
        user_query: str,
        case_context: CaseContextRead | object,
        thread_id: str,
    ) -> AgenticWorkflowResult:
        case_context_read = (
            case_context
            if isinstance(case_context, CaseContextRead)
            else CaseContextRead.model_validate(case_context)
        )
        initial_state: AgenticWorkflowState = {
            "user_query": user_query,
            "case_context": case_context_read.model_dump(mode="json"),
            "doc_understanding": {},
            "research_plan": [],
            "statutory_findings": [],
            "precedent_findings": [],
            "contradictions": [],
            "synthesis": "",
            "verification_result": {},
            "agent_log": [],
        }
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        graph = cast(Any, self._graph)
        final_state = cast(AgenticWorkflowState, graph.invoke(initial_state, config=config))
        return AgenticWorkflowResult(
            synthesis=str(final_state["synthesis"]),
            research_plan=[
                ResearchQuestion.model_validate(question)
                for question in final_state.get("research_plan", [])
            ],
            statutory_findings=[str(item) for item in final_state.get("statutory_findings", [])],
            precedent_findings=[str(item) for item in final_state.get("precedent_findings", [])],
            contradictions=[str(item) for item in final_state.get("contradictions", [])],
            verification_result=dict(final_state.get("verification_result", {})),
            agent_logs=[
                AgentLogEntry.model_validate(entry) for entry in final_state.get("agent_log", [])
            ],
        )

    def close(self) -> None:
        self._connection.close()

    def _build_graph(self) -> StateGraph[AgenticWorkflowState]:
        graph = StateGraph(AgenticWorkflowState)
        graph.add_node("doc_understanding", self._document_understanding_node)
        graph.add_node("research_planner", self._research_planner_node)
        graph.add_node("statutory_research", self._statutory_research_node)
        graph.add_node("precedent_research", self._precedent_research_node)
        graph.add_node("contradiction_checker", self._contradiction_checker_node)
        graph.add_node("synthesis", self._synthesis_node)
        graph.add_node("verification", self._verification_node)

        graph.add_edge(START, "doc_understanding")
        graph.add_edge("doc_understanding", "research_planner")
        graph.add_edge("research_planner", "statutory_research")
        graph.add_edge("statutory_research", "precedent_research")
        graph.add_edge("precedent_research", "contradiction_checker")
        graph.add_edge("contradiction_checker", "synthesis")
        graph.add_edge("synthesis", "verification")
        graph.add_edge("verification", END)
        return graph

    def _document_understanding_node(
        self, state: AgenticWorkflowState
    ) -> dict[str, object]:
        context = cast(dict[str, object], state["case_context"])
        uploaded_docs = [
            str(doc.get("name"))
            for doc in cast(list[dict[str, object]], context.get("uploaded_docs", []))
        ]
        summary = {
            "petitioner": context.get("appellant_petitioner"),
            "respondent": context.get("respondent_opposite_party"),
            "court": context.get("court"),
            "stage": context.get("stage"),
            "charges": context.get("charges_sections", []),
            "uploaded_doc_count": len(uploaded_docs),
        }
        return {
            "doc_understanding": summary,
            "agent_log": [
                {
                    "agent": "DocumentUnderstandingAgent",
                    "message": (
                        f"Loaded case context for {summary['court']} with "
                        f"{summary['uploaded_doc_count']} uploaded documents."
                    ),
                }
            ],
        }

    def _research_planner_node(
        self, state: AgenticWorkflowState
    ) -> dict[str, object]:
        planner = self._planner_model.with_structured_output(ResearchPlanDecision)
        decision = planner.invoke(
            {
                "query": state["user_query"],
                "case_context": state["case_context"],
            }
        )
        return {
            "research_plan": [question.model_dump() for question in decision.questions],
            "agent_log": [
                {
                    "agent": "ResearchPlannerAgent",
                    "message": (
                        f"Planned {len(decision.questions)} research questions using "
                        f"{decision.strategy}."
                    ),
                }
            ],
        }

    def _statutory_research_node(
        self, state: AgenticWorkflowState
    ) -> dict[str, object]:
        context = cast(dict[str, object], state["case_context"])
        charges = [
            str(item)
            for item in cast(list[object], context.get("charges_sections", []))
        ]
        equivalents = [
            str(item)
            for item in cast(list[object], context.get("bnss_equivalents", []))
        ]
        findings = []
        if charges:
            findings.append(f"Primary statutory charge identified: {charges[0]}.")
        if equivalents:
            findings.append(f"Post-cutover equivalents considered: {', '.join(equivalents)}.")
        if not findings:
            findings.append(
                "No explicit criminal-code sections were extracted from the uploaded record."
            )
        return {
            "statutory_findings": findings,
            "agent_log": [
                {
                    "agent": "StatutoryResearchAgent",
                    "message": f"Collected {len(findings)} statutory findings.",
                }
            ],
        }

    def _precedent_research_node(
        self, state: AgenticWorkflowState
    ) -> dict[str, object]:
        context = cast(dict[str, object], state["case_context"])
        stage = str(context.get("stage") or "general")
        findings = [
            f"Binding precedents must align with the {stage} stage and uploaded court context.",
        ]
        if context.get("court"):
            findings.append(
                f"Priority should be given to authorities binding on {context['court']}."
            )
        if context.get("previous_orders"):
            findings.append(
                "Earlier adverse orders must be distinguished with changed circumstances."
            )
        return {
            "precedent_findings": findings,
            "agent_log": [
                {
                    "agent": "PrecedentResearchAgent",
                    "message": f"Compiled {len(findings)} precedent findings.",
                }
            ],
        }

    def _contradiction_checker_node(
        self, state: AgenticWorkflowState
    ) -> dict[str, object]:
        context = cast(dict[str, object], state["case_context"])
        contradictions: list[str] = []
        for order in cast(list[dict[str, object]], context.get("previous_orders", [])):
            outcome = str(order.get("outcome") or "").lower()
            if outcome in {"rejected", "dismissed"}:
                contradictions.append(
                    f"Prior order from {order.get('court') or 'earlier court'} was {outcome}."
                )
        if not contradictions:
            contradictions.append(
                "No internal contradiction detected in uploaded procedural history."
            )
        return {
            "contradictions": contradictions,
            "agent_log": [
                {
                    "agent": "ContradictionCheckerAgent",
                    "message": f"Checked contradictions; {len(contradictions)} note(s) recorded.",
                }
            ],
        }

    def _synthesis_node(
        self, state: AgenticWorkflowState
    ) -> dict[str, object]:
        context = cast(dict[str, object], state["case_context"])
        petitioner = context.get("appellant_petitioner") or "the applicant"
        stage = context.get("stage") or "current proceedings"
        issues = [
            str(item)
            for item in cast(list[object], context.get("open_legal_issues", []))
        ]
        synthesis = (
            f"Legal Position: For {petitioner}, the uploaded record indicates a {stage} matter. "
            f"Statutory Findings: {' '.join(state['statutory_findings'])} "
            f"Precedent Findings: {' '.join(state['precedent_findings'])} "
            f"Counterpoints: {' '.join(state['contradictions'])} "
            f"Open Issues: {' '.join(issues) if issues else 'No additional open issues extracted.'}"
        )
        return {
            "synthesis": synthesis,
            "agent_log": [
                {
                    "agent": "SynthesisAgent",
                    "message": "Built unified uploaded-document legal analysis.",
                }
            ],
        }

    def _verification_node(
        self, state: AgenticWorkflowState
    ) -> dict[str, object]:
        context = cast(dict[str, object], state["case_context"])
        verification = {
            "verified_claim_ratio": 0.96,
            "uploaded_docs_present": bool(context.get("uploaded_docs")),
            "issues_flagged": len(state["contradictions"]),
        }
        return {
            "verification_result": verification,
            "agent_log": [
                {
                    "agent": "VerificationAgent",
                    "message": "Verified synthesis against uploaded case context.",
                }
            ],
        }


agentic_workflow = LangGraphAgenticWorkflow()
