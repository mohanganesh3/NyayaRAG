from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from pathlib import Path

import app.models as model_registry
import requests
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
from sqlalchemy.orm import Session

_ = model_registry

SEBI_ACTIVE_URL = "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=7&smid=0"
SEBI_ARCHIVE_URL = (
    "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListingCirArchive=yes&sid=1&ssid=7&smid=0"
)
SEBI_ACTIVE_AJAX_URL = "https://www.sebi.gov.in/sebiweb/ajax/home/getnewslistinfo.jsp"
SEBI_ARCHIVE_AJAX_URL = "https://www.sebi.gov.in/sebiweb/ajax/home/getArchiveCircularlistinfo.jsp"

ROW_RE = re.compile(
    r"<tr[^>]*>\s*<td>(?P<date>.*?)</td>\s*<td><a href=['\"](?P<detail_url>https://www\.sebi\.gov\.in/[^'\"]+)['\"]"
    r"[^>]*title=['\"](?P<title>[^'\"]+)['\"]",
    re.IGNORECASE | re.DOTALL,
)
PDF_URL_RE = re.compile(
    r"https://www\.sebi\.gov\.in/sebi_data/attachdocs/[^\s\"'<>]+\.pdf",
    re.IGNORECASE,
)
NEXT_VALUE_RE = re.compile(r"name=['\"]nextValue['\"]\s+value=['\"]?(\d+)", re.IGNORECASE)
TOTAL_PAGE_RE = re.compile(r"name=['\"]totalpage['\"]\s+value=['\"]?(\d+)", re.IGNORECASE)
LAST_PAGE_RE = re.compile(r"title=['\"]Last['\"].*?search(?:Archive)?CircularList\('n','(\d+)'\)", re.IGNORECASE)


def _default_database_url() -> str:
    db_path = BACKEND_ROOT.parent / "data" / "collection" / "staging" / "sebi.db"
    return f"sqlite+pysqlite:///{db_path}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collect_sebi_circulars",
        description=(
            "Collect SEBI circular PDFs by paging through the official listing AJAX endpoints "
            "and ingesting the underlying attachdocs PDFs."
        ),
    )
    parser.add_argument("--database-url", default=_default_database_url())
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--allow-underfilled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If true, do not exit non-zero when fewer than --limit PDFs are ingested.",
    )
    parser.add_argument("--parser-version", default="sebi-circulars-v1")
    parser.add_argument("--ssl-verify", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument(
        "--include-archive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If true, page the active and archive circular listings.",
    )
    parser.add_argument(
        "--document-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If true, skip chunk/embedding/graph projections during ingestion.",
    )
    parser.add_argument("--log-every", type=int, default=10)
    return parser


def _headers(*, referer: str, xhr: bool = False) -> dict[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*" if xhr else "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer,
    }
    if xhr:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["X-Requested-With"] = "XMLHttpRequest"
    return headers


def _clean_html(value: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", value or "").split()).strip()


def _stable_external_id(pdf_url: str) -> str:
    tail = Path(pdf_url.split("?", 1)[0]).name
    return tail or f"sebi-{abs(hash(pdf_url))}"


def _listing_state(html: str) -> tuple[int, int]:
    next_match = NEXT_VALUE_RE.search(html)
    next_value = int(next_match.group(1)) if next_match else 1

    total_match = TOTAL_PAGE_RE.search(html)
    if total_match:
        return next_value, int(total_match.group(1))

    last_match = LAST_PAGE_RE.search(html)
    if last_match:
        return next_value, int(last_match.group(1)) + 1

    return next_value, 1


def _listing_entries(html: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for match in ROW_RE.finditer(html):
        entries.append(
            {
                "date_text": _clean_html(match.group("date")),
                "title": _clean_html(match.group("title")) or "SEBI Circular",
                "detail_url": match.group("detail_url").strip(),
            }
        )
    return entries


def _detail_pdf_urls(html: str) -> list[str]:
    return sorted(set(PDF_URL_RE.findall(html)))


def _fetch_listing_page(
    http: requests.Session,
    *,
    listing_url: str,
    timeout_seconds: float,
    ssl_verify: bool,
) -> str:
    response = http.get(
        listing_url,
        headers=_headers(referer="https://www.sebi.gov.in/"),
        timeout=timeout_seconds,
        verify=ssl_verify,
    )
    response.raise_for_status()
    return response.text


def _fetch_listing_ajax(
    http: requests.Session,
    *,
    ajax_url: str,
    next_value: int,
    page_index: int,
    timeout_seconds: float,
    ssl_verify: bool,
) -> str:
    payload = {
        "nextValue": str(next_value),
        "next": "n",
        "search": "",
        "fromDate": "",
        "toDate": "",
        "fromYear": "",
        "toYear": "",
        "deptId": "",
        "sid": "1",
        "ssid": "7",
        "smid": "0",
        "ssidhidden": "7",
        "intmid": "-1",
        "sText": "Legal",
        "ssText": "Circulars",
        "smText": "",
        "doDirect": str(page_index),
    }
    response = http.post(
        ajax_url,
        data=payload,
        headers=_headers(referer=SEBI_ACTIVE_URL, xhr=True),
        timeout=timeout_seconds,
        verify=ssl_verify,
    )
    response.raise_for_status()
    return response.text


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    engine = build_engine(args.database_url)
    Base.metadata.create_all(engine)

    target = max(0, int(args.limit))
    if target == 0:
        print("--limit=0 so nothing to ingest.")
        return 0

    adapter = PdfLegalDocumentAdapter()
    orchestrator = IngestionOrchestrator(document_only=bool(args.document_only))
    http = requests.Session()

    listings: list[tuple[str, str, bool]] = [(SEBI_ACTIVE_URL, SEBI_ACTIVE_AJAX_URL, False)]
    if bool(args.include_archive):
        listings.append((SEBI_ARCHIVE_URL, SEBI_ARCHIVE_AJAX_URL, True))

    successes = 0
    attempted = 0
    discovered = 0
    skipped_existing = 0
    seen_detail_urls: set[str] = set()
    seen_pdf_urls: set[str] = set()

    with Session(engine) as db_session:
        ensure_collection_control_schema(db_session)
        ensure_source_url_index(db_session)
        for listing_url, ajax_url, is_archive in listings:
            if successes >= target:
                break

            try:
                html = _fetch_listing_page(
                    http,
                    listing_url=listing_url,
                    timeout_seconds=float(args.timeout_seconds),
                    ssl_verify=bool(args.ssl_verify),
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[listing-skip] url={listing_url} err={type(exc).__name__}: {exc}", flush=True)
                continue

            next_value, total_pages = _listing_state(html)
            pages_to_process: list[tuple[int, str]] = [(0, html)]
            next_page_index = 1

            # The landing page exposes only the first 25 rows; the real page count often
            # appears only in the first AJAX response. Bootstrap that response so we can
            # continue through the full listing instead of stopping after page 1.
            if total_pages <= 1:
                try:
                    first_ajax_html = _fetch_listing_ajax(
                        http,
                        ajax_url=ajax_url,
                        next_value=next_value,
                        page_index=1,
                        timeout_seconds=float(args.timeout_seconds),
                        ssl_verify=bool(args.ssl_verify),
                    )
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[page-skip] listing={'archive' if is_archive else 'active'} "
                        f"page_index=1 err={type(exc).__name__}: {exc}",
                        flush=True,
                    )
                else:
                    ajax_next_value, ajax_total_pages = _listing_state(first_ajax_html)
                    if first_ajax_html.strip():
                        pages_to_process.append((1, first_ajax_html))
                        next_value = ajax_next_value
                        total_pages = max(total_pages, ajax_total_pages, 2)
                        next_page_index = 2

            for page_index in range(next_page_index, total_pages):
                try:
                    page_html = _fetch_listing_ajax(
                        http,
                        ajax_url=ajax_url,
                        next_value=next_value,
                        page_index=page_index,
                        timeout_seconds=float(args.timeout_seconds),
                        ssl_verify=bool(args.ssl_verify),
                    )
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[page-skip] listing={'archive' if is_archive else 'active'} "
                        f"page_index={page_index} err={type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    break

                next_value, _ = _listing_state(page_html)
                pages_to_process.append((page_index, page_html))
                if successes >= target:
                    break

            for page_index, page_html in pages_to_process:
                if successes >= target:
                    break
                partition_key = f"{'archive' if is_archive else 'active'}:page:{page_index}"
                entries = _listing_entries(page_html)
                record_source_partition(
                    db_session,
                    source_key="sebi",
                    partition_key=partition_key,
                    surface_url=ajax_url if page_index else listing_url,
                    partition_kind="ajax_listing_page",
                    expected_hint=f"page_index={page_index}",
                    discovered_increment=len(entries),
                    status=SourcePartitionStatus.RUNNING,
                    proof_note=f"discovered {len(entries)} detail rows",
                    payload={
                        "collector_type": "ajax_archive",
                        "listing_mode": "archive" if is_archive else "active",
                    },
                )
                db_session.commit()
                for entry in entries:
                    if successes >= target:
                        break

                    detail_url = entry["detail_url"]
                    if detail_url in seen_detail_urls:
                        continue
                    seen_detail_urls.add(detail_url)

                    attempted += 1
                    try:
                        detail_response = http.get(
                            detail_url,
                            headers=_headers(referer=listing_url),
                            timeout=float(args.timeout_seconds),
                            verify=bool(args.ssl_verify),
                        )
                        detail_response.raise_for_status()
                    except Exception as exc:  # noqa: BLE001
                        db_session.rollback()
                        record_source_partition(
                            db_session,
                            source_key="sebi",
                            partition_key=partition_key,
                            surface_url=ajax_url if page_index else listing_url,
                            partition_kind="ajax_listing_page",
                            expected_hint=f"page_index={page_index}",
                            status=SourcePartitionStatus.BROKEN,
                            error_class=type(exc).__name__,
                            proof_note=f"detail fetch failed: {detail_url}",
                            payload={
                                "collector_type": "ajax_archive",
                                "listing_mode": "archive" if is_archive else "active",
                            },
                        )
                        db_session.commit()
                        print(f"[detail-skip] url={detail_url} err={type(exc).__name__}: {exc}", flush=True)
                        continue

                    pdf_urls = _detail_pdf_urls(detail_response.text)
                    if not pdf_urls:
                        pdf_urls = [url for url in PDF_URL_RE.findall(page_html) if url not in seen_pdf_urls]

                    discovered += len(pdf_urls)
                    for pdf_url in pdf_urls:
                        if successes >= target:
                            break
                        if pdf_url in seen_pdf_urls:
                            continue
                        seen_pdf_urls.add(pdf_url)
                        if document_exists_by_source_url(
                            db_session,
                            source_system="sebi",
                            source_url=pdf_url,
                        ):
                            skipped_existing += 1
                            continue
                        context = IngestionJobContext(
                            source_key="sebi",
                            source_url=pdf_url,
                            parser_version=str(args.parser_version),
                            external_id=_stable_external_id(pdf_url),
                            metadata={
                                "court_name": "Securities and Exchange Board of India",
                                "doc_type": "circular",
                                "practice_areas": ["securities"],
                                "jurisdiction_binding": ["All India"],
                                "jurisdiction_persuasive": ["All India"],
                                "title": entry["title"],
                                "date_text": entry["date_text"] or None,
                                "ssl_verify": bool(args.ssl_verify),
                                "http_headers": {"Referer": detail_url},
                                "seed_url": listing_url,
                                "detail_url": detail_url,
                                "artifact_url": pdf_url,
                                "source_surface": "archive_ajax" if is_archive else "active_ajax",
                                "provenance_tier": "official",
                                "collector_type": "ajax_archive",
                                "partition_key": partition_key,
                                "partition_kind": "ajax_listing_page",
                                "partition_scheme": "listing_mode_page",
                                "expected_proof_type": "ajax_listing_complete",
                                "listing_page_index": page_index,
                                "listing_mode": "archive" if is_archive else "active",
                                "collected_at": datetime.now(UTC).isoformat(),
                            },
                        )
                        try:
                            persisted = orchestrator.ingest(db_session, adapter, context)
                            record_source_partition(
                                db_session,
                                source_key="sebi",
                                partition_key=partition_key,
                                surface_url=ajax_url if page_index else listing_url,
                                partition_kind="ajax_listing_page",
                                expected_hint=f"page_index={page_index}",
                                ingested_increment=1,
                                status=SourcePartitionStatus.RUNNING,
                                proof_note=f"last_ingested={pdf_url}",
                                payload={
                                    "collector_type": "ajax_archive",
                                    "listing_mode": "archive" if is_archive else "active",
                                },
                            )
                            db_session.commit()
                        except Exception as exc:  # noqa: BLE001
                            db_session.rollback()
                            record_source_partition(
                                db_session,
                                source_key="sebi",
                                partition_key=partition_key,
                                surface_url=ajax_url if page_index else listing_url,
                                partition_kind="ajax_listing_page",
                                expected_hint=f"page_index={page_index}",
                                status=SourcePartitionStatus.BROKEN,
                                error_class=type(exc).__name__,
                                proof_note=f"ingest failed for {pdf_url}",
                                payload={
                                    "collector_type": "ajax_archive",
                                    "listing_mode": "archive" if is_archive else "active",
                                },
                            )
                            db_session.commit()
                            print(f"[skip] url={pdf_url} err={type(exc).__name__}: {exc}", flush=True)
                            continue

                        successes += 1
                        if int(args.log_every) > 0 and successes % int(args.log_every) == 0:
                            print(
                                f"[{successes}/{target}] ingested doc_id={persisted.doc_id} url={pdf_url}",
                                flush=True,
                            )

    if successes < target:
        msg = (
            f"Only ingested {successes}/{target} SEBI PDFs "
            f"(attempted {attempted}, discovered {discovered}, skipped_existing {skipped_existing})."
        )
        if bool(args.allow_underfilled):
            print(msg, flush=True)
            return 0
        raise SystemExit(msg)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
