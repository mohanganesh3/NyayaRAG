from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import AuthContext, require_auth_context
from app.db.session import get_db
from app.models import CaseContext
from app.schemas.legal import CaseContextRead
from app.schemas.query import QueryHistoryEntryRead
from app.schemas.workspace import CaseContextResponse, WorkspaceQueryHistoryResponse
from app.services.case_contexts import case_context_builder
from app.services.query_history import query_history_store

router = APIRouter(tags=["workspace"])
DbSession = Annotated[Session, Depends(get_db)]
RequiredAuth = Annotated[AuthContext, Depends(require_auth_context)]

def _require_owned_workspace(*, db: Session, case_id: str, auth: AuthContext) -> CaseContext:
    context = case_context_builder.get(db, case_id)
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "workspace_not_found",
                "message": f"No persisted case context exists for '{case_id}'.",
                "detail": {"case_id": case_id},
            },
        )

    if context.owner_auth_user_id != auth.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "workspace_forbidden",
                "message": "This workspace belongs to a different authenticated user.",
                "detail": {"case_id": case_id},
            },
        )

    return context


@router.get("/workspace/{case_id}", response_model=CaseContextResponse)
def get_workspace(case_id: str, db: DbSession, auth: RequiredAuth) -> CaseContextResponse:
    context = _require_owned_workspace(db=db, case_id=case_id, auth=auth)
    return CaseContextResponse(data=CaseContextRead.model_validate(context))


@router.get("/workspace/{case_id}/history", response_model=WorkspaceQueryHistoryResponse)
def get_workspace_history(
    case_id: str,
    db: DbSession,
    auth: RequiredAuth,
) -> WorkspaceQueryHistoryResponse:
    _require_owned_workspace(db=db, case_id=case_id, auth=auth)
    entries = query_history_store.list_for_workspace(
        session=db,
        auth_user_id=auth.user_id or "",
        workspace_id=case_id,
    )
    return WorkspaceQueryHistoryResponse(
        data=[QueryHistoryEntryRead.model_validate(entry) for entry in entries]
    )
