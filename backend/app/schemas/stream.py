from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class StreamEventType(StrEnum):
    STEP_START = "STEP_START"
    STEP_COMPLETE = "STEP_COMPLETE"
    STEP_ERROR = "STEP_ERROR"
    AGENT_LOG = "AGENT_LOG"
    TOKEN = "TOKEN"
    CITATION_RESOLVED = "CITATION_RESOLVED"
    COMPLETE = "COMPLETE"


class StreamEventBase(BaseModel):
    sequence: int
    emitted_at: datetime


class StepStartEvent(StreamEventBase):
    type: Literal[StreamEventType.STEP_START]
    step: str


class StepCompleteEvent(StreamEventBase):
    type: Literal[StreamEventType.STEP_COMPLETE]
    step: str
    data: dict[str, object] | None = None


class StepErrorEvent(StreamEventBase):
    type: Literal[StreamEventType.STEP_ERROR]
    step: str
    error: str


class AgentLogEvent(StreamEventBase):
    type: Literal[StreamEventType.AGENT_LOG]
    agent: str
    message: str


class TokenEvent(StreamEventBase):
    type: Literal[StreamEventType.TOKEN]
    token: str


class CitationResolvedEvent(StreamEventBase):
    type: Literal[StreamEventType.CITATION_RESOLVED]
    placeholder: str
    citation: str
    status: str


class CompleteEvent(StreamEventBase):
    type: Literal[StreamEventType.COMPLETE]
    confidence: float
    metrics: dict[str, object] = Field(default_factory=dict)


QueryStreamEvent = Annotated[
    StepStartEvent
    | StepCompleteEvent
    | StepErrorEvent
    | AgentLogEvent
    | TokenEvent
    | CitationResolvedEvent
    | CompleteEvent,
    Field(discriminator="type"),
]

