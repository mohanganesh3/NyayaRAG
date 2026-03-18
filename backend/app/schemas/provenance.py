from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import ApprovalStatus, IngestionRunStatus, SourceType


class SourceRegistryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_key: str
    display_name: str
    source_type: SourceType
    base_url: str | None = None
    canonical_hostname: str | None = None
    jurisdiction_scope: list[str]
    update_frequency: str | None = None
    access_method: str | None = None
    is_public: bool
    is_active: bool
    approval_status: ApprovalStatus
    default_parser_version: str | None = None
    notes: str | None = None


class IngestionRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_key: str
    status: IngestionRunStatus
    parser_version: str
    triggered_by: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    document_count: int
    new_document_count: int
    updated_document_count: int
    failed_document_count: int
    checksum_algorithm: str
    source_snapshot_url: str | None = None
    approval_status: ApprovalStatus
    error_summary: str | None = None
    payload: dict[str, object] | None = None
