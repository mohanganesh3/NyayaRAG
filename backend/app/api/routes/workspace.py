from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import AuthContext, require_auth_context
from app.db.session import get_db
from app.models import CaseContext
from app.schemas.legal import CaseContextRead
from app.schemas.query import QueryHistoryEntryRead
from app.schemas.workspace import (
    CaseContextResponse,
    SavedWorkspaceAnswerRead,
    WorkspaceListResponse,
    WorkspaceQueryHistoryResponse,
    WorkspaceSavedAnswerCreateRequest,
    WorkspaceSavedAnswerResponse,
    WorkspaceSavedAnswersResponse,
)
from app.services.case_contexts import case_context_builder
from app.services.query_history import query_history_store
from app.services.upload_ingestion import upload_ingestion_service
from app.services.workspaces import workspace_store

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


@router.get("/workspaces", response_model=WorkspaceListResponse)
def list_workspaces(db: DbSession, auth: RequiredAuth) -> WorkspaceListResponse:
    workspaces = workspace_store.list_for_user(session=db, auth_user_id=auth.user_id or "")
    return WorkspaceListResponse(
        data=[workspace_store.build_list_item(context) for context in workspaces]
    )


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


@router.get(
    "/workspace/{case_id}/saved-answers",
    response_model=WorkspaceSavedAnswersResponse,
)
def get_workspace_saved_answers(
    case_id: str,
    db: DbSession,
    auth: RequiredAuth,
) -> WorkspaceSavedAnswersResponse:
    _require_owned_workspace(db=db, case_id=case_id, auth=auth)
    saved_answers = workspace_store.list_saved_answers(
        session=db,
        auth_user_id=auth.user_id or "",
        workspace_id=case_id,
    )
    return WorkspaceSavedAnswersResponse(
        data=[
            SavedWorkspaceAnswerRead(
                id=answer.id,
                workspace_id=answer.workspace_id,
                auth_user_id=answer.auth_user_id,
                query_text=answer.query_text,
                overall_status=answer.overall_status,
                answer=answer.answer_payload,
                created_at=answer.created_at,
                updated_at=answer.updated_at,
            )
            for answer in saved_answers
        ]
    )


@router.post(
    "/workspace/{case_id}/saved-answers",
    response_model=WorkspaceSavedAnswerResponse,
)
def create_workspace_saved_answer(
    case_id: str,
    request: WorkspaceSavedAnswerCreateRequest,
    db: DbSession,
    auth: RequiredAuth,
) -> WorkspaceSavedAnswerResponse:
    _require_owned_workspace(db=db, case_id=case_id, auth=auth)
    saved_answer = workspace_store.save_answer(
        session=db,
        auth_user_id=auth.user_id or "",
        workspace_id=case_id,
        query_text=request.query_text,
        overall_status=request.overall_status,
        answer=request.answer,
    )
    db.commit()
    db.refresh(saved_answer)
    return WorkspaceSavedAnswerResponse(
        data=SavedWorkspaceAnswerRead(
            id=saved_answer.id,
            workspace_id=saved_answer.workspace_id,
            auth_user_id=saved_answer.auth_user_id,
            query_text=saved_answer.query_text,
            overall_status=saved_answer.overall_status,
            answer=saved_answer.answer_payload,
            created_at=saved_answer.created_at,
            updated_at=saved_answer.updated_at,
        )
    )


@router.post("/workspace/upload", response_model=CaseContextResponse)
async def upload_workspace_documents(
    db: DbSession,
    auth: RequiredAuth,
    files: Annotated[list[UploadFile], File(...)],
    case_id: Annotated[str | None, Form()] = None,
    court: Annotated[str | None, Form()] = None,
    case_number: Annotated[str | None, Form()] = None,
) -> CaseContextResponse:
    processed_documents = []

    for upload in files:
        content = await upload.read()
        try:
            processed = upload_ingestion_service.process_upload(
                file_name=upload.filename or "uploaded-document",
                content=content,
                media_type=upload.content_type,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "upload_processing_failed",
                    "message": str(exc),
                    "detail": {"file_name": upload.filename},
                },
            ) from exc
        processed_documents.append(processed)

    context = case_context_builder.build_from_uploads(
        db,
        processed_documents=processed_documents,
        case_id=case_id,
        court=court,
        case_number=case_number,
        owner_auth_user_id=auth.user_id,
        owner_display_name=auth.display_name,
        auth_provider=auth.provider,
    )
    db.commit()
    db.refresh(context)
    return CaseContextResponse(data=CaseContextRead.model_validate(context))
