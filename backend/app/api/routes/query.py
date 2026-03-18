from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies.auth import (
    AuthContext,
    get_optional_auth_context,
    require_auth_context,
)
from app.db.session import get_db
from app.models import CaseContext
from app.schemas.query import (
    QueryAcceptedResponse,
    QueryHistoryEntryRead,
    QueryHistoryResponse,
    QuerySubmissionRequest,
)
from app.services.billing import billing_store
from app.services.query_history import query_history_store
from app.services.query_runtime import query_runtime

router = APIRouter(tags=["query"])
DbSession = Annotated[Session, Depends(get_db)]
OptionalAuth = Annotated[AuthContext, Depends(get_optional_auth_context)]
RequiredAuth = Annotated[AuthContext, Depends(require_auth_context)]


def _require_owned_workspace(
    *,
    db: Session,
    workspace_id: str,
    auth: AuthContext,
) -> CaseContext:
    workspace = db.get(CaseContext, workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "workspace_not_found",
                "message": f"No persisted case context exists for '{workspace_id}'.",
                "detail": {"case_id": workspace_id},
            },
        )

    if workspace.owner_auth_user_id != auth.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "workspace_forbidden",
                "message": "This workspace belongs to a different authenticated user.",
                "detail": {"case_id": workspace_id},
            },
        )

    return workspace


@router.post("/query", status_code=status.HTTP_202_ACCEPTED, response_model=QueryAcceptedResponse)
def submit_query(
    request: QuerySubmissionRequest,
    db: DbSession,
    auth: OptionalAuth,
) -> QueryAcceptedResponse:
    allowance = billing_store.evaluate_query_allowance(
        db,
        auth_user_id=auth.user_id if auth.is_authenticated else None,
        workspace_id=request.workspace_id,
    )
    if not allowance.allowed:
        raise HTTPException(
            status_code=allowance.status_code or status.HTTP_403_FORBIDDEN,
            detail={
                "code": allowance.code or "billing_rejected",
                "message": allowance.message or "This request is blocked by billing policy.",
                "detail": allowance.detail,
            },
        )

    if request.workspace_id is not None:
        if not auth.is_authenticated:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "auth_required",
                    "message": "Authentication is required for workspace-scoped queries.",
                },
            )
        _require_owned_workspace(db=db, workspace_id=request.workspace_id, auth=auth)

    record = query_runtime.create_query(
        request.query,
        workspace_id=request.workspace_id,
        auth=auth,
    )
    return QueryAcceptedResponse(data=query_runtime.build_acceptance(record))


@router.get("/query/{query_id}/stream")
async def stream_query(
    query_id: str,
    auth: OptionalAuth,
    access_token: str | None = None,
) -> StreamingResponse:
    record = query_runtime.get_query(query_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "query_not_found",
                "message": f"Query '{query_id}' does not exist.",
                "detail": {"query_id": query_id},
            },
        )
    if record.auth_user_id is not None:
        if access_token is not None and access_token == record.access_token:
            auth = AuthContext(
                user_id=record.auth_user_id,
                session_id=record.auth_session_id,
                provider=record.auth_provider,
                display_name=None,
                is_authenticated=True,
            )
        if not auth.is_authenticated:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "auth_required",
                    "message": "Authentication is required to stream this query.",
                    "detail": {"query_id": query_id},
                },
            )
        if auth.user_id != record.auth_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "query_forbidden",
                    "message": "This query belongs to a different authenticated session.",
                    "detail": {"query_id": query_id},
                },
            )

    async def event_generator() -> AsyncIterator[str]:
        events = await query_runtime.stream_query_events(query_id)
        for event in events:
            yield f"data: {event.model_dump_json()}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/query/history", response_model=QueryHistoryResponse)
def list_query_history(db: DbSession, auth: RequiredAuth) -> QueryHistoryResponse:
    entries = query_history_store.list_for_user(session=db, auth_user_id=auth.user_id or "")
    return QueryHistoryResponse(
        data=[QueryHistoryEntryRead.model_validate(entry) for entry in entries]
    )
