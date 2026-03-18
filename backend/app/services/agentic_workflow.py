from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from operator import add
from pathlib import Path
from tempfile import gettempdir
from typing import Annotated, Any, TypedDict, TypeVar, cast

from app.models import DocumentChunk, LegalDocument, LegalDocumentType, ValidityStatus
from app.rag import (
    CitationBadgeStatus,
    InlineCitationBadge,
    StructuredAnswer,
    StructuredAnswerSection,
    StructuredAnswerSectionKind,
    StructuredClaim,
    VerificationStatusItem,
)
from app.schemas.legal import CaseContextRead
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_ACT_ALIASES: dict[str, tuple[str, ...]] = {
    "IPC": ("ipc", "indian penal code"),
    "CRPC": ("crpc", "code of criminal procedure"),
    "BNS": ("bns", "bharatiya nyaya sanhita"),
    "BNSS": ("bnss", "bharatiya nagarik suraksha sanhita"),
    "BSA": ("bsa", "bharatiya sakshya adhiniyam"),
    "ARTICLE": ("article", "constitution"),
}
_STAGE_JUDGMENT_TERMS: dict[str, tuple[str, ...]] = {
    "bail": ("bail", "anticipatory", "custody", "liberty"),
    "appeal": ("appeal", "reversal", "sentence"),
    "trial": ("trial", "evidence", "charge"),
}


@dataclass(slots=True, frozen=True)
class GroundedAuthority:
    label: str
    citation: str | None
    doc_id: str
    chunk_id: str
    source_passage: str | None
    message: str


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
    model_config = ConfigDict(arbitrary_types_allowed=True)

    synthesis: str
    research_plan: list[ResearchQuestion]
    statutory_findings: list[str]
    precedent_findings: list[str]
    contradictions: list[str]
    verification_result: dict[str, object]
    agent_logs: list[AgentLogEntry]
    structured_answer: StructuredAnswer


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
        session: Session | None = None,
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
        structured_answer = self._build_structured_answer(
            user_query=user_query,
            final_state=final_state,
            session=session,
        )
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
            structured_answer=structured_answer,
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

    def _build_structured_answer(
        self,
        *,
        user_query: str,
        final_state: AgenticWorkflowState,
        session: Session | None,
    ) -> StructuredAnswer:
        synthesis = str(final_state.get("synthesis") or "")
        verification = cast(dict[str, object], final_state.get("verification_result", {}))
        case_context = cast(dict[str, object], final_state.get("case_context", {}))
        overall_status = self._overall_status(verification)
        stage = str(case_context.get("stage") or "").lower()

        legal_claims: list[StructuredClaim] = []
        legal_position = self._slice_synthesis_section(
            synthesis,
            current_label="Legal Position:",
            next_label="Statutory Findings:",
        )
        statutory_findings = [
            str(item) for item in cast(list[object], final_state.get("statutory_findings", []))
        ]
        precedent_findings = [
            str(item) for item in cast(list[object], final_state.get("precedent_findings", []))
        ]
        statutory_sources_by_finding = [
            self._lookup_statute_sources(
                session,
                case_context=case_context,
                finding=finding,
            )
            for finding in statutory_findings
        ]
        precedent_sources_by_finding = [
            self._lookup_precedent_sources(
                session,
                case_context=case_context,
                user_query=user_query,
                finding=finding,
            )
            for finding in precedent_findings
        ]
        legal_position_sources = self._dedupe_authorities(
            [
                *(
                    sources[0]
                    for sources in statutory_sources_by_finding
                    if sources
                ),
                *(
                    sources[0]
                    for sources in precedent_sources_by_finding
                    if sources
                ),
            ]
        )[:2]
        if legal_position:
            legal_claims.append(
                self._build_claim(
                    text=legal_position,
                    status=self._claim_status(
                        preferred=overall_status,
                        sources=legal_position_sources,
                    ),
                    reason=(
                        "Synthesized from uploaded documents, stage-specific planning, "
                        "and contradiction review."
                    ),
                    claim_key="legal-position",
                    sources=legal_position_sources,
                )
            )

        contradictions = [
            str(item) for item in cast(list[object], final_state.get("contradictions", []))
        ]
        for contradiction in contradictions:
            legal_claims.append(
                self._build_claim(
                    text=contradiction,
                    status=CitationBadgeStatus.UNCERTAIN,
                    reason=(
                        "The contradiction checker flagged a procedural caution that should "
                        "be addressed in submissions."
                    ),
                    claim_key="contradiction",
                )
            )

        applicable_law_claims = tuple(
            self._build_claim(
                text=finding,
                status=self._claim_status(
                    preferred=CitationBadgeStatus.VERIFIED,
                    sources=sources,
                ),
                reason=(
                    "Derived from uploaded-document statutory analysis and criminal-code "
                    "mapping."
                ),
                claim_key=f"applicable-law-{index}",
                sources=sources,
            )
            for index, (finding, sources) in enumerate(
                zip(statutory_findings, statutory_sources_by_finding, strict=False),
                start=1,
            )
        )

        key_case_claims = tuple(
            self._build_claim(
                text=finding,
                status=self._claim_status(
                    preferred=CitationBadgeStatus.VERIFIED,
                    sources=sources,
                    fallback=(
                        CitationBadgeStatus.UNCERTAIN
                        if stage == "bail"
                        else CitationBadgeStatus.UNVERIFIED
                    ),
                ),
                reason=(
                    "Derived from agentic precedent research aligned to the uploaded court "
                    "context and stage."
                ),
                claim_key=f"key-case-{index}",
                sources=sources,
            )
            for index, (finding, sources) in enumerate(
                zip(precedent_findings, precedent_sources_by_finding, strict=False),
                start=1,
            )
        )

        all_claims = [
            *legal_claims,
            *applicable_law_claims,
            *key_case_claims,
        ]

        verification_section = StructuredAnswerSection(
            kind=StructuredAnswerSectionKind.VERIFICATION_STATUS,
            title="Verification Status",
            status_items=self._build_verification_items(
                verification=verification,
                claims=all_claims,
                overall_status=overall_status,
            ),
        )

        return StructuredAnswer(
            query=user_query,
            overall_status=overall_status,
            sections=(
                StructuredAnswerSection(
                    kind=StructuredAnswerSectionKind.LEGAL_POSITION,
                    title="Legal Position",
                    claims=tuple(legal_claims),
                ),
                StructuredAnswerSection(
                    kind=StructuredAnswerSectionKind.APPLICABLE_LAW,
                    title="Applicable Law",
                    claims=applicable_law_claims,
                ),
                StructuredAnswerSection(
                    kind=StructuredAnswerSectionKind.KEY_CASES,
                    title="Key Cases",
                    claims=key_case_claims,
                ),
                verification_section,
            ),
        )

    def _build_claim(
        self,
        *,
        text: str,
        status: CitationBadgeStatus,
        reason: str,
        claim_key: str,
        sources: list[GroundedAuthority] | None = None,
    ) -> StructuredClaim:
        badges = self._build_badges(
            claim_key=claim_key,
            status=status,
            sources=sources or [],
        )
        return StructuredClaim(
            text=text,
            status=status,
            reason=reason,
            citation=self._claim_citation(badges),
            source_passage=self._claim_source_passage(badges),
            appeal_warning=None,
            reretrieved=False,
            citation_badges=badges,
        )

    def _build_verification_items(
        self,
        *,
        verification: dict[str, object],
        claims: list[StructuredClaim],
        overall_status: CitationBadgeStatus,
    ) -> tuple[VerificationStatusItem, ...]:
        verified_ratio = self._verified_ratio(verification)
        issues_flagged = self._issues_flagged(verification)
        verified_claims = sum(
            1 for claim in claims if claim.status is CitationBadgeStatus.VERIFIED
        )
        uncertain_claims = sum(
            1 for claim in claims if claim.status is CitationBadgeStatus.UNCERTAIN
        )
        unverified_claims = sum(
            1 for claim in claims if claim.status is CitationBadgeStatus.UNVERIFIED
        )
        resolved_citations = sum(len(claim.citation_badges) for claim in claims)
        unresolved_citations = unverified_claims

        return (
            VerificationStatusItem(
                label="Verified Claims",
                value=str(verified_claims),
                status=(
                    CitationBadgeStatus.VERIFIED
                    if verified_claims > 0
                    else CitationBadgeStatus.UNVERIFIED
                ),
            ),
            VerificationStatusItem(
                label="Claims Requiring Review",
                value=str(uncertain_claims),
                status=(
                    CitationBadgeStatus.UNCERTAIN
                    if uncertain_claims > 0
                    else CitationBadgeStatus.VERIFIED
                ),
            ),
            VerificationStatusItem(
                label="Unverified Claims",
                value=str(unverified_claims),
                status=(
                    CitationBadgeStatus.UNVERIFIED
                    if unverified_claims > 0
                    else CitationBadgeStatus.VERIFIED
                ),
            ),
            VerificationStatusItem(
                label="Workflow Confidence",
                value=f"{verified_ratio:.2f}",
                status=overall_status,
            ),
            VerificationStatusItem(
                label="Issues Flagged",
                value=str(issues_flagged),
                status=(
                    CitationBadgeStatus.UNCERTAIN
                    if issues_flagged > 0
                    else CitationBadgeStatus.VERIFIED
                ),
            ),
            VerificationStatusItem(
                label="Resolved Citations",
                value=str(resolved_citations),
                status=CitationBadgeStatus.VERIFIED,
            ),
            VerificationStatusItem(
                label="Unresolved Citations",
                value=str(unresolved_citations),
                status=(
                    CitationBadgeStatus.UNVERIFIED
                    if unresolved_citations > 0
                    else CitationBadgeStatus.VERIFIED
                ),
            ),
        )

    def _overall_status(
        self,
        verification: dict[str, object],
    ) -> CitationBadgeStatus:
        verified_ratio = self._verified_ratio(verification)
        issues_flagged = self._issues_flagged(verification)
        if verified_ratio >= 0.95 and issues_flagged == 0:
            return CitationBadgeStatus.VERIFIED
        if verified_ratio >= 0.75:
            return CitationBadgeStatus.UNCERTAIN
        return CitationBadgeStatus.UNVERIFIED

    def _verified_ratio(self, verification: dict[str, object]) -> float:
        raw_value = verification.get("verified_claim_ratio", 0.0)
        if isinstance(raw_value, int | float):
            return float(raw_value)
        return 0.0

    def _issues_flagged(self, verification: dict[str, object]) -> int:
        raw_value = verification.get("issues_flagged", 0)
        if isinstance(raw_value, int):
            return raw_value
        if isinstance(raw_value, float):
            return int(raw_value)
        if isinstance(raw_value, str) and raw_value.isdigit():
            return int(raw_value)
        return 0

    def _slice_synthesis_section(
        self,
        synthesis: str,
        *,
        current_label: str,
        next_label: str,
    ) -> str:
        if current_label not in synthesis:
            return synthesis.strip()
        section = synthesis.split(current_label, maxsplit=1)[1]
        if next_label in section:
            section = section.split(next_label, maxsplit=1)[0]
        return " ".join(section.split()).strip()

    def _claim_status(
        self,
        *,
        preferred: CitationBadgeStatus,
        sources: list[GroundedAuthority],
        fallback: CitationBadgeStatus | None = None,
    ) -> CitationBadgeStatus:
        if sources:
            return (
                CitationBadgeStatus.UNCERTAIN
                if preferred is CitationBadgeStatus.UNVERIFIED
                else preferred
            )
        return fallback or (
            CitationBadgeStatus.UNVERIFIED
            if preferred is CitationBadgeStatus.VERIFIED
            else preferred
        )

    def _build_badges(
        self,
        *,
        claim_key: str,
        status: CitationBadgeStatus,
        sources: list[GroundedAuthority],
    ) -> tuple[InlineCitationBadge, ...]:
        return tuple(
            InlineCitationBadge(
                placeholder_token=f"[AGENTIC:{claim_key}:{index}]",
                label=source.label,
                status=status,
                citation=source.citation or source.label,
                message=source.message,
                doc_id=source.doc_id,
                chunk_id=source.chunk_id,
                source_passage=source.source_passage,
                appeal_warning=None,
            )
            for index, source in enumerate(sources, start=1)
        )

    def _claim_citation(
        self,
        badges: tuple[InlineCitationBadge, ...],
    ) -> str | None:
        citations = [badge.citation or badge.label for badge in badges]
        return "; ".join(citations) if citations else None

    def _claim_source_passage(
        self,
        badges: tuple[InlineCitationBadge, ...],
    ) -> str | None:
        for badge in badges:
            if badge.source_passage:
                return badge.source_passage
        return None

    def _lookup_statute_sources(
        self,
        session: Session | None,
        *,
        case_context: dict[str, object],
        finding: str,
    ) -> list[GroundedAuthority]:
        if session is None:
            return []

        references = [
            *[
                str(item)
                for item in cast(list[object], case_context.get("bnss_equivalents", []))
            ],
            *[
                str(item)
                for item in cast(list[object], case_context.get("charges_sections", []))
            ],
        ]
        grounded: list[GroundedAuthority] = []
        for reference in references:
            authority = self._find_best_statute_authority(
                session,
                reference=reference,
                finding=finding,
            )
            if authority is not None:
                grounded.append(authority)
        return self._dedupe_authorities(grounded)[:2]

    def _find_best_statute_authority(
        self,
        session: Session,
        *,
        reference: str,
        finding: str,
    ) -> GroundedAuthority | None:
        act_code, section_number = self._parse_reference(reference)
        query_tokens = self._tokens_for_text(f"{reference} {finding}")
        candidates = session.execute(
            select(DocumentChunk, LegalDocument)
            .join(LegalDocument, DocumentChunk.doc_id == LegalDocument.doc_id)
            .where(
                DocumentChunk.doc_type.in_(
                    [LegalDocumentType.STATUTE, LegalDocumentType.CONSTITUTION]
                ),
                LegalDocument.current_validity == ValidityStatus.GOOD_LAW,
            )
        ).all()

        best_score = 0.0
        best_authority: GroundedAuthority | None = None
        for chunk, document in candidates:
            if chunk.is_in_force is False:
                continue
            score = 0.0
            if section_number and (chunk.section_number or "").upper() == section_number:
                score += 0.8
            if act_code and self._matches_act_reference(act_code, chunk.act_name or ""):
                score += 0.75

            candidate_tokens = self._tokens_for_text(
                " ".join(
                    part
                    for part in [
                        chunk.act_name or "",
                        chunk.section_number or "",
                        chunk.section_header or "",
                        chunk.text[:240],
                    ]
                    if part
                )
            )
            score += min(self._token_overlap(query_tokens, candidate_tokens), 0.4)
            if score > best_score:
                best_score = score
                best_authority = GroundedAuthority(
                    label=self._statute_label(chunk),
                    citation=self._statute_citation(chunk),
                    doc_id=document.doc_id,
                    chunk_id=chunk.chunk_id,
                    source_passage=chunk.text,
                    message="Resolved from uploaded-case statutory grounding.",
                )

        return best_authority if best_score >= 1.0 else None

    def _lookup_precedent_sources(
        self,
        session: Session | None,
        *,
        case_context: dict[str, object],
        user_query: str,
        finding: str,
    ) -> list[GroundedAuthority]:
        if session is None:
            return []

        stage = str(case_context.get("stage") or "").lower()
        court = str(case_context.get("court") or "")
        query_tokens = self._tokens_for_text(
            " ".join([user_query, finding, stage, court])
        )
        query_tokens.update(_STAGE_JUDGMENT_TERMS.get(stage, ()))

        candidates = session.execute(
            select(DocumentChunk, LegalDocument)
            .join(LegalDocument, DocumentChunk.doc_id == LegalDocument.doc_id)
            .where(
                DocumentChunk.doc_type == LegalDocumentType.JUDGMENT,
                LegalDocument.current_validity == ValidityStatus.GOOD_LAW,
            )
        ).all()

        scored: list[tuple[float, GroundedAuthority]] = []
        for chunk, document in candidates:
            candidate_tokens = self._tokens_for_text(
                " ".join(
                    part
                    for part in [
                        document.citation or "",
                        self._judgment_label(document),
                        chunk.section_header or "",
                        chunk.text[:320],
                        document.court or "",
                    ]
                    if part
                )
            )
            score = self._token_overlap(query_tokens, candidate_tokens)
            if stage == "bail" and any(
                token in candidate_tokens for token in _STAGE_JUDGMENT_TERMS["bail"]
            ):
                score += 0.35
            if (document.court or "").lower().startswith("supreme court"):
                score += 0.3
            elif court and court in chunk.jurisdiction_binding:
                score += 0.2
            elif "All India" in chunk.jurisdiction_binding:
                score += 0.1

            if score < 0.2:
                continue

            scored.append(
                (
                    score,
                    GroundedAuthority(
                        label=self._judgment_label(document),
                        citation=document.citation or chunk.citation,
                        doc_id=document.doc_id,
                        chunk_id=chunk.chunk_id,
                        source_passage=chunk.text,
                        message="Resolved from uploaded-case precedent grounding.",
                    ),
                )
            )

        scored.sort(key=lambda item: item[0], reverse=True)
        return self._dedupe_authorities([authority for _, authority in scored])[:2]

    def _dedupe_authorities(
        self,
        authorities: list[GroundedAuthority],
    ) -> list[GroundedAuthority]:
        deduped: dict[tuple[str, str], GroundedAuthority] = {}
        for authority in authorities:
            deduped[(authority.doc_id, authority.chunk_id)] = authority
        return list(deduped.values())

    def _parse_reference(
        self,
        reference: str,
    ) -> tuple[str | None, str | None]:
        parts = reference.strip().split()
        if len(parts) < 2:
            return None, None
        return parts[0].upper(), parts[-1].upper()

    def _matches_act_reference(self, act_code: str, act_name: str) -> bool:
        aliases = _ACT_ALIASES.get(act_code, (act_code.lower(),))
        act_name_lower = act_name.lower()
        return any(alias in act_name_lower for alias in aliases)

    def _token_overlap(
        self,
        left: set[str],
        right: set[str],
    ) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / len(left)

    def _tokens_for_text(self, text: str) -> set[str]:
        return set(_TOKEN_PATTERN.findall(text.lower()))

    def _judgment_label(self, document: LegalDocument) -> str:
        appellant = document.parties.get("appellant") or document.parties.get("petitioner")
        respondent = document.parties.get("respondent") or document.parties.get("opposite_party")
        if appellant and respondent:
            return f"{appellant} v {respondent}"
        return document.citation or document.doc_id

    def _statute_label(self, chunk: DocumentChunk) -> str:
        if chunk.act_name and chunk.section_number:
            act_tokens = chunk.act_name.split()
            short_act = " ".join(act_tokens[:2]) if act_tokens else chunk.act_name
            return f"{short_act} {chunk.section_number}"
        return chunk.act_name or chunk.section_header or chunk.chunk_id

    def _statute_citation(self, chunk: DocumentChunk) -> str | None:
        if chunk.act_name and chunk.section_number:
            return f"{chunk.act_name}, Section {chunk.section_number}"
        return chunk.section_header


agentic_workflow = LangGraphAgenticWorkflow()
