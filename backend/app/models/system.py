from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONPayloadMixin, TimestampMixin, UUIDPrimaryKeyMixin


class RuntimeSetting(TimestampMixin, Base):
    __tablename__ = "runtime_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(String(2000), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)


class BackgroundTaskRun(UUIDPrimaryKeyMixin, TimestampMixin, JSONPayloadMixin, Base):
    __tablename__ = "background_task_runs"

    task_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    queue_name: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    result: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)


class QueryHistoryEntry(UUIDPrimaryKeyMixin, TimestampMixin, JSONPayloadMixin, Base):
    __tablename__ = "query_history_entries"

    query_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    auth_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    auth_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    auth_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    query_text: Mapped[str] = mapped_column(String(4000), nullable=False)
    pipeline: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="accepted", index=True)
    answer_preview: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class SavedWorkspaceAnswer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "saved_workspace_answers"

    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    auth_user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    query_text: Mapped[str] = mapped_column(String(4000), nullable=False)
    overall_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    answer_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
