from typing import Literal

from pydantic import BaseModel

from app.schemas.legal import CaseContextRead


class CaseContextResponse(BaseModel):
    success: Literal[True] = True
    data: CaseContextRead
