from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.legal import CaseContextRead
from app.schemas.workspace import CaseContextResponse
from app.services.case_contexts import case_context_builder

router = APIRouter(tags=["workspace"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/workspace/{case_id}", response_model=CaseContextResponse)
def get_workspace(case_id: str, db: DbSession) -> CaseContextResponse:
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

    return CaseContextResponse(data=CaseContextRead.model_validate(context))
