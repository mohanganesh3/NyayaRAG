from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from time import sleep

import app.models as model_registry
from app.core.config import BACKEND_ROOT
from app.db.base import Base
from app.db.session import build_engine
from app.ingestion.adapters import PdfLegalDocumentAdapter
from app.ingestion.collector_utils import (
    document_exists_by_source_url,
    ensure_collection_control_schema,
    ensure_source_url_index,
    record_source_partition,
)
from app.ingestion.contracts import IngestionJobContext
from app.ingestion.http_client import robust_get
from app.ingestion.orchestrator import IngestionOrchestrator
from app.models import SourcePartitionStatus
from app.models.legal import ApprovalStatus
from app.models.provenance import SourceRegistry, SourceType
from sqlalchemy import text
from sqlalchemy.orm import Session

_ = model_registry

BASE_URL = "https://cestat.gov.in"


def _default_database_url() -> str:
    db_path = BACKEND_ROOT.parent / "data" / "collection" / "staging" / "cestat.db"
    return f"sqlite+pysqlite:///{db_path}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collect_cestat_openfile",
        description=(
            "Collect CESTAT orders by enumerating the official /openfile/<kind>/<id> "
            "document route instead of relying only on captcha-gated search forms."
        ),
    )
    parser.add_argument("--database-url", default=_default_database_url())
    parser.add_argument("--kind", type=int, default=2)
    parser.add_argument("--start-id", type=int, default=1)
    parser.add_argument("--end-id", type=int, default=None)
    parser.add_argument(
        "--lookahead",
        type=int,
        default=2000,
        help=(
            "When --end-id is omitted, keep scanning this far beyond the highest "
            "known good id while the route is still yielding PDFs."
        ),
    )
    parser.add_argument(
        "--consecutive-miss-limit",
        type=int,
        default=750,
        help=(
            "When scanning past the current known frontier, stop after this many "
            "consecutive non-PDF or 404 responses."
        ),
    )
    parser.add_argument("--limit", type=int, default=250000)
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--sleep-seconds", type=float, default=0.02)
    parser.add_argument("--fetch-retries", type=int, default=2)
    parser.add_argument("--retry-backoff-seconds", type=float, default=1.5)
    parser.add_argument("--parser-version", default="cestat-openfile-v1")
    parser.add_argument(
        "--document-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If true (default), skip chunk/embedding/graph projections during ingestion.",
    )
    parser.add_argument(
        "--allow-underfilled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If true (default), do not exit non-zero when fewer than --limit docs are ingested.",
    )
    parser.add_argument("--ssl-verify", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--window-size", type=int, default=250)
    parser.add_argument("--log-every", type=int, default=25)
    return parser


def _headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/pdf,text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"{BASE_URL}/final-order-status-all",
    }


def _pdf_url(*, kind: int, document_id: int) -> str:
    return f"{BASE_URL}/openfile/{int(kind)}/{int(document_id)}"


def _partition_key(*, kind: int, document_id: int, window_size: int) -> str:
    window_start = ((max(1, int(document_id)) - 1) // int(window_size)) * int(window_size) + 1
    window_end = window_start + int(window_size) - 1
    return f"kind:{int(kind)}|id:{window_start}-{window_end}"


def _existing_ids(session: Session, *, kind: int) -> set[int]:
    rows = session.execute(
        text(
            "SELECT source_url FROM legal_documents "
            "WHERE source_system = 'cestat' AND source_url LIKE :pattern"
        ),
        {"pattern": f"%/openfile/{int(kind)}/%"},
    ).fetchall()
    found: set[int] = set()
    pattern = re.compile(rf"/openfile/{int(kind)}/(\d+)")
    for (source_url,) in rows:
        if not source_url:
            continue
        match = pattern.search(str(source_url))
        if match:
            found.add(int(match.group(1)))
    return found


def _ensure_source_registry(session: Session) -> None:
    registry = session.get(SourceRegistry, "cestat")
    if registry is not None:
        return
    session.add(
        SourceRegistry(
            source_key="cestat",
            display_name="Customs, Excise and Service Tax Appellate Tribunal",
            source_type=SourceType.TRIBUNAL_PORTAL,
            base_url=BASE_URL,
            canonical_hostname="cestat.gov.in",
            jurisdiction_scope=["All India"],
            update_frequency="daily",
            access_method="direct_document_enumerator",
            is_public=True,
            is_active=True,
            approval_status=ApprovalStatus.APPROVED,
            default_parser_version="cestat-openfile-v1",
            collector_type="direct_document_enumerator",
            canonical_surfaces=[
                f"{BASE_URL}/openfile/2/*",
                f"{BASE_URL}/final-order-status-all",
            ],
            mirror_surfaces=["https://www.cis.cestat.gov.in"],
            partition_scheme="openfile_kind_2_numeric_id",
            expected_proof_type="numeric_range_closure",
            auth_mode="public",
            critical=True,
            metadata_profile={
                "required": [
                    "source_url",
                    "source_document_ref",
                    "collector_run_id",
                    "parser_version",
                    "checksum",
                    "doc_type",
                ]
            },
        )
    )
    session.flush()


def _fetch_with_retries(
    url: str,
    *,
    timeout_seconds: float,
    ssl_verify: bool,
    fetch_retries: int,
    retry_backoff_seconds: float,
):
    last_exc: Exception | None = None
    for attempt in range(max(0, int(fetch_retries)) + 1):
        try:
            response = robust_get(
                url,
                headers=_headers(),
                timeout=float(timeout_seconds),
                verify=bool(ssl_verify),
                max_attempts=4,
            )
            return response
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= int(fetch_retries):
                raise
            sleep(max(0.0, float(retry_backoff_seconds)) * (attempt + 1))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"unreachable retry state for {url}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    target = max(0, int(args.limit))
    if target == 0:
        print("--limit=0 so nothing to ingest.")
        return 0

    engine = build_engine(args.database_url)
    Base.metadata.create_all(engine)

    adapter = PdfLegalDocumentAdapter()
    orchestrator = IngestionOrchestrator(document_only=bool(args.document_only))

    attempted = 0
    discovered = 0
    successes = 0
    skipped_existing = 0
    checked = 0
    consecutive_misses = 0

    with Session(engine) as db_session:
        ensure_collection_control_schema(db_session)
        _ensure_source_registry(db_session)
        ensure_source_url_index(db_session)

        existing_ids = _existing_ids(db_session, kind=int(args.kind))
        known_max_id = max(existing_ids, default=0)
        frontier = max(int(args.start_id), known_max_id)
        end_id = (
            max(int(args.end_id), int(args.start_id))
            if args.end_id is not None
            else max(int(args.start_id), frontier + int(args.lookahead))
        )

        document_id = max(1, int(args.start_id))
        while successes < target and document_id <= end_id:
            partition_key = _partition_key(
                kind=int(args.kind),
                document_id=document_id,
                window_size=int(args.window_size),
            )
            partition_surface = f"{BASE_URL}/openfile/{int(args.kind)}/*"
            pdf_url = _pdf_url(kind=int(args.kind), document_id=document_id)
            checked += 1

            if document_id in existing_ids or document_exists_by_source_url(
                db_session,
                source_system="cestat",
                source_url=pdf_url,
            ):
                existing_ids.add(document_id)
                skipped_existing += 1
                consecutive_misses = 0
                if document_id > frontier:
                    frontier = document_id
                    if args.end_id is None:
                        end_id = max(end_id, frontier + int(args.lookahead))
                document_id += 1
                continue

            try:
                response = _fetch_with_retries(
                    pdf_url,
                    timeout_seconds=float(args.timeout_seconds),
                    ssl_verify=bool(args.ssl_verify),
                    fetch_retries=max(0, int(args.fetch_retries)),
                    retry_backoff_seconds=float(args.retry_backoff_seconds),
                )
            except Exception as exc:  # noqa: BLE001
                record_source_partition(
                    db_session,
                    source_key="cestat",
                    partition_key=partition_key,
                    surface_url=partition_surface,
                    partition_kind="numeric_id_window",
                    expected_hint=f"id={document_id}",
                    status=SourcePartitionStatus.BROKEN,
                    error_class=type(exc).__name__,
                    proof_note=f"fetch failed for {pdf_url}: {exc}",
                    payload={
                        "collector_type": "direct_document_enumerator",
                        "partition_scheme": f"openfile_kind_{int(args.kind)}_numeric_id",
                    },
                )
                db_session.commit()
                print(
                    f"[cestat-openfile] fetch failed id={document_id} "
                    f"error={type(exc).__name__}: {exc}",
                    flush=True,
                )
                document_id += 1
                continue

            content_type = (response.headers.get("content-type") or "").lower()
            is_pdf = response.status_code == 200 and "pdf" in content_type
            if not is_pdf:
                consecutive_misses += 1
                record_source_partition(
                    db_session,
                    source_key="cestat",
                    partition_key=partition_key,
                    surface_url=partition_surface,
                    partition_kind="numeric_id_window",
                    expected_hint=f"id={document_id}",
                    status=SourcePartitionStatus.RUNNING,
                    proof_note=f"id={document_id} status={response.status_code} content_type={content_type or 'unknown'}",
                    payload={
                        "collector_type": "direct_document_enumerator",
                        "partition_scheme": f"openfile_kind_{int(args.kind)}_numeric_id",
                    },
                )
                db_session.commit()
                if (
                    args.end_id is None
                    and document_id > frontier
                    and consecutive_misses >= int(args.consecutive_miss_limit)
                ):
                    print(
                        f"[cestat-openfile] stopping after {consecutive_misses} consecutive misses "
                        f"beyond frontier={frontier}",
                        flush=True,
                    )
                    break
                document_id += 1
                continue

            consecutive_misses = 0
            discovered += 1
            record_source_partition(
                db_session,
                source_key="cestat",
                partition_key=partition_key,
                surface_url=partition_surface,
                partition_kind="numeric_id_window",
                expected_hint=f"id={document_id}",
                discovered_increment=1,
                status=SourcePartitionStatus.RUNNING,
                proof_note=f"pdf={pdf_url}",
                payload={
                    "collector_type": "direct_document_enumerator",
                    "partition_scheme": f"openfile_kind_{int(args.kind)}_numeric_id",
                },
            )

            attempted += 1
            context = IngestionJobContext(
                source_key="cestat",
                source_url=pdf_url,
                parser_version=str(args.parser_version),
                external_id=f"cestat-openfile-{int(args.kind)}-{document_id}",
                metadata={
                    "court_name": "Customs, Excise and Service Tax Appellate Tribunal",
                    "doc_type": "order",
                    "practice_areas": ["tax"],
                    "jurisdiction_binding": ["Customs, Excise and Service Tax Appellate Tribunal"],
                    "jurisdiction_persuasive": ["All India"],
                    "title": f"CESTAT Order {document_id}",
                    "ssl_verify": bool(args.ssl_verify),
                    "seed_url": f"{BASE_URL}/final-order-status-all",
                    "detail_url": pdf_url,
                    "artifact_url": pdf_url,
                    "source_surface": f"{BASE_URL}/openfile/{int(args.kind)}/*",
                    "provenance_tier": "official",
                    "mime_type": content_type or "application/pdf",
                    "source_document_ref": f"openfile-{int(args.kind)}-{document_id}",
                    "collector_type": "direct_document_enumerator",
                    "partition_key": partition_key,
                    "partition_kind": "numeric_id_window",
                    "partition_scheme": f"openfile_kind_{int(args.kind)}_numeric_id",
                    "expected_proof_type": "numeric_range_closure",
                },
            )

            try:
                orchestrator.ingest(db_session, adapter, context)
                record_source_partition(
                    db_session,
                    source_key="cestat",
                    partition_key=partition_key,
                    surface_url=partition_surface,
                    partition_kind="numeric_id_window",
                    expected_hint=f"id={document_id}",
                    ingested_increment=1,
                    status=SourcePartitionStatus.RUNNING,
                    proof_note=f"last_ingested={pdf_url}",
                    payload={
                        "collector_type": "direct_document_enumerator",
                        "partition_scheme": f"openfile_kind_{int(args.kind)}_numeric_id",
                    },
                )
                db_session.commit()
                successes += 1
                existing_ids.add(document_id)
                if document_id > frontier:
                    frontier = document_id
                    if args.end_id is None:
                        end_id = max(end_id, frontier + int(args.lookahead))
            except Exception as exc:  # noqa: BLE001
                db_session.rollback()
                record_source_partition(
                    db_session,
                    source_key="cestat",
                    partition_key=partition_key,
                    surface_url=partition_surface,
                    partition_kind="numeric_id_window",
                    expected_hint=f"id={document_id}",
                    status=SourcePartitionStatus.BROKEN,
                    error_class=type(exc).__name__,
                    proof_note=f"ingest failed for {pdf_url}: {exc}",
                    payload={
                        "collector_type": "direct_document_enumerator",
                        "partition_scheme": f"openfile_kind_{int(args.kind)}_numeric_id",
                    },
                )
                db_session.commit()
                print(
                    f"[cestat-openfile] ingest failed id={document_id} "
                    f"error={type(exc).__name__}: {exc}",
                    flush=True,
                )

            if int(args.log_every) > 0 and checked % int(args.log_every) == 0:
                print(
                    f"[cestat-openfile] checked={checked} discovered={discovered} attempted={attempted} "
                    f"ingested={successes} skipped_existing={skipped_existing} "
                    f"frontier={frontier} end_id={end_id}",
                    flush=True,
                )

            if float(args.sleep_seconds) > 0:
                sleep(float(args.sleep_seconds))

            document_id += 1

    print(
        f"[cestat-openfile] completed_at={datetime.now(UTC).isoformat()} checked={checked} "
        f"discovered={discovered} attempted={attempted} ingested={successes} "
        f"skipped_existing={skipped_existing}",
        flush=True,
    )

    if successes >= target or bool(args.allow_underfilled):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
