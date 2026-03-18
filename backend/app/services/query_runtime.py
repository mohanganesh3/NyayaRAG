import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from app.db.session import get_session_factory
from app.models import CaseContext
from app.rag import QueryRouter
from app.schemas.legal import CaseContextRead
from app.schemas.query import QueryAcceptedData
from app.schemas.stream import (
    AgentLogEvent,
    CompleteEvent,
    QueryStreamEvent,
    StepCompleteEvent,
    StepErrorEvent,
    StepStartEvent,
    StreamEventType,
    TokenEvent,
)
from app.services.agentic_workflow import agentic_workflow


def _default_workspace_loader(workspace_id: str) -> CaseContext | None:
    with get_session_factory()() as session:
        context = session.get(CaseContext, workspace_id)
        if context is None:
            return None
        session.expunge(context)
        return context


@dataclass(slots=True)
class StoredQuery:
    query_id: str
    query: str
    workspace_id: str | None
    created_at: datetime


class QueryRuntime:
    def __init__(self) -> None:
        self._queries: dict[str, StoredQuery] = {}
        self._router = QueryRouter()
        self._workspace_loader: Callable[[str], CaseContext | None] = _default_workspace_loader

    def reset(self) -> None:
        self._queries.clear()
        self._workspace_loader = _default_workspace_loader

    def set_workspace_loader(
        self, loader: Callable[[str], CaseContext | None]
    ) -> None:
        self._workspace_loader = loader

    def create_query(self, query: str, workspace_id: str | None = None) -> StoredQuery:
        record = StoredQuery(
            query_id=str(uuid4()),
            query=query,
            workspace_id=workspace_id,
            created_at=datetime.now(UTC),
        )
        self._queries[record.query_id] = record
        return record

    def get_query(self, query_id: str) -> StoredQuery | None:
        return self._queries.get(query_id)

    def build_acceptance(self, record: StoredQuery) -> QueryAcceptedData:
        return QueryAcceptedData(
            query_id=record.query_id,
            status="accepted",
            stream_url=f"/api/query/{record.query_id}/stream",
            created_at=record.created_at,
        )

    async def stream_query_events(self, query_id: str) -> list[QueryStreamEvent]:
        record = self.get_query(query_id)
        if record is None:
            return []

        workspace_context = None
        if record.workspace_id is not None:
            workspace_context = self._workspace_loader(record.workspace_id)
            if workspace_context is None:
                return [
                    StepErrorEvent(
                        type=StreamEventType.STEP_ERROR,
                        sequence=1,
                        emitted_at=datetime.now(UTC),
                        step="Loading workspace",
                        error=f"Workspace '{record.workspace_id}' was not found.",
                    ),
                    CompleteEvent(
                        type=StreamEventType.COMPLETE,
                        sequence=2,
                        emitted_at=datetime.now(UTC),
                        confidence=0.0,
                        metrics={"mode": "workspace_error", "event_count": 2},
                    ),
                ]

            analysis = self._router.analyze(
                record.query,
                case_context=workspace_context,
            )
            if analysis.selected_pipeline.value == "agentic_rag":
                return await self._stream_agentic_events(
                    record,
                    workspace_context,
                    analysis.pipeline_reason,
                )

        events: list[QueryStreamEvent] = [
            StepStartEvent(
                type=StreamEventType.STEP_START,
                sequence=1,
                emitted_at=datetime.now(UTC),
                step="Analyzing query...",
            ),
            StepCompleteEvent(
                type=StreamEventType.STEP_COMPLETE,
                sequence=2,
                emitted_at=datetime.now(UTC),
                step="Query analyzed",
                data={"query_preview": record.query[:80], "pipeline": "bootstrap-demo"},
            ),
            TokenEvent(
                type=StreamEventType.TOKEN,
                sequence=3,
                emitted_at=datetime.now(UTC),
                token="NyayaRAG",
            ),
            TokenEvent(
                type=StreamEventType.TOKEN,
                sequence=4,
                emitted_at=datetime.now(UTC),
                token=" bootstrap stream ready.",
            ),
            CompleteEvent(
                type=StreamEventType.COMPLETE,
                sequence=5,
                emitted_at=datetime.now(UTC),
                confidence=1.0,
                metrics={"mode": "dummy", "event_count": 5},
            ),
        ]

        for _ in events:
            await asyncio.sleep(0)
        return events

    async def _stream_agentic_events(
        self,
        record: StoredQuery,
        workspace_context: CaseContext,
        pipeline_reason: str,
    ) -> list[QueryStreamEvent]:
        context_read = CaseContextRead.model_validate(workspace_context)
        workflow_result = agentic_workflow.run(
            user_query=record.query,
            case_context=context_read,
            thread_id=record.query_id,
        )

        sequence = 1
        events: list[QueryStreamEvent] = [
            StepStartEvent(
                type=StreamEventType.STEP_START,
                sequence=sequence,
                emitted_at=datetime.now(UTC),
                step="Analyzing uploaded-document query...",
            )
        ]
        sequence += 1
        events.append(
            StepCompleteEvent(
                type=StreamEventType.STEP_COMPLETE,
                sequence=sequence,
                emitted_at=datetime.now(UTC),
                step="Query analyzed",
                data={
                    "pipeline": "agentic_rag",
                    "workspace_id": record.workspace_id,
                    "reason": pipeline_reason,
                },
            )
        )
        sequence += 1
        events.append(
            StepStartEvent(
                type=StreamEventType.STEP_START,
                sequence=sequence,
                emitted_at=datetime.now(UTC),
                step="Running LangGraph agentic workflow...",
            )
        )
        sequence += 1

        for log_entry in workflow_result.agent_logs:
            events.append(
                AgentLogEvent(
                    type=StreamEventType.AGENT_LOG,
                    sequence=sequence,
                    emitted_at=datetime.now(UTC),
                    agent=log_entry.agent,
                    message=log_entry.message,
                )
            )
            sequence += 1

        events.append(
            StepCompleteEvent(
                type=StreamEventType.STEP_COMPLETE,
                sequence=sequence,
                emitted_at=datetime.now(UTC),
                step="Agentic workflow completed",
                data={
                    "research_question_count": len(workflow_result.research_plan),
                    "verification_ratio": workflow_result.verification_result.get(
                        "verified_claim_ratio",
                        0.0,
                    ),
                },
            )
        )
        sequence += 1

        for token in self._chunk_tokens(workflow_result.synthesis):
            events.append(
                TokenEvent(
                    type=StreamEventType.TOKEN,
                    sequence=sequence,
                    emitted_at=datetime.now(UTC),
                    token=token,
                )
            )
            sequence += 1

        verification_ratio = workflow_result.verification_result.get("verified_claim_ratio", 0.0)
        confidence = (
            float(verification_ratio)
            if isinstance(verification_ratio, int | float)
            else 0.0
        )

        events.append(
            CompleteEvent(
                type=StreamEventType.COMPLETE,
                sequence=sequence,
                emitted_at=datetime.now(UTC),
                confidence=confidence,
                metrics={
                    "mode": "agentic",
                    "pipeline": "agentic_rag",
                    "event_count": sequence,
                    "agent_count": len(workflow_result.agent_logs),
                },
            )
        )

        for _ in events:
            await asyncio.sleep(0)
        return events

    def _chunk_tokens(self, text: str, chunk_size: int = 48) -> list[str]:
        return [text[index : index + chunk_size] for index in range(0, len(text), chunk_size)]


query_runtime = QueryRuntime()
