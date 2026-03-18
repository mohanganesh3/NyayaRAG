from __future__ import annotations

from datetime import date as date_value

from pydantic import BaseModel, ConfigDict

from app.models import CriminalCode, CriminalCodeMappingStatus


class CriminalCodeReference(BaseModel):
    code: CriminalCode
    section: str


class CriminalCodeMappingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    legacy_code: CriminalCode
    legacy_section: str
    legacy_title: str | None = None
    new_code: CriminalCode
    new_section: str
    new_title: str | None = None
    mapping_status: CriminalCodeMappingStatus
    effective_from: date_value
    effective_until: date_value | None = None
    is_active: bool
    transition_note: str | None = None
    source_reference: str | None = None


class CriminalCodeResolutionRead(BaseModel):
    query_reference: CriminalCodeReference
    preferred_reference: CriminalCodeReference
    equivalent_reference: CriminalCodeReference | None = None
    mapping_status: CriminalCodeMappingStatus | None = None
    applies_new_code: bool
    reference_date: date_value
    cutover_date: date_value
    note: str | None = None
