from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.legal import CaseContextRead
from app.schemas.query import QueryHistoryEntryRead


class CaseContextResponse(BaseModel):
    success: Literal[True] = True
    data: CaseContextRead


class WorkspaceQueryHistoryResponse(BaseModel):
    success: Literal[True] = True
    data: list[QueryHistoryEntryRead]


class WorkspaceListItemRead(BaseModel):
    case_id: str
    appellant_petitioner: str | None = None
    respondent_opposite_party: str | None = None
    court: str | None = None
    case_number: str | None = None
    stage: str | None = None
    case_type: str | None = None
    uploaded_doc_count: int = 0
    updated_at: datetime


class WorkspaceListResponse(BaseModel):
    success: Literal[True] = True
    data: list[WorkspaceListItemRead]


class SavedWorkspaceAnswerRead(BaseModel):
    id: str
    workspace_id: str
    auth_user_id: str
    query_text: str
    overall_status: str
    answer: dict[str, object]
    created_at: datetime
    updated_at: datetime


class WorkspaceSavedAnswersResponse(BaseModel):
    success: Literal[True] = True
    data: list[SavedWorkspaceAnswerRead]


class WorkspaceSavedAnswerCreateRequest(BaseModel):
    query_text: str = Field(min_length=1, max_length=4000)
    overall_status: str = Field(min_length=1, max_length=50)
    answer: dict[str, object]


class WorkspaceSavedAnswerResponse(BaseModel):
    success: Literal[True] = True
    data: SavedWorkspaceAnswerRead
