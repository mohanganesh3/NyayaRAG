from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from datetime import date as date_value
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    BackgroundTaskRun,
    CitationEdge,
    DocumentChunk,
    LegalDocument,
    StatuteAmendment,
    StatuteSection,
    ValidityStatus,
)


@dataclass(slots=True)
class StatuteSectionUpdate:
    section_number: str
    updated_text: str | None = None
    amendment_label: str | None = None
    amendment_date: date_value | None = None
    effective_date: date_value | None = None
    summary: str | None = None
    is_in_force: bool | None = None
    corresponding_new_section: str | None = None
    punishment: str | None = None


@dataclass(slots=True)
class StatuteValidityUpdate:
    doc_id: str
    current_validity: bool
    replaced_by: str | None = None
    replaced_on: date_value | None = None
    sections: list[StatuteSectionUpdate] = field(default_factory=list)


@dataclass(slots=True)
class JudgmentValidityUpdate:
    target_doc_id: str
    new_validity: ValidityStatus
    authority_doc_id: str | None = None
    authority_date: date_value | None = None
    note: str | None = None


@dataclass(slots=True)
class ValidityEngineReport:
    statute_updates_applied: int = 0
    judgment_updates_applied: int = 0
    stale_document_ids: list[str] = field(default_factory=list)
    stale_chunk_ids: list[str] = field(default_factory=list)
    reembedding_chunk_ids: list[str] = field(default_factory=list)
    background_task_run_id: str | None = None

    def to_result_payload(self) -> dict[str, object]:
        return {
            "statute_updates_applied": self.statute_updates_applied,
            "judgment_updates_applied": self.judgment_updates_applied,
            "stale_document_ids": self.stale_document_ids,
            "stale_chunk_ids": self.stale_chunk_ids,
            "reembedding_chunk_ids": self.reembedding_chunk_ids,
            "background_task_run_id": self.background_task_run_id,
        }


class DailyValidityEngine:
    def run(
        self,
        session: Session,
        *,
        statute_updates: list[StatuteValidityUpdate] | None = None,
        judgment_updates: list[JudgmentValidityUpdate] | None = None,
        task_name: str = "daily_validity_engine",
    ) -> ValidityEngineReport:
        report = ValidityEngineReport()
        task_run = BackgroundTaskRun(
            task_name=task_name,
            queue_name="maintenance",
            status="running",
            payload={
                "statute_updates_requested": len(statute_updates or []),
                "judgment_updates_requested": len(judgment_updates or []),
            },
        )
        session.add(task_run)
        session.flush()
        report.background_task_run_id = task_run.id

        try:
            for statute_update in statute_updates or []:
                self.apply_statute_update(session, statute_update, report=report)
            for judgment_update in judgment_updates or []:
                self.apply_judgment_update(session, judgment_update, report=report)

            task_run.status = "succeeded"
            task_run.result = report.to_result_payload()
            session.flush()
            return report
        except Exception as exc:
            task_run.status = "failed"
            task_run.result = {
                "error": str(exc),
                "background_task_run_id": task_run.id,
            }
            session.flush()
            raise

    def apply_statute_update(
        self,
        session: Session,
        update: StatuteValidityUpdate,
        *,
        report: ValidityEngineReport,
    ) -> None:
        document = session.get(LegalDocument, update.doc_id)
        if document is None or document.statute_document is None:
            raise ValueError(f"Unknown statute document: {update.doc_id}")

        statute_document = document.statute_document
        document.validity_checked_at = datetime.now(UTC)
        statute_document.current_validity = update.current_validity
        statute_document.replaced_by = update.replaced_by
        statute_document.replaced_on = update.replaced_on

        if not update.current_validity:
            document.current_validity = ValidityStatus.REPEALED
            self._mark_document_stale(
                document,
                reason=(
                    f"Statute repealed. Replacement: {update.replaced_by or 'not specified'}"
                ),
                report=report,
                needs_reembedding=False,
            )

        amended = False
        for section_update in update.sections:
            section = self._get_section(statute_document.sections, section_update.section_number)
            if section is None:
                raise ValueError(
                    f"Unknown section {section_update.section_number} for statute {update.doc_id}"
                )

            section_changed = False
            previous_text = section.text

            if (
                section_update.updated_text is not None
                and section_update.updated_text != section.text
            ):
                if section.original_text is None:
                    section.original_text = section.text
                section.text = section_update.updated_text
                section_changed = True

            if (
                section_update.is_in_force is not None
                and section_update.is_in_force != section.is_in_force
            ):
                section.is_in_force = section_update.is_in_force
                section_changed = True

            if (
                section_update.corresponding_new_section is not None
                and section_update.corresponding_new_section != section.corresponding_new_section
            ):
                section.corresponding_new_section = section_update.corresponding_new_section
                section_changed = True

            if (
                section_update.punishment is not None
                and section_update.punishment != section.punishment
            ):
                section.punishment = section_update.punishment
                section_changed = True

            if section_changed or section_update.amendment_label:
                amended = True
                self._upsert_amendment(section, section_update, previous_text)
                self._mark_document_stale(
                    document,
                    reason=f"Section {section.section_number} amended.",
                    report=report,
                    needs_reembedding=True,
                    section_number=section.section_number,
                )
                for case_doc_id in section.cases_interpreting:
                    case_document = session.get(LegalDocument, case_doc_id)
                    if case_document is None:
                        continue
                    self._mark_document_stale(
                        case_document,
                        reason=(
                            "Interpreted statute text changed for "
                            f"section {section.section_number}."
                        ),
                        report=report,
                        needs_reembedding=True,
                    )

        statute_document.current_sections_in_force = [
            section.section_number
            for section in statute_document.sections
            if section.is_in_force
        ]

        if update.current_validity and amended:
            document.current_validity = ValidityStatus.AMENDED
        elif update.current_validity and document.current_validity is ValidityStatus.REPEALED:
            document.current_validity = ValidityStatus.GOOD_LAW

        report.statute_updates_applied += 1
        session.flush()

    def apply_judgment_update(
        self,
        session: Session,
        update: JudgmentValidityUpdate,
        *,
        report: ValidityEngineReport,
    ) -> None:
        target_document = session.get(LegalDocument, update.target_doc_id)
        if target_document is None:
            raise ValueError(f"Unknown judgment document: {update.target_doc_id}")

        target_document.current_validity = update.new_validity
        target_document.overruled_by = update.authority_doc_id
        target_document.overruled_date = update.authority_date
        target_document.validity_checked_at = datetime.now(UTC)
        self._mark_document_stale(
            target_document,
            reason=update.note or f"Judgment validity updated to {update.new_validity.value}.",
            report=report,
            needs_reembedding=False,
        )

        citing_doc_ids = session.scalars(
            select(CitationEdge.source_doc_id).where(
                CitationEdge.target_doc_id == update.target_doc_id
            )
        ).all()
        for citing_doc_id in citing_doc_ids:
            citing_document = session.get(LegalDocument, citing_doc_id)
            if citing_document is None:
                continue
            self._mark_document_stale(
                citing_document,
                reason=(
                    f"Cites judgment {update.target_doc_id} whose validity changed to "
                    f"{update.new_validity.value}."
                ),
                report=report,
                needs_reembedding=False,
            )

        report.judgment_updates_applied += 1
        session.flush()

    def _mark_document_stale(
        self,
        document: LegalDocument,
        *,
        reason: str,
        report: ValidityEngineReport,
        needs_reembedding: bool,
        section_number: str | None = None,
    ) -> None:
        document.projection_stale = True
        document.stale_reason = reason
        document.validity_checked_at = datetime.now(UTC)
        report.stale_document_ids = self._append_unique(report.stale_document_ids, document.doc_id)

        for chunk in document.chunks:
            if section_number is not None and chunk.section_number != section_number:
                continue
            self._mark_chunk_stale(
                chunk,
                reason=reason,
                report=report,
                needs_reembedding=needs_reembedding,
            )

    def _mark_chunk_stale(
        self,
        chunk: DocumentChunk,
        *,
        reason: str,
        report: ValidityEngineReport,
        needs_reembedding: bool,
    ) -> None:
        chunk.projection_stale = True
        chunk.stale_reason = reason
        chunk.last_validated_at = datetime.now(UTC)
        report.stale_chunk_ids = self._append_unique(report.stale_chunk_ids, chunk.chunk_id)

        if needs_reembedding:
            chunk.needs_reembedding = True
            report.reembedding_chunk_ids = self._append_unique(
                report.reembedding_chunk_ids,
                chunk.chunk_id,
            )

    def _upsert_amendment(
        self,
        section: StatuteSection,
        update: StatuteSectionUpdate,
        previous_text: str,
    ) -> None:
        if update.amendment_label is None:
            return

        amendment_id = str(
            uuid5(
                NAMESPACE_URL,
                (
                    f"{section.id}|{update.amendment_label}|"
                    f"{update.effective_date.isoformat() if update.effective_date else 'none'}"
                ),
            )
        )
        amendment = next((item for item in section.amendments if item.id == amendment_id), None)
        if amendment is None:
            amendment = StatuteAmendment(id=amendment_id)
            section.amendments.append(amendment)

        amendment.amendment_label = update.amendment_label
        amendment.amendment_date = update.amendment_date
        amendment.effective_date = update.effective_date
        amendment.summary = update.summary
        amendment.previous_text = previous_text
        amendment.updated_text = update.updated_text or section.text

    def _get_section(
        self,
        sections: list[StatuteSection],
        section_number: str,
    ) -> StatuteSection | None:
        for section in sections:
            if section.section_number == section_number:
                return section
        return None

    def _append_unique(self, items: list[str], value: str) -> list[str]:
        if value not in items:
            return [*items, value]
        return items
