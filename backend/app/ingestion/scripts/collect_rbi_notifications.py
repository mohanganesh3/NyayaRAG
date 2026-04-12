from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from html import unescape as html_unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

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

RBI_LISTINGS: tuple[dict[str, str], ...] = (
    {
        "label": "notifications",
        "page_url": "https://www.rbi.org.in/Scripts/NotificationUser.aspx",
        "doc_type": "notification",
    },
    {
        "label": "press_releases",
        "page_url": "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx",
        "doc_type": "notification",
    },
)

SECTION_RE = re.compile(
    r"<tr><td[^>]*class=[\"']tableheader[\"'][^>]*>.*?<b>(?P<date>[^<]+)</b>.*?</tr>"
    r"(?P<body>.*?)(?=<tr><td[^>]*class=[\"']tableheader[\"'][^>]*>|$)",
    re.IGNORECASE | re.DOTALL,
)
ROW_RE = re.compile(
    r"<a[^>]*class=[\"']link2[\"'][^>]*>(?P<title>.*?)</a>"
    r".*?href=[\"'](?P<pdf_url>https://rbidocs\.rbi\.org\.in/rdocs/[^\"']+\.pdf)[\"']",
    re.IGNORECASE | re.DOTALL,
)
DETAIL_PAGE_RE = re.compile(
    r"(?:NotificationUser|BS_PressReleaseDisplay)\.aspx\?Id=\d+",
    re.IGNORECASE,
)
TAG_RE = re.compile(r"<[^>]+>")


def _default_database_url() -> str:
    db_path = BACKEND_ROOT.parent / "data" / "collection" / "staging" / "rbi.db"
    return f"sqlite+pysqlite:///{db_path}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collect_rbi_notifications",
        description=(
            "Collect RBI notifications and press releases from the official listing pages "
            "and ingest their rbidocs PDF URLs into the staging DB."
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
    parser.add_argument("--parser-version", default="rbi-listings-v1")
    parser.add_argument("--ssl-verify", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument(
        "--document-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If true, skip chunk/embedding/graph projections during ingestion.",
    )
    parser.add_argument("--log-every", type=int, default=10)
    return parser


def _headers(*, referer: str | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def _clean_html(value: str) -> str:
    cleaned = TAG_RE.sub(" ", html_unescape(value or ""))
    return " ".join(cleaned.split()).strip()


def _stable_external_id(label: str, pdf_url: str) -> str:
    tail = Path(urlparse(pdf_url).path).name or "document"
    return f"rbi-{label}-{tail}"


def _extract_entries(page_url: str, html: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    html = html_unescape(html)

    sections = list(SECTION_RE.finditer(html))
    if sections:
        for section in sections:
            date_text = _clean_html(section.group("date"))
            body = section.group("body")
            for row in ROW_RE.finditer(body):
                pdf_url = row.group("pdf_url").strip()
                if pdf_url in seen_urls:
                    continue
                seen_urls.add(pdf_url)
                entries.append(
                    {
                        "title": _clean_html(row.group("title")) or Path(urlparse(pdf_url).path).name,
                        "pdf_url": pdf_url,
                        "date_text": date_text,
                        "page_url": page_url,
                    }
                )
        return entries

    for row in ROW_RE.finditer(html):
        pdf_url = row.group("pdf_url").strip()
        if pdf_url in seen_urls:
            continue
        seen_urls.add(pdf_url)
        entries.append(
            {
                "title": _clean_html(row.group("title")) or Path(urlparse(pdf_url).path).name,
                "pdf_url": pdf_url,
                "date_text": "",
                "page_url": page_url,
            }
        )
    return entries


def _extract_detail_page_urls(page_url: str, html: str) -> list[str]:
    return sorted({urljoin(page_url, raw) for raw in DETAIL_PAGE_RE.findall(html)})


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

    successes = 0
    attempted = 0
    discovered = 0
    skipped_existing = 0
    seen_page_urls: set[str] = set()

    with Session(engine) as db_session:
        ensure_collection_control_schema(db_session)
        ensure_source_url_index(db_session)
        for listing in RBI_LISTINGS:
            if successes >= target:
                break

            page_url = listing["page_url"]
            try:
                response = http.get(
                    page_url,
                    headers=_headers(referer="https://www.rbi.org.in/"),
                    timeout=float(args.timeout_seconds),
                    verify=bool(args.ssl_verify),
                )
                response.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                print(f"[crawl-skip] url={page_url} err={type(exc).__name__}: {exc}", flush=True)
                continue

            pages_to_process: list[tuple[str, str]] = [(page_url, response.text)]
            for detail_page_url in _extract_detail_page_urls(page_url, response.text):
                if detail_page_url in seen_page_urls:
                    continue
                seen_page_urls.add(detail_page_url)
                try:
                    detail_response = http.get(
                        detail_page_url,
                        headers=_headers(referer=page_url),
                        timeout=float(args.timeout_seconds),
                        verify=bool(args.ssl_verify),
                    )
                    detail_response.raise_for_status()
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[detail-skip] url={detail_page_url} err={type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    continue
                pages_to_process.append((detail_page_url, detail_response.text))

            entries: list[dict[str, str]] = []
            for current_page_url, current_html in pages_to_process:
                partition_key = f"{listing['label']}|page:{current_page_url}"
                page_entries = _extract_entries(current_page_url, current_html)
                entries.extend(page_entries)
                record_source_partition(
                    db_session,
                    source_key="rbi",
                    partition_key=partition_key,
                    surface_url=current_page_url,
                    partition_kind="listing_page",
                    expected_hint=listing["label"],
                    discovered_increment=len(page_entries),
                    status=SourcePartitionStatus.RUNNING,
                    proof_note=f"discovered {len(page_entries)} pdf rows",
                    payload={"collector_type": "listing_html", "listing_label": listing["label"]},
                )
                db_session.commit()
            discovered += len(entries)
            for entry in entries:
                if successes >= target:
                    break

                attempted += 1
                pdf_url = entry["pdf_url"]
                partition_key = f"{listing['label']}|page:{entry['page_url']}"
                if document_exists_by_source_url(
                    db_session,
                    source_system="rbi",
                    source_url=pdf_url,
                ):
                    skipped_existing += 1
                    continue
                context = IngestionJobContext(
                    source_key="rbi",
                    source_url=pdf_url,
                    parser_version=str(args.parser_version),
                    external_id=_stable_external_id(listing["label"], pdf_url),
                    metadata={
                        "court_name": "Reserve Bank of India",
                        "doc_type": listing["doc_type"],
                        "practice_areas": ["banking"],
                        "jurisdiction_binding": ["All India"],
                        "jurisdiction_persuasive": ["All India"],
                        "title": entry["title"],
                        "date_text": entry["date_text"] or None,
                        "ssl_verify": bool(args.ssl_verify),
                        "seed_url": page_url,
                        "detail_url": entry["page_url"],
                        "artifact_url": pdf_url,
                        "source_surface": listing["label"],
                        "provenance_tier": "official",
                        "collector_type": "listing_html",
                        "partition_key": partition_key,
                        "partition_kind": "listing_page",
                        "partition_scheme": "listing_label_page",
                        "expected_proof_type": "listing_complete",
                        "http_headers": {"Referer": page_url},
                        "listing_label": listing["label"],
                        "collected_at": datetime.now(UTC).isoformat(),
                    },
                )
                try:
                    persisted = orchestrator.ingest(db_session, adapter, context)
                    record_source_partition(
                        db_session,
                        source_key="rbi",
                        partition_key=partition_key,
                        surface_url=entry["page_url"],
                        partition_kind="listing_page",
                        expected_hint=listing["label"],
                        ingested_increment=1,
                        status=SourcePartitionStatus.RUNNING,
                        proof_note=f"last_ingested={pdf_url}",
                        payload={"collector_type": "listing_html", "listing_label": listing["label"]},
                    )
                    db_session.commit()
                except Exception as exc:  # noqa: BLE001
                    db_session.rollback()
                    record_source_partition(
                        db_session,
                        source_key="rbi",
                        partition_key=partition_key,
                        surface_url=entry["page_url"],
                        partition_kind="listing_page",
                        expected_hint=listing["label"],
                        status=SourcePartitionStatus.BROKEN,
                        error_class=type(exc).__name__,
                        proof_note=f"ingest failed for {pdf_url}",
                        payload={"collector_type": "listing_html", "listing_label": listing["label"]},
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
            f"Only ingested {successes}/{target} PDFs "
            f"(attempted {attempted}, discovered {discovered}, skipped_existing {skipped_existing}) "
            f"from RBI listings."
        )
        if bool(args.allow_underfilled):
            print(msg, flush=True)
            return 0
        raise SystemExit(msg)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
