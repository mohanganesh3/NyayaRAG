from __future__ import annotations

from app.api.dependencies.auth import AuthContext
from app.models import QueryHistoryEntry
from sqlalchemy import select
from sqlalchemy.orm import Session


class QueryHistoryStore:
    def create_entry(
        self,
        session: Session,
        *,
        query_id: str,
        query_text: str,
        auth: AuthContext,
        workspace_id: str | None,
    ) -> QueryHistoryEntry:
        entry = QueryHistoryEntry(
            query_id=query_id,
            auth_user_id=auth.user_id,
            auth_session_id=auth.session_id,
            auth_provider=auth.provider,
            workspace_id=workspace_id,
            query_text=query_text,
            status="accepted",
        )
        session.add(entry)
        session.flush()
        return entry

    def mark_completed(
        self,
        session: Session,
        *,
        query_id: str,
        pipeline: str,
        answer_preview: str | None,
    ) -> QueryHistoryEntry | None:
        entry = self.get_by_query_id(session, query_id)
        if entry is None:
            return None

        entry.pipeline = pipeline
        entry.status = "completed"
        entry.answer_preview = answer_preview
        entry.error_message = None
        session.flush()
        return entry

    def mark_error(
        self,
        session: Session,
        *,
        query_id: str,
        pipeline: str | None,
        error_message: str,
    ) -> QueryHistoryEntry | None:
        entry = self.get_by_query_id(session, query_id)
        if entry is None:
            return None

        if pipeline is not None:
            entry.pipeline = pipeline
        entry.status = "error"
        entry.error_message = error_message
        session.flush()
        return entry

    def get_by_query_id(self, session: Session, query_id: str) -> QueryHistoryEntry | None:
        return session.scalar(
            select(QueryHistoryEntry).where(QueryHistoryEntry.query_id == query_id)
        )

    def list_for_user(
        self,
        session: Session,
        *,
        auth_user_id: str,
        limit: int = 20,
    ) -> list[QueryHistoryEntry]:
        statement = (
            select(QueryHistoryEntry)
            .where(QueryHistoryEntry.auth_user_id == auth_user_id)
            .order_by(QueryHistoryEntry.created_at.desc())
            .limit(limit)
        )
        return list(session.scalars(statement))

    def list_for_workspace(
        self,
        session: Session,
        *,
        auth_user_id: str,
        workspace_id: str,
        limit: int = 20,
    ) -> list[QueryHistoryEntry]:
        statement = (
            select(QueryHistoryEntry)
            .where(
                QueryHistoryEntry.auth_user_id == auth_user_id,
                QueryHistoryEntry.workspace_id == workspace_id,
            )
            .order_by(QueryHistoryEntry.created_at.desc())
            .limit(limit)
        )
        return list(session.scalars(statement))

query_history_store = QueryHistoryStore()
