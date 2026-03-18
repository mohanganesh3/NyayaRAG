from typing import Literal

from pydantic import BaseModel

from app.schemas.legal import CaseContextRead
from app.schemas.query import QueryHistoryEntryRead


class CaseContextResponse(BaseModel):
    success: Literal[True] = True
    data: CaseContextRead


class WorkspaceQueryHistoryResponse(BaseModel):
    success: Literal[True] = True
    data: list[QueryHistoryEntryRead]
