# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, date as date_value, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

REPO_ROOT = Path(__file__).resolve().parents[4]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import Session

from app.db.base import Base  # noqa: E402
from app.db.session import build_engine  # noqa: E402
from app.models import (  # noqa: E402
    ApprovalStatus,
    DocumentChunk,
    IngestionRun,
    IngestionRunStatus,
    LegalDocument,
    LegalDocumentType,
    SourceRegistry,
    StatuteAmendment,
    StatuteDocument,
    StatuteSection,
    SourceType,
    ValidityStatus,
)

STAGING_DIR = REPO_ROOT / "data" / "collection" / "staging"
SUMMARY_PATH = REPO_ROOT / "data" / "collection" / "india_code_merge_summary.json"
DEFAULT_DATABASE_URL = f"sqlite+pysqlite:///{REPO_ROOT / 'data' / 'collection' / 'live_corpus.db'}"
SOURCE_KEY = "india_code"
PARSER_VERSION = "india-code-merge-v1"


@dataclass(slots=True)
class FileResult:
    path: str
    status: str
    doc_id: str | None = None
    source_document_ref: str | None = None
    sections: int = 0
    chunks: int = 0
    amendments: int = 0
    error: str | None = None


@dataclass(slots=True)
class MergeSummary:
    run_id: str | None
    started_at: str
    completed_at: str
    staging_dir: str
    staging_files_found: int
    staging_files_processed: int = 0
    documents_inserted: int = 0
    documents_updated: int = 0
    documents_failed: int = 0
    sections_upserted: int = 0
    chunks_upserted: int = 0
    amendments_upserted: int = 0
    file_results: list[FileResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "staging_dir": self.staging_dir,
            "staging_files_found": self.staging_files_found,
            "staging_files_processed": self.staging_files_processed,
            "documents_inserted": self.documents_inserted,
            "documents_updated": self.documents_updated,
            "documents_failed": self.documents_failed,
            "sections_upserted": self.sections_upserted,
            "chunks_upserted": self.chunks_upserted,
            "amendments_upserted": self.amendments_upserted,
            "file_results": [asdict(result) for result in self.file_results],
            "notes": self.notes,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge India Code staging files into SQLite.")
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    parser.add_argument("--staging-dir", type=Path, default=STAGING_DIR)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    args = parser.parse_args(argv)

    started_at = datetime.now(UTC)
    engine = build_engine(args.database_url)
    Base.metadata.create_all(engine)

    staging_paths = sorted(args.staging_dir.glob("act_*.json")) if args.staging_dir.exists() else []
    summary = MergeSummary(
        run_id=None,
        started_at=started_at.isoformat(),
        completed_at=started_at.isoformat(),
        staging_dir=str(args.staging_dir.resolve()),
        staging_files_found=len(staging_paths),
    )

    if not staging_paths:
        summary.notes.append("No staging files found.")
        _write_summary(args.summary_path, summary)
        print(json.dumps(summary.to_dict(), indent=2, sort_keys=True))
        return 0

    with Session(engine) as session:
        run = _create_merge_run(session)
        summary.run_id = run.id
        session.flush()

        try:
            for path in staging_paths:
                summary.staging_files_processed += 1
                try:
                    result = _merge_staging_file(session, run, path)
                except Exception as exc:  # noqa: BLE001
                    summary.documents_failed += 1
                    summary.file_results.append(
                        FileResult(
                            path=str(path),
                            status="failed",
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    )
                    continue

                summary.file_results.append(result)
                if result.status == "inserted":
                    summary.documents_inserted += 1
                else:
                    summary.documents_updated += 1
                summary.sections_upserted += result.sections
                summary.chunks_upserted += result.chunks
                summary.amendments_upserted += result.amendments

            run.status = (
                IngestionRunStatus.SUCCEEDED
                if summary.documents_failed == 0
                else IngestionRunStatus.PARTIAL
            )
            run.completed_at = datetime.now(UTC)
            run.document_count = summary.staging_files_processed
            run.new_document_count = summary.documents_inserted
            run.updated_document_count = summary.documents_updated
            run.failed_document_count = summary.documents_failed
            run.error_summary = (
                None
                if summary.documents_failed == 0
                else f"{summary.documents_failed} staging files failed during India Code merge."
            )
            session.commit()
        except Exception:
            session.rollback()
            raise

    summary.completed_at = datetime.now(UTC).isoformat()
    _write_summary(args.summary_path, summary)
    print(json.dumps(summary.to_dict(), indent=2, sort_keys=True))
    return 0


def _create_merge_run(session: Session) -> IngestionRun:
    registry = _ensure_source_registry(session)
    run = IngestionRun(
        source_registry=registry,
        status=IngestionRunStatus.RUNNING,
        parser_version=PARSER_VERSION,
        triggered_by="merge_india_code_staging",
        started_at=datetime.now(UTC),
        checksum_algorithm="sha256",
        source_snapshot_url=str(STAGING_DIR.resolve()),
        approval_status=registry.approval_status,
    )
    session.add(run)
    session.flush()
    return run


def _ensure_source_registry(session: Session) -> SourceRegistry:
    registry = session.get(SourceRegistry, SOURCE_KEY)
    if registry is not None:
        return registry

    registry = SourceRegistry(
        source_key=SOURCE_KEY,
        display_name="India Code Central Acts",
        source_type=SourceType.STATUTE_PORTAL,
        base_url="https://www.indiacode.nic.in",
        canonical_hostname="www.indiacode.nic.in",
        jurisdiction_scope=["All India"],
        update_frequency="daily",
        access_method="structured_text",
        is_public=True,
        is_active=True,
        approval_status=ApprovalStatus.APPROVED,
        default_parser_version=PARSER_VERSION,
        notes="Merged from India Code staging JSON.",
    )
    session.add(registry)
    session.flush()
    return registry


def _merge_staging_file(session: Session, run: IngestionRun, path: Path) -> FileResult:
    record = json.loads(path.read_text(encoding="utf-8"))
    handle = _as_str(record.get("handle")) or path.stem.removeprefix("act_")
    act_number = _as_str(record.get("act_number"))
    year = _as_str(record.get("year"))
    title = _as_str(record.get("title")) or _as_str(record.get("act_name")) or handle
    source_document_ref = handle or _dedupe_key(act_number, year, title)
    doc_id = str(uuid5(NAMESPACE_URL, f"{SOURCE_KEY}|{source_document_ref}"))

    legal_document = session.get(LegalDocument, doc_id)
    inserted = legal_document is None
    if legal_document is None:
        legal_document = LegalDocument(doc_id=doc_id, doc_type=LegalDocumentType.STATUTE)
        session.add(legal_document)
        session.flush()

    statute_document = legal_document.statute_document
    if statute_document is None:
        statute_document = StatuteDocument(doc_id=doc_id, act_name=title, jurisdiction="Central")
        legal_document.statute_document = statute_document

    sections_payload = _dedupe_sections_payload(_as_list(record.get("sections")))
    section_texts = []
    section_count = 0
    amendment_count = 0

    legal_document.doc_type = LegalDocumentType.STATUTE
    legal_document.court = None
    legal_document.bench = []
    legal_document.coram = None
    legal_document.date = _parse_date(record.get("enactment_date") or record.get("date"))
    legal_document.citation = _as_str(record.get("act_number")) or title
    legal_document.neutral_citation = None
    legal_document.parties = {}
    legal_document.jurisdiction_binding = ["All India"]
    legal_document.jurisdiction_persuasive = []
    legal_document.current_validity = (
        ValidityStatus.REPEALED if bool(record.get("is_repealed")) else ValidityStatus.GOOD_LAW
    )
    legal_document.overruled_by = None
    legal_document.overruled_date = None
    legal_document.distinguished_by = []
    legal_document.followed_by = []
    legal_document.statutes_interpreted = []
    legal_document.statutes_applied = []
    legal_document.citations_made = []
    legal_document.headnotes = []
    legal_document.ratio_decidendi = None
    legal_document.obiter_dicta = []
    legal_document.practice_areas = ["statutory"]
    legal_document.language = _as_str(record.get("language")) or "en"
    legal_document.full_text = None
    legal_document.source_system = SOURCE_KEY
    legal_document.source_url = _canonical_source_url(
        _as_str(record.get("source_url")),
        handle,
    )
    legal_document.source_document_ref = source_document_ref
    legal_document.fetched_at = _parse_datetime(record.get("fetch_timestamp"))
    legal_document.checksum = _as_str(record.get("checksum"))
    legal_document.parser_version = PARSER_VERSION
    legal_document.ingestion_run = run
    legal_document.approval_status = ApprovalStatus.APPROVED
    legal_document.validity_checked_at = None
    legal_document.projection_stale = False
    legal_document.stale_reason = None

    legal_document.chunks.clear()
    if statute_document.sections:
        statute_document.sections.clear()

    statute_document.act_name = title
    statute_document.short_title = _as_str(record.get("short_title")) or title
    statute_document.replaced_by = None
    statute_document.replaced_on = _parse_date(record.get("replaced_on"))
    statute_document.current_sections_in_force = []
    statute_document.jurisdiction = "Central"
    statute_document.enforcement_date = _parse_date(
        record.get("commencement_date") or record.get("enactment_date")
    )
    statute_document.current_validity = not bool(record.get("is_repealed"))

    for index, section_payload in enumerate(sections_payload):
        if not isinstance(section_payload, dict):
            continue
        section_number = _as_str(section_payload.get("section_number")) or str(index + 1)
        heading = _as_str(section_payload.get("heading"))
        text = _section_text(section_payload)
        if not text:
            text = heading or section_number
        is_in_force = _as_bool(section_payload.get("is_in_force"))
        if is_in_force is None:
            is_in_force = "[Omitted]" not in (heading or "")

        section = StatuteSection(
            id=str(uuid5(NAMESPACE_URL, f"{doc_id}|section|{section_number}")),
            section_number=section_number,
            heading=heading,
            text=text,
            original_text=_as_str(section_payload.get("original_text")) or text,
            is_in_force=is_in_force,
            corresponding_new_section=_as_str(
                section_payload.get("corresponding_new_section")
            ),
            punishment=_as_str(section_payload.get("punishment")),
            cases_interpreting=_as_str_list(section_payload.get("cases_interpreting")),
        )

        for amendment_payload in _as_list(section_payload.get("amendments")):
            if not isinstance(amendment_payload, dict):
                continue
            amendment_label = (
                _as_str(amendment_payload.get("amendment_label"))
                or _as_str(amendment_payload.get("label"))
                or f"{section_number}-amendment"
            )
            section.amendments.append(
                StatuteAmendment(
                    id=str(uuid5(NAMESPACE_URL, f"{section.id}|amendment|{amendment_label}")),
                    amendment_label=amendment_label,
                    amendment_date=_parse_date(amendment_payload.get("amendment_date")),
                    effective_date=_parse_date(amendment_payload.get("effective_date")),
                    summary=_as_str(amendment_payload.get("summary")),
                    previous_text=_as_str(amendment_payload.get("previous_text")),
                    updated_text=_as_str(amendment_payload.get("updated_text")),
                )
            )
            amendment_count += 1

        statute_document.sections.append(section)
        section_count += 1
        if is_in_force:
            statute_document.current_sections_in_force.append(section_number)
        section_texts.append(text)

    legal_document.full_text = "\n\n".join(section_texts).strip() or legal_document.full_text

    for index, section_payload in enumerate(sections_payload):
        if not isinstance(section_payload, dict):
            continue
        section_number = _as_str(section_payload.get("section_number")) or str(index + 1)
        heading = _as_str(section_payload.get("heading"))
        text = _section_text(section_payload) or heading or section_number
        chunk = DocumentChunk(
            chunk_id=str(uuid5(NAMESPACE_URL, f"{doc_id}|chunk|{index}")),
            doc_id=doc_id,
            doc_type=LegalDocumentType.STATUTE,
            text=text,
            text_normalized=" ".join(text.split()),
            chunk_index=index,
            total_chunks=max(1, len(sections_payload)),
            section_header=f"Section {section_number}" + (f" - {heading}" if heading else ""),
            court=None,
            date=legal_document.date,
            citation=legal_document.citation,
            jurisdiction_binding=["All India"],
            jurisdiction_persuasive=[],
            current_validity=legal_document.current_validity,
            practice_area=["statutory"],
            act_name=statute_document.act_name,
            section_number=section_number,
            is_in_force=bool(section_payload.get("is_in_force", True)),
            amendment_date=_parse_date(section_payload.get("amendment_date")),
        )
        legal_document.chunks.append(chunk)

    session.flush()
    return FileResult(
        path=str(path),
        status="inserted" if inserted else "updated",
        doc_id=doc_id,
        source_document_ref=source_document_ref,
        sections=section_count,
        chunks=len(sections_payload),
        amendments=amendment_count,
    )


def _write_summary(path: Path, summary: MergeSummary) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary.to_dict(), indent=2, sort_keys=True), encoding="utf-8")


def _canonical_source_url(source_url: str | None, handle: str) -> str:
    if source_url:
        return source_url
    return f"https://www.indiacode.nic.in/handle/123456789/{handle}?view_type=browse&col=123456789/1362"


def _section_text(section: dict[str, Any]) -> str:
    parts: list[str] = []
    heading = _as_str(section.get("heading"))
    number = _as_str(section.get("section_number")) or _as_str(section.get("number"))
    text = _as_str(section.get("text")) or _as_str(section.get("body")) or _as_str(
        section.get("content")
    )
    if number and heading:
        parts.append(f"Section {number} - {heading}")
    elif number:
        parts.append(f"Section {number}")
    elif heading:
        parts.append(heading)
    if text:
        parts.append(text)

    for key in ("subsections", "clauses", "subclauses", "provisos", "explanations"):
        for item in _as_list(section.get(key)):
            if isinstance(item, dict):
                child_text = _section_text(item)
            else:
                child_text = _as_str(item)
            if child_text:
                parts.append(child_text)

    return "\n".join(part for part in parts if part).strip()


def _dedupe_sections_payload(sections_payload: list[Any]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen_by_number: dict[str, dict[str, Any]] = {}

    for index, section_payload in enumerate(sections_payload):
        if not isinstance(section_payload, dict):
            continue

        candidate = dict(section_payload)
        section_number = _as_str(candidate.get("section_number")) or str(index + 1)
        candidate["section_number"] = section_number

        existing = seen_by_number.get(section_number)
        if existing is None:
            seen_by_number[section_number] = candidate
            deduped.append(candidate)
            continue

        existing_text = _section_text(existing)
        candidate_text = _section_text(candidate)
        if len(candidate_text) > len(existing_text):
            if not candidate.get("amendments") and existing.get("amendments"):
                candidate["amendments"] = existing.get("amendments")
            if not candidate.get("heading") and existing.get("heading"):
                candidate["heading"] = existing.get("heading")
            existing.clear()
            existing.update(candidate)
            continue

        if not existing.get("heading") and candidate.get("heading"):
            existing["heading"] = candidate.get("heading")
        if not existing.get("text") and candidate.get("text"):
            existing["text"] = candidate.get("text")
        if not existing.get("original_text") and candidate.get("original_text"):
            existing["original_text"] = candidate.get("original_text")
        if not existing.get("amendments") and candidate.get("amendments"):
            existing["amendments"] = candidate.get("amendments")

    return deduped


def _dedupe_key(act_number: str | None, year: str | None, title: str) -> str:
    if act_number and year:
        return f"{act_number}|{year}"
    return title


def _parse_date(value: object) -> date_value | None:
    text = _as_str(value)
    if not text:
        return None
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_datetime(value: object) -> datetime | None:
    text = _as_str(value)
    if not text:
        return None
    cleaned = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed
    except ValueError:
        parsed_date = _parse_date(text)
        if parsed_date is not None:
            return datetime.combine(parsed_date, datetime.min.time(), tzinfo=UTC)
        return None


def _as_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return None


def _as_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    return []


def _as_str_list(value: object) -> list[str]:
    return [item for item in (_as_str(item) for item in _as_list(value)) if item]


if __name__ == "__main__":
    raise SystemExit(main())
