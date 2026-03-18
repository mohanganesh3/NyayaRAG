from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONPayloadMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.legal import ApprovalStatus

if TYPE_CHECKING:
    from app.models.legal import LegalDocument


class SourceType(StrEnum):
    COURT_PORTAL = "court_portal"
    STATUTE_PORTAL = "statute_portal"
    API = "api"
    TRIBUNAL_PORTAL = "tribunal_portal"
    REPORTS_PORTAL = "reports_portal"
    USER_UPLOAD = "user_upload"
    OTHER = "other"


class IngestionRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"


class SourceRegistry(TimestampMixin, Base):
    __tablename__ = "source_registries"

    source_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, native_enum=False),
        nullable=False,
    )
    base_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    canonical_hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    jurisdiction_scope: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    update_frequency: Mapped[str | None] = mapped_column(String(100), nullable=True)
    access_method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, native_enum=False),
        nullable=False,
        default=ApprovalStatus.PENDING,
    )
    default_parser_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    documents: Mapped[list[LegalDocument]] = relationship(
        "LegalDocument",
        back_populates="source_registry",
    )
    ingestion_runs: Mapped[list[IngestionRun]] = relationship(
        "IngestionRun",
        back_populates="source_registry",
        cascade="all, delete-orphan",
    )


class IngestionRun(UUIDPrimaryKeyMixin, TimestampMixin, JSONPayloadMixin, Base):
    __tablename__ = "ingestion_runs"

    source_key: Mapped[str] = mapped_column(
        ForeignKey("source_registries.source_key", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[IngestionRunStatus] = mapped_column(
        Enum(IngestionRunStatus, native_enum=False),
        nullable=False,
        default=IngestionRunStatus.PENDING,
    )
    parser_version: Mapped[str] = mapped_column(String(50), nullable=False)
    triggered_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checksum_algorithm: Mapped[str] = mapped_column(String(30), nullable=False, default="sha256")
    source_snapshot_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, native_enum=False),
        nullable=False,
        default=ApprovalStatus.PENDING,
    )
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_registry: Mapped[SourceRegistry] = relationship(
        "SourceRegistry",
        back_populates="ingestion_runs",
    )
    documents: Mapped[list[LegalDocument]] = relationship(
        "LegalDocument",
        back_populates="ingestion_run",
    )
