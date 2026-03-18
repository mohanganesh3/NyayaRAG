import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from app.schemas.query import QueryAcceptedData
from app.schemas.stream import (
    CompleteEvent,
    QueryStreamEvent,
    StepCompleteEvent,
    StepStartEvent,
    StreamEventType,
    TokenEvent,
)


@dataclass(slots=True)
class StoredQuery:
    query_id: str
    query: str
    created_at: datetime


class QueryRuntime:
    def __init__(self) -> None:
        self._queries: dict[str, StoredQuery] = {}

    def reset(self) -> None:
        self._queries.clear()

    def create_query(self, query: str) -> StoredQuery:
        record = StoredQuery(
            query_id=str(uuid4()),
            query=query,
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


query_runtime = QueryRuntime()
