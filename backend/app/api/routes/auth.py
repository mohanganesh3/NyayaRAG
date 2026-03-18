from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies.auth import AuthContext, get_optional_auth_context
from app.schemas.auth import AuthSessionData, AuthSessionResponse

router = APIRouter(tags=["auth"])
OptionalAuth = Annotated[AuthContext, Depends(get_optional_auth_context)]


@router.get("/auth/session", response_model=AuthSessionResponse)
def get_auth_session(auth: OptionalAuth) -> AuthSessionResponse:
    return AuthSessionResponse(
        data=AuthSessionData(
            is_authenticated=auth.is_authenticated,
            user_id=auth.user_id,
            session_id=auth.session_id,
            provider=auth.provider,
            display_name=auth.display_name,
        )
    )
