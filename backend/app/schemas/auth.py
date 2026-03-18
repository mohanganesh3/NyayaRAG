from typing import Literal

from pydantic import BaseModel


class AuthSessionData(BaseModel):
    is_authenticated: bool
    user_id: str | None = None
    session_id: str | None = None
    provider: str | None = None
    display_name: str | None = None


class AuthSessionResponse(BaseModel):
    success: Literal[True] = True
    data: AuthSessionData
