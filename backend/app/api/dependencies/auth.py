from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status


@dataclass(frozen=True, slots=True)
class AuthContext:
    user_id: str | None
    session_id: str | None
    provider: str | None
    display_name: str | None
    is_authenticated: bool


def get_optional_auth_context(
    clerk_user_id: Annotated[str | None, Header(alias="X-Clerk-User-Id")] = None,
    clerk_session_id: Annotated[str | None, Header(alias="X-Clerk-Session-Id")] = None,
    clerk_display_name: Annotated[str | None, Header(alias="X-Clerk-Display-Name")] = None,
    dev_user_id: Annotated[str | None, Header(alias="X-Nyayarag-Dev-User-Id")] = None,
) -> AuthContext:
    if clerk_user_id:
        return AuthContext(
            user_id=clerk_user_id,
            session_id=clerk_session_id,
            provider="clerk",
            display_name=clerk_display_name,
            is_authenticated=True,
        )

    if dev_user_id:
        return AuthContext(
            user_id=dev_user_id,
            session_id=None,
            provider="dev_header",
            display_name=dev_user_id,
            is_authenticated=True,
        )

    return AuthContext(
        user_id=None,
        session_id=None,
        provider=None,
        display_name=None,
        is_authenticated=False,
    )


def require_auth_context(
    auth: Annotated[AuthContext, Depends(get_optional_auth_context)],
) -> AuthContext:
    if auth.is_authenticated:
        return auth

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "auth_required",
            "message": "Authentication is required for this workspace action.",
        },
    )
