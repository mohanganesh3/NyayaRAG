import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from app.api.dependencies.auth import AuthContext
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
from app.services.query_history import query_history_store
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger("nyayarag.backend.query_runtime")


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
    auth_user_id: str | None
    auth_session_id: str | None
    auth_provider: str | None
    access_token: str | None
    created_at: datetime


class QueryRuntime:
    def __init__(self) -> None:
        self._queries: dict[str, StoredQuery] = {}
        self._router = QueryRouter()
        self._workspace_loader: Callable[[str], CaseContext | None] = _default_workspace_loader
        self._session_factory_provider: Callable[[], sessionmaker[Session]] = get_session_factory

    def reset(self) -> None:
        self._queries.clear()
        self._workspace_loader = _default_workspace_loader
        self._session_factory_provider = get_session_factory

    def set_workspace_loader(
        self, loader: Callable[[str], CaseContext | None]
    ) -> None:
        self._workspace_loader = loader

    def set_session_factory_provider(
        self,
        provider: Callable[[], sessionmaker[Session]],
    ) -> None:
        self._session_factory_provider = provider

    def create_query(
        self,
        query: str,
        *,
        workspace_id: str | None = None,
        auth: AuthContext | None = None,
    ) -> StoredQuery:
        auth_context = auth or AuthContext(
            user_id=None,
            session_id=None,
            provider=None,
            display_name=None,
            is_authenticated=False,
        )
        record = StoredQuery(
            query_id=str(uuid4()),
            query=query,
            workspace_id=workspace_id,
            auth_user_id=auth_context.user_id,
            auth_session_id=auth_context.session_id,
            auth_provider=auth_context.provider,
            access_token=str(uuid4()) if auth_context.user_id is not None else None,
            created_at=datetime.now(UTC),
        )
        self._queries[record.query_id] = record
        try:
            with self._session_factory_provider()() as session:
                query_history_store.create_entry(
                    session,
                    query_id=record.query_id,
                    query_text=query,
                    auth=auth_context,
                    workspace_id=workspace_id,
                )
                session.commit()
        except SQLAlchemyError:
            logger.warning(
                "query history create skipped",
                extra={"event": "query_history_create_skipped", "query_id": record.query_id},
            )
        return record

    def get_query(self, query_id: str) -> StoredQuery | None:
        return self._queries.get(query_id)

    def build_acceptance(self, record: StoredQuery) -> QueryAcceptedData:
        stream_url = f"/api/query/{record.query_id}/stream"
        if record.access_token is not None:
            stream_url = f"{stream_url}?access_token={record.access_token}"
        return QueryAcceptedData(
            query_id=record.query_id,
            status="accepted",
            stream_url=stream_url,
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
                self._mark_query_error(
                    query_id=record.query_id,
                    pipeline="workspace_lookup",
                    error_message=f"Workspace '{record.workspace_id}' was not found.",
                )
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
                agentic_events = await self._stream_agentic_events(
                    record,
                    workspace_context,
                    analysis.pipeline_reason,
                )
                self._mark_query_completed(
                    query_id=record.query_id,
                    pipeline="agentic_rag",
                    answer_preview=self._joined_output(agentic_events),
                )
                return agentic_events

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

        self._mark_query_completed(
            query_id=record.query_id,
            pipeline="bootstrap-demo",
            answer_preview=self._joined_output(events),
        )

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

    def _mark_query_completed(
        self,
        *,
        query_id: str,
        pipeline: str,
        answer_preview: str | None,
    ) -> None:
        try:
            with self._session_factory_provider()() as session:
                query_history_store.mark_completed(
                    session,
                    query_id=query_id,
                    pipeline=pipeline,
                    answer_preview=answer_preview,
                )
                session.commit()
        except SQLAlchemyError:
            logger.warning(
                "query history completion skipped",
                extra={"event": "query_history_completion_skipped", "query_id": query_id},
            )

    def _mark_query_error(
        self,
        *,
        query_id: str,
        pipeline: str | None,
        error_message: str,
    ) -> None:
        try:
            with self._session_factory_provider()() as session:
                query_history_store.mark_error(
                    session,
                    query_id=query_id,
                    pipeline=pipeline,
                    error_message=error_message,
                )
                session.commit()
        except SQLAlchemyError:
            logger.warning(
                "query history error skipped",
                extra={"event": "query_history_error_skipped", "query_id": query_id},
            )

    def _joined_output(self, events: list[QueryStreamEvent], limit: int = 320) -> str | None:
        preview = "".join(
            event.token
            for event in events
            if isinstance(event, TokenEvent)
        ).strip()
        return preview[:limit] if preview else None


query_runtime = QueryRuntime()
