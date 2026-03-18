from __future__ import annotations

from collections.abc import Sequence
from datetime import date as date_value

from app.models import (
    CRIMINAL_CODE_CUTOVER,
    CriminalCode,
    CriminalCodeMapping,
    CriminalCodeMappingStatus,
)
from app.schemas.criminal_codes import (
    CriminalCodeMappingRead,
    CriminalCodeReference,
    CriminalCodeResolutionRead,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

_CODE_ALIASES: dict[str, CriminalCode] = {
    "indian evidence act": CriminalCode.EVIDENCE_ACT,
    "evidence act": CriminalCode.EVIDENCE_ACT,
    "crpc": CriminalCode.CRPC,
    "code of criminal procedure": CriminalCode.CRPC,
    "ipc": CriminalCode.IPC,
    "indian penal code": CriminalCode.IPC,
    "bns": CriminalCode.BNS,
    "bnss": CriminalCode.BNSS,
    "bsa": CriminalCode.BSA,
}

_DISPLAY_CODES: dict[CriminalCode, str] = {
    CriminalCode.IPC: "IPC",
    CriminalCode.CRPC: "CrPC",
    CriminalCode.EVIDENCE_ACT: "Indian Evidence Act",
    CriminalCode.BNS: "BNS",
    CriminalCode.BNSS: "BNSS",
    CriminalCode.BSA: "BSA",
}

_LEGACY_CODES = {
    CriminalCode.IPC,
    CriminalCode.CRPC,
    CriminalCode.EVIDENCE_ACT,
}
_NEW_CODES = {
    CriminalCode.BNS,
    CriminalCode.BNSS,
    CriminalCode.BSA,
}


class CriminalCodeMappingResolver:
    def __init__(self, cutover_date: date_value = CRIMINAL_CODE_CUTOVER) -> None:
        self.cutover_date = cutover_date

    def upsert_mapping(
        self,
        session: Session,
        *,
        legacy_code: CriminalCode,
        legacy_section: str,
        new_code: CriminalCode,
        new_section: str,
        mapping_status: CriminalCodeMappingStatus = CriminalCodeMappingStatus.DIRECT,
        legacy_title: str | None = None,
        new_title: str | None = None,
        effective_from: date_value = CRIMINAL_CODE_CUTOVER,
        effective_until: date_value | None = None,
        is_active: bool = True,
        transition_note: str | None = None,
        source_reference: str | None = None,
    ) -> CriminalCodeMapping:
        existing = session.scalar(
            select(CriminalCodeMapping).where(
                CriminalCodeMapping.legacy_code == legacy_code,
                CriminalCodeMapping.legacy_section == legacy_section.upper(),
                CriminalCodeMapping.new_code == new_code,
                CriminalCodeMapping.new_section == new_section.upper(),
            )
        )

        if existing is None:
            existing = CriminalCodeMapping(
                legacy_code=legacy_code,
                legacy_section=legacy_section.upper(),
                new_code=new_code,
                new_section=new_section.upper(),
            )
            session.add(existing)

        existing.legacy_title = legacy_title
        existing.new_title = new_title
        existing.mapping_status = mapping_status
        existing.effective_from = effective_from
        existing.effective_until = effective_until
        existing.is_active = is_active
        existing.transition_note = transition_note
        existing.source_reference = source_reference
        session.flush()
        return existing

    def resolve_reference(
        self,
        session: Session,
        reference: str | CriminalCodeReference,
        *,
        reference_date: date_value | None = None,
    ) -> CriminalCodeResolutionRead:
        parsed = self.parse_reference(reference)
        effective_date = reference_date or self.cutover_date
        applies_new_code = effective_date >= self.cutover_date

        mapping = self._find_mapping(session, parsed)
        if mapping is None:
            return CriminalCodeResolutionRead(
                query_reference=parsed,
                preferred_reference=parsed,
                equivalent_reference=None,
                mapping_status=None,
                applies_new_code=applies_new_code,
                reference_date=effective_date,
                cutover_date=self.cutover_date,
                note="No stored criminal-code transition mapping found for this reference.",
            )

        preferred = self._preferred_reference(parsed, mapping, applies_new_code)
        equivalent = self._equivalent_reference(mapping, preferred)
        return CriminalCodeResolutionRead(
            query_reference=parsed,
            preferred_reference=preferred,
            equivalent_reference=equivalent,
            mapping_status=mapping.mapping_status,
            applies_new_code=applies_new_code,
            reference_date=effective_date,
            cutover_date=self.cutover_date,
            note=mapping.transition_note,
        )

    def expand_references_for_query(
        self,
        session: Session,
        references: Sequence[str | CriminalCodeReference],
        *,
        reference_date: date_value | None = None,
    ) -> list[str]:
        expanded: list[str] = []
        seen: set[str] = set()

        for reference in references:
            resolution = self.resolve_reference(
                session,
                reference,
                reference_date=reference_date,
            )
            for candidate in (
                resolution.preferred_reference,
                resolution.equivalent_reference,
            ):
                if candidate is None:
                    continue
                formatted = self.format_reference(candidate)
                if formatted not in seen:
                    seen.add(formatted)
                    expanded.append(formatted)

        return expanded

    def parse_reference(self, reference: str | CriminalCodeReference) -> CriminalCodeReference:
        if isinstance(reference, CriminalCodeReference):
            return reference

        normalized = " ".join(reference.replace("Section", "").replace("section", "").split())
        lowered = normalized.lower()

        aliases = sorted(
            _CODE_ALIASES.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        )
        for alias, code in aliases:
            if lowered.startswith(f"{alias} "):
                section = normalized[len(alias) :].strip().upper()
                return CriminalCodeReference(code=code, section=section)

        raise ValueError(f"Unsupported criminal code reference: {reference}")

    def format_reference(self, reference: CriminalCodeReference) -> str:
        return f"{_DISPLAY_CODES[reference.code]} {reference.section}"

    def get_mapping_read(
        self,
        session: Session,
        reference: str | CriminalCodeReference,
    ) -> CriminalCodeMappingRead | None:
        parsed = self.parse_reference(reference)
        mapping = self._find_mapping(session, parsed)
        if mapping is None:
            return None
        return CriminalCodeMappingRead.model_validate(mapping)

    def _find_mapping(
        self,
        session: Session,
        reference: CriminalCodeReference,
    ) -> CriminalCodeMapping | None:
        if reference.code in _LEGACY_CODES:
            return session.scalar(
                select(CriminalCodeMapping).where(
                    CriminalCodeMapping.legacy_code == reference.code,
                    CriminalCodeMapping.legacy_section == reference.section,
                    CriminalCodeMapping.is_active.is_(True),
                )
            )

        if reference.code in _NEW_CODES:
            return session.scalar(
                select(CriminalCodeMapping).where(
                    CriminalCodeMapping.new_code == reference.code,
                    CriminalCodeMapping.new_section == reference.section,
                    CriminalCodeMapping.is_active.is_(True),
                )
            )

        return None

    def _preferred_reference(
        self,
        parsed: CriminalCodeReference,
        mapping: CriminalCodeMapping,
        applies_new_code: bool,
    ) -> CriminalCodeReference:
        if parsed.code in _LEGACY_CODES:
            if applies_new_code:
                return CriminalCodeReference(
                    code=mapping.new_code,
                    section=mapping.new_section,
                )
            return parsed

        if parsed.code in _NEW_CODES and not applies_new_code:
            return CriminalCodeReference(
                code=mapping.legacy_code,
                section=mapping.legacy_section,
            )

        return parsed

    def _equivalent_reference(
        self,
        mapping: CriminalCodeMapping,
        preferred: CriminalCodeReference,
    ) -> CriminalCodeReference | None:
        candidates = (
            CriminalCodeReference(code=mapping.legacy_code, section=mapping.legacy_section),
            CriminalCodeReference(code=mapping.new_code, section=mapping.new_section),
        )
        for candidate in candidates:
            if candidate != preferred:
                return candidate
        return None
