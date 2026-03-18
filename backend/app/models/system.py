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

