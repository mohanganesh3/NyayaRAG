from __future__ import annotations

from app.models import CaseContext, SavedWorkspaceAnswer
from app.schemas.workspace import WorkspaceListItemRead
from sqlalchemy import select
from sqlalchemy.orm import Session


class WorkspaceStore:
    def list_for_user(
        self,
        session: Session,
        *,
        auth_user_id: str,
        limit: int = 25,
    ) -> list[CaseContext]:
        statement = (
            select(CaseContext)
            .where(CaseContext.owner_auth_user_id == auth_user_id)
            .order_by(CaseContext.updated_at.desc(), CaseContext.created_at.desc())
            .limit(limit)
        )
        return list(session.scalars(statement))

    def save_answer(
        self,
        session: Session,
        *,
        auth_user_id: str,
        workspace_id: str,
        query_text: str,
        overall_status: str,
        answer: dict[str, object],
    ) -> SavedWorkspaceAnswer:
        saved_answer = SavedWorkspaceAnswer(
            workspace_id=workspace_id,
            auth_user_id=auth_user_id,
            query_text=query_text,
            overall_status=overall_status,
            answer_payload=answer,
        )
        session.add(saved_answer)
        session.flush()
        return saved_answer

    def list_saved_answers(
        self,
        session: Session,
        *,
        auth_user_id: str,
        workspace_id: str,
        limit: int = 20,
    ) -> list[SavedWorkspaceAnswer]:
        statement = (
            select(SavedWorkspaceAnswer)
            .where(
                SavedWorkspaceAnswer.auth_user_id == auth_user_id,
                SavedWorkspaceAnswer.workspace_id == workspace_id,
            )
            .order_by(SavedWorkspaceAnswer.created_at.desc())
            .limit(limit)
        )
        return list(session.scalars(statement))

    def build_list_item(self, context: CaseContext) -> WorkspaceListItemRead:
        return WorkspaceListItemRead(
            case_id=context.case_id,
            appellant_petitioner=context.appellant_petitioner,
            respondent_opposite_party=context.respondent_opposite_party,
            court=context.court,
            case_number=context.case_number,
            stage=context.stage.value if context.stage is not None else None,
            case_type=context.case_type.value if context.case_type is not None else None,
            uploaded_doc_count=len(context.uploaded_docs),
            updated_at=context.updated_at,
        )


workspace_store = WorkspaceStore()
