from typing import Literal

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    detail: dict[str, object] | list[dict[str, object]] | str | None = None


class ErrorResponse(BaseModel):
    success: Literal[False] = False
    error: ErrorDetail
