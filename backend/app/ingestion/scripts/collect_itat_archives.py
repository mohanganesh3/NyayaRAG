from __future__ import annotations

import argparse
import re
from datetime import UTC, date, datetime, timedelta
from html import unescape as html_unescape
from pathlib import Path
from time import sleep
from urllib.parse import urljoin, urlparse

import requests

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
from app.ingestion.orchestrator import IngestionOrchestrator
from app.models import SourcePartitionStatus
from app.models.legal import ApprovalStatus
from app.models.provenance import SourceRegistry, SourceType
from sqlalchemy import text
from sqlalchemy.orm import Session

_ = model_registry

BASE_URL = "https://itat.gov.in"
ARCHIVE_URL = f"{BASE_URL}/home/archives"

PAGE_LABELS = {
    "49": "Notice Board",
    "47": "Press Releases",
    "103": "RTI Orders & Circulars",
    "86": "Holiday Lists",
    "85": "Circulars and Notifications",
}

PAGE_DOC_TYPES = {
    "49": "order",
    "47": "notification",
    "103": "circular",
    "85": "circular",
    "86": "notification",
}

_TAG_RE = re.compile(r"<[^>]+>")


def _default_database_url() -> str:
    db_path = BACKEND_ROOT.parent / "data" / "collection" / "staging" / "itat.db"
    return f"sqlite+pysqlite:///{db_path}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collect_itat_archives",
        description=(
            "Collect ITAT archive PDFs by posting to the official archives surface "
            "and ingesting the resulting public upload links with provenance metadata."
        ),
    )
    parser.add_argument("--database-url", default=_default_database_url())
    parser.add_argument(
        "--page-name",
        action="append",
        dest="page_names",
        help="Official ITAT archives page name id. Defaults to 49 (Notice Board).",
    )
    parser.add_argument("--start-date", default="1990-01-01")
    parser.add_argument(
        "--end-date",
        default=datetime.now(UTC).date().isoformat(),
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=365,
        help="Date window size for each archives POST request.",
    )
    parser.add_argument("--limit", type=int, default=250000)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--sleep-seconds", type=float, default=0.02)
    parser.add_argument("--fetch-retries", type=int, default=2)
    parser.add_argument("--retry-backoff-seconds", type=float, default=1.5)
    parser.add_argument("--parser-version", default="itat-archives-v1")
    parser.add_argument(
        "--document-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If true (default), skip chunk/embedding/graph projections.",
    )
    parser.add_argument(
        "--allow-underfilled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If true (default), do not exit non-zero when fewer than --limit docs ingest.",
    )
    parser.add_argument("--log-every", type=int, default=100)
    return parser


def _headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": ARCHIVE_URL,
        "Origin": BASE_URL,
    }


def _clean_html_fragment(fragment: str) -> str:
    cleaned = _TAG_RE.sub(" ", html_unescape(fragment))
    return " ".join(cleaned.split())


def _parse_iso_date(value: str) -> date:
    return date.fromisoformat(value)


def _format_archive_date(value: date) -> str:
    return value.isoformat()


def _parse_uploaded_on(value: str) -> str | None:
    normalized = " ".join(value.split())
    if not normalized:
        return None
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _iter_windows(start_date: date, end_date: date, *, window_days: int) -> list[tuple[date, date]]:
    if end_date < start_date:
        return []
    span = max(1, int(window_days))
    windows: list[tuple[date, date]] = []
    cursor = start_date
    while cursor <= end_date:
        window_end = min(end_date, cursor + timedelta(days=span - 1))
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def _partition_key(*, page_name: str, window_start: date, window_end: date) -> str:
    return f"page:{page_name}|{window_start.isoformat()}:{window_end.isoformat()}"


def _existing_urls(session: Session) -> set[str]:
    rows = session.execute(
        text(
            "SELECT source_url FROM legal_documents "
            "WHERE source_system = 'itat' AND source_url IS NOT NULL"
        )
    ).fetchall()
    return {str(source_url) for (source_url,) in rows if source_url}


def _ensure_source_registry(session: Session) -> None:
    registry = session.get(SourceRegistry, "itat")
    if registry is None:
        registry = SourceRegistry(source_key="itat")
        session.add(registry)

    registry.display_name = "Income Tax Appellate Tribunal"
    registry.source_type = SourceType.TRIBUNAL_PORTAL
    registry.base_url = BASE_URL
    registry.canonical_hostname = "itat.gov.in"
    registry.jurisdiction_scope = ["All India"]
    registry.update_frequency = "daily"
    registry.access_method = "archive_post_listing"
    registry.is_public = True
    registry.is_active = True
    registry.approval_status = ApprovalStatus.APPROVED
    registry.default_parser_version = "itat-archives-v1"
    registry.collector_type = "archive_post_listing"
    registry.canonical_surfaces = [ARCHIVE_URL, f"{BASE_URL}/judicial/tribunalorders"]
    registry.mirror_surfaces = [f"{BASE_URL}/public/files/upload/*"]
    registry.partition_scheme = "archives_page_name_date_window"
    registry.expected_proof_type = "archive_window_closure"
    registry.auth_mode = "public"
    registry.critical = True
    registry.metadata_profile = {
        "required": [
            "source_url",
            "source_document_ref",
            "collector_run_id",
            "parser_version",
            "checksum",
            "doc_type",
            "title",
            "date_text",
            "source_surface",
            "artifact_url",
            "provenance_tier",
        ]
    }
    session.flush()


def _extract_archive_rows(html: str) -> list[dict[str, str | None]]:
    tbody_start = html.lower().find("<tbody")
    if tbody_start >= 0:
        tbody_open = html.find(">", tbody_start)
        tbody_close = html.lower().find("</tbody>", tbody_open)
        if tbody_open >= 0:
            html = html[tbody_open + 1 : tbody_close if tbody_close >= 0 else None]

    rows: list[dict[str, str | None]] = []
    for fragment in html.split("<tr>"):
        if "/public/files/upload/" not in fragment:
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", fragment, re.IGNORECASE | re.DOTALL)
        if len(cells) < 4:
            continue
        link_match = re.search(
            r"<a\s+href=['\"]([^'\"]+/public/files/upload/[^'\"]+\.pdf[^'\"]*)['\"]",
            fragment,
            re.IGNORECASE,
        )
        if link_match is None:
            continue
        raw_url = link_match.group(1).strip()
        url = urljoin(BASE_URL, raw_url)
        title = _clean_html_fragment(cells[1])
        uploaded_on_text = _clean_html_fragment(cells[-1])
        rows.append(
            {
                "url": url,
                "title": title,
                "uploaded_on_text": uploaded_on_text or None,
                "uploaded_on_iso": _parse_uploaded_on(uploaded_on_text),
            }
        )
    return rows


def _fetch_archive_window(
    session: requests.Session,
    *,
    page_name: str,
    window_start: date,
    window_end: date,
    timeout_seconds: float,
    fetch_retries: int,
    retry_backoff_seconds: float,
) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(max(0, int(fetch_retries)) + 1):
        try:
            page = session.get(ARCHIVE_URL, timeout=timeout_seconds)
            page.raise_for_status()
            csrf_match = re.search(
                r'id="csrftkn" name="csrftkn" value="([0-9a-f]+)"',
                page.text,
                re.IGNORECASE,
            )
            if csrf_match is None:
                raise RuntimeError("csrf token missing from ITAT archives page")
            payload = {
                "hp": "",
                "csrftkn": csrf_match.group(1),
                "page_name": str(page_name),
                "filled_onfrom": _format_archive_date(window_start),
                "filled_onto": _format_archive_date(window_end),
                "bt1": "true",
            }
            response = session.post(
                ARCHIVE_URL,
                data=payload,
                timeout=timeout_seconds,
                headers={"Referer": ARCHIVE_URL},
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= int(fetch_retries):
                raise
            sleep(max(0.0, float(retry_backoff_seconds)) * (attempt + 1))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("unreachable retry state")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target = max(0, int(args.limit))
    if target == 0:
        print("--limit=0 so nothing to ingest.")
        return 0

    start_date = _parse_iso_date(str(args.start_date))
    end_date = _parse_iso_date(str(args.end_date))
    page_names = list(dict.fromkeys(args.page_names or ["49"]))
    windows = _iter_windows(start_date, end_date, window_days=max(1, int(args.window_days)))

    engine = build_engine(args.database_url)
    Base.metadata.create_all(engine)

    adapter = PdfLegalDocumentAdapter()
    orchestrator = IngestionOrchestrator(document_only=bool(args.document_only))
    http = requests.Session()
    http.headers.update(_headers())

    attempted = 0
    discovered = 0
    successes = 0
    skipped_existing = 0
    checked = 0

    with Session(engine) as db_session:
        ensure_collection_control_schema(db_session)
        _ensure_source_registry(db_session)
        ensure_source_url_index(db_session)
        existing_urls = _existing_urls(db_session)

        for page_name in page_names:
            if successes >= target:
                break
            page_label = PAGE_LABELS.get(page_name, f"Page {page_name}")
            doc_type = PAGE_DOC_TYPES.get(page_name, "order")

            for window_start, window_end in windows:
                if successes >= target:
                    break

                partition_key = _partition_key(
                    page_name=page_name,
                    window_start=window_start,
                    window_end=window_end,
                )
                surface_url = f"{ARCHIVE_URL}?page_name={page_name}"
                print(
                    f"[itat-archives] fetching page={page_name} ({page_label}) "
                    f"window={window_start.isoformat()}..{window_end.isoformat()}",
                    flush=True,
                )

                try:
                    response = _fetch_archive_window(
                        http,
                        page_name=page_name,
                        window_start=window_start,
                        window_end=window_end,
                        timeout_seconds=float(args.timeout_seconds),
                        fetch_retries=max(0, int(args.fetch_retries)),
                        retry_backoff_seconds=float(args.retry_backoff_seconds),
                    )
                except Exception as exc:  # noqa: BLE001
                    record_source_partition(
                        db_session,
                        source_key="itat",
                        partition_key=partition_key,
                        surface_url=surface_url,
                        partition_kind="archive_date_window",
                        expected_hint=f"{window_start.isoformat()}:{window_end.isoformat()}",
                        status=SourcePartitionStatus.BROKEN,
                        error_class=type(exc).__name__,
                        proof_note=f"archives fetch failed: {exc}",
                        payload={
                            "collector_type": "archive_post_listing",
                            "partition_scheme": "archives_page_name_date_window",
                            "page_name": page_name,
                            "page_label": page_label,
                        },
                    )
                    db_session.commit()
                    print(
                        f"[itat-archives] page={page_name} window={window_start}..{window_end} "
                        f"fetch failed: {type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    continue

                print(
                    f"[itat-archives] fetched page={page_name} window={window_start.isoformat()}.."
                    f"{window_end.isoformat()} bytes={len(response.text)}",
                    flush=True,
                )
                rows = _extract_archive_rows(response.text)
                print(
                    f"[itat-archives] parsed page={page_name} window={window_start.isoformat()}.."
                    f"{window_end.isoformat()} rows={len(rows)}",
                    flush=True,
                )
                discovered += len(rows)
                record_source_partition(
                    db_session,
                    source_key="itat",
                    partition_key=partition_key,
                    surface_url=surface_url,
                    partition_kind="archive_date_window",
                    expected_hint=f"{window_start.isoformat()}:{window_end.isoformat()}",
                    discovered_increment=len(rows),
                    status=SourcePartitionStatus.RUNNING,
                    proof_note=(
                        f"page={page_name} rows={len(rows)} "
                        f"window={window_start.isoformat()}..{window_end.isoformat()}"
                    ),
                    payload={
                        "collector_type": "archive_post_listing",
                        "partition_scheme": "archives_page_name_date_window",
                        "page_name": page_name,
                        "page_label": page_label,
                    },
                )
                db_session.commit()

                seen_in_window: set[str] = set()
                window_ingested = 0

                for row in rows:
                    if successes >= target:
                        break
                    pdf_url = str(row["url"])
                    if pdf_url in seen_in_window:
                        continue
                    seen_in_window.add(pdf_url)
                    checked += 1

                    if pdf_url in existing_urls or document_exists_by_source_url(
                        db_session,
                        source_system="itat",
                        source_url=pdf_url,
                    ):
                        skipped_existing += 1
                        existing_urls.add(pdf_url)
                        continue

                    attempted += 1
                    basename = Path(urlparse(pdf_url).path).name
                    title = str(row["title"] or basename)
                    uploaded_on_text = row["uploaded_on_text"]
                    print(f"[itat-archives] ingesting {pdf_url}", flush=True)

                    context = IngestionJobContext(
                        source_key="itat",
                        source_url=pdf_url,
                        parser_version=str(args.parser_version),
                        external_id=f"itat-archive-{page_name}-{basename}",
                        metadata={
                            "court_name": "Income Tax Appellate Tribunal",
                            "doc_type": doc_type,
                            "practice_areas": ["tax"],
                            "jurisdiction_binding": ["Income Tax Appellate Tribunal"],
                            "jurisdiction_persuasive": ["All India"],
                            "title": title,
                            "date_text": uploaded_on_text,
                            "seed_url": ARCHIVE_URL,
                            "detail_url": surface_url,
                            "artifact_url": pdf_url,
                            "source_surface": surface_url,
                            "provenance_tier": "official",
                            "mime_type": "application/pdf",
                            "source_document_ref": basename,
                            "collector_type": "archive_post_listing",
                            "partition_key": partition_key,
                            "partition_kind": "archive_date_window",
                            "partition_scheme": "archives_page_name_date_window",
                            "expected_proof_type": "archive_window_closure",
                            "page_name": page_name,
                            "page_label": page_label,
                            "uploaded_on_iso": row["uploaded_on_iso"],
                        },
                    )

                    try:
                        orchestrator.ingest(db_session, adapter, context)
                        record_source_partition(
                            db_session,
                            source_key="itat",
                            partition_key=partition_key,
                            surface_url=surface_url,
                            partition_kind="archive_date_window",
                            expected_hint=f"{window_start.isoformat()}:{window_end.isoformat()}",
                            ingested_increment=1,
                            status=SourcePartitionStatus.RUNNING,
                            proof_note=f"last_ingested={pdf_url}",
                            payload={
                                "collector_type": "archive_post_listing",
                                "partition_scheme": "archives_page_name_date_window",
                                "page_name": page_name,
                                "page_label": page_label,
                            },
                        )
                        db_session.commit()
                        successes += 1
                        window_ingested += 1
                        existing_urls.add(pdf_url)
                    except Exception as exc:  # noqa: BLE001
                        db_session.rollback()
                        record_source_partition(
                            db_session,
                            source_key="itat",
                            partition_key=partition_key,
                            surface_url=surface_url,
                            partition_kind="archive_date_window",
                            expected_hint=f"{window_start.isoformat()}:{window_end.isoformat()}",
                            status=SourcePartitionStatus.BROKEN,
                            error_class=type(exc).__name__,
                            proof_note=f"ingest failed for {pdf_url}: {exc}",
                            payload={
                                "collector_type": "archive_post_listing",
                                "partition_scheme": "archives_page_name_date_window",
                                "page_name": page_name,
                                "page_label": page_label,
                            },
                        )
                        db_session.commit()
                        print(
                            f"[itat-archives] ingest failed url={pdf_url} "
                            f"error={type(exc).__name__}: {exc}",
                            flush=True,
                        )

                    if int(args.log_every) > 0 and checked % int(args.log_every) == 0:
                        print(
                            f"[itat-archives] checked={checked} discovered={discovered} "
                            f"attempted={attempted} ingested={successes} "
                            f"skipped_existing={skipped_existing} "
                            f"page={page_name} window={window_start}..{window_end}",
                            flush=True,
                        )

                    if float(args.sleep_seconds) > 0:
                        sleep(float(args.sleep_seconds))

                final_status = (
                    SourcePartitionStatus.DONE
                    if window_ingested > 0 or rows
                    else SourcePartitionStatus.VERIFIED
                )
                record_source_partition(
                    db_session,
                    source_key="itat",
                    partition_key=partition_key,
                    surface_url=surface_url,
                    partition_kind="archive_date_window",
                    expected_hint=f"{window_start.isoformat()}:{window_end.isoformat()}",
                    status=final_status,
                    proof_note=(
                        f"page={page_name} rows={len(rows)} ingested={window_ingested} "
                        f"window={window_start.isoformat()}..{window_end.isoformat()}"
                    ),
                    payload={
                        "collector_type": "archive_post_listing",
                        "partition_scheme": "archives_page_name_date_window",
                        "page_name": page_name,
                        "page_label": page_label,
                    },
                )
                db_session.commit()

    print(
        f"[itat-archives] completed_at={datetime.now(UTC).isoformat()} checked={checked} "
        f"discovered={discovered} attempted={attempted} ingested={successes} "
        f"skipped_existing={skipped_existing}",
        flush=True,
    )

    if successes >= target or bool(args.allow_underfilled):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
