from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import app.models as model_registry
import requests
from app.core.config import BACKEND_ROOT
from app.db.base import Base
from app.db.session import build_engine
from app.ingestion.adapters import PdfLegalDocumentAdapter
from app.ingestion.collector_utils import (
    document_exists_by_source_url,
    ensure_source_url_index,
)
from app.ingestion.contracts import IngestionJobContext
from app.ingestion.orchestrator import IngestionOrchestrator
from sqlalchemy.orm import Session

_ = model_registry

IRDAI_SECTIONS: tuple[dict[str, str], ...] = (
    {
        "label": "circulars",
        "listing_url": "https://irdai.gov.in/web/guest/circulars",
        "doc_type": "circular",
    },
    {
        "label": "notifications",
        "listing_url": "https://irdai.gov.in/web/guest/notifications",
        "doc_type": "notification",
    },
)

DETAIL_URL_RE = re.compile(
    r"(?:https://irdai\.gov\.in)?/(?:web/guest/)?document-detail\?documentId=\d+",
    re.IGNORECASE,
)
PAGINATION_URL_RE = re.compile(
    r"(?:https://irdai\.gov\.in)?/(?:web/guest/)?(?:circulars|notifications)[^\s\"'<>]*_cur=\d+",
    re.IGNORECASE,
)
PDF_URL_RE = re.compile(r"(?:https://irdai\.gov\.in)?/documents/[^\s\"']+\.pdf[^\s\"']*", re.IGNORECASE)
PDF_DATA_RE = re.compile(r"let\s+pdfDataArray\s*=\s*(\[[^\n;]+\]);", re.IGNORECASE | re.DOTALL)
HEADING_RE = re.compile(r"<strong[^>]*fileNameHeading[^>]*>(.*?)</strong>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")


def _default_database_url() -> str:
    db_path = BACKEND_ROOT.parent / "data" / "collection" / "staging" / "irdai.db"
    return f"sqlite+pysqlite:///{db_path}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collect_irdai_documents",
        description=(
            "Collect IRDAI circulars and notifications from the official document-detail "
            "pages and ingest their PDFs into the staging DB."
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
    parser.add_argument("--parser-version", default="irdai-documents-v1")
    parser.add_argument("--ssl-verify", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--max-listing-pages", type=int, default=200)
    parser.add_argument(
        "--document-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If true, skip chunk/embedding/graph projections during ingestion.",
    )
    parser.add_argument("--log-every", type=int, default=10)
    return parser


def _headers(*, referer: str) -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer,
    }


def _clean_html(value: str) -> str:
    return " ".join(TAG_RE.sub(" ", value or "").split()).strip()


def _cookie_header(http: requests.Session) -> str | None:
    parts = [f"{cookie.name}={cookie.value}" for cookie in http.cookies]
    return "; ".join(parts) or None


def _stable_external_id(pdf_url: str) -> str:
    tail = Path(pdf_url.split("?", 1)[0]).name
    return tail or f"irdai-{abs(hash(pdf_url))}"


def _detail_title(html: str, detail_url: str) -> str:
    match = HEADING_RE.search(html)
    if match:
        title = _clean_html(match.group(1))
        if title:
            return title
    return Path(detail_url.split("?", 1)[0]).name or "IRDAI Document"


def _detail_pdf_urls(html: str, *, base_url: str) -> list[str]:
    match = PDF_DATA_RE.search(html)
    if match:
        try:
            payload = json.loads(match.group(1))
        except Exception:
            payload = None
        if isinstance(payload, list):
            urls: list[str] = []
            for item in payload:
                if not isinstance(item, dict):
                    continue
                raw = item.get("url")
                if isinstance(raw, str) and raw.strip():
                    urls.append(urljoin(base_url, raw.strip()))
            if urls:
                return sorted(set(urls))
    return sorted({urljoin(base_url, raw.strip()) for raw in PDF_URL_RE.findall(html)})


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
    seen_listing_urls: set[str] = set()
    seen_detail_urls: set[str] = set()
    seen_pdf_urls: set[str] = set()

    with Session(engine) as db_session:
        ensure_source_url_index(db_session)
        for section in IRDAI_SECTIONS:
            if successes >= target:
                break

            listing_queue: list[str] = [section["listing_url"]]
            while listing_queue and len(seen_listing_urls) < int(args.max_listing_pages) and successes < target:
                listing_url = listing_queue.pop(0)
                if listing_url in seen_listing_urls:
                    continue
                seen_listing_urls.add(listing_url)

                try:
                    listing_response = http.get(
                        listing_url,
                        headers=_headers(referer="https://irdai.gov.in/"),
                        timeout=float(args.timeout_seconds),
                        verify=bool(args.ssl_verify),
                    )
                    listing_response.raise_for_status()
                except Exception as exc:  # noqa: BLE001
                    print(f"[listing-skip] url={listing_url} err={type(exc).__name__}: {exc}", flush=True)
                    continue

                listing_html = listing_response.text
                for page_url in PAGINATION_URL_RE.findall(listing_html):
                    page_url = urljoin(listing_url, page_url.strip())
                    if page_url not in seen_listing_urls:
                        listing_queue.append(page_url)

                for detail_url in DETAIL_URL_RE.findall(listing_html):
                    detail_url = urljoin(listing_url, detail_url.strip())
                    if successes >= target:
                        break
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
                        print(f"[detail-skip] url={detail_url} err={type(exc).__name__}: {exc}", flush=True)
                        continue

                    detail_html = detail_response.text
                    pdf_urls = _detail_pdf_urls(detail_html, base_url=detail_url)
                    discovered += len(pdf_urls)
                    title = _detail_title(detail_html, detail_url)
                    cookie_header = _cookie_header(http)

                    for pdf_url in pdf_urls:
                        if successes >= target:
                            break
                        if pdf_url in seen_pdf_urls:
                            continue
                        seen_pdf_urls.add(pdf_url)
                        if document_exists_by_source_url(
                            db_session,
                            source_system="irdai",
                            source_url=pdf_url,
                        ):
                            skipped_existing += 1
                            continue
                        context = IngestionJobContext(
                            source_key="irdai",
                            source_url=pdf_url,
                            parser_version=str(args.parser_version),
                            external_id=_stable_external_id(pdf_url),
                            metadata={
                                "court_name": "Insurance Regulatory and Development Authority of India",
                                "doc_type": section["doc_type"],
                                "practice_areas": ["insurance"],
                                "jurisdiction_binding": ["All India"],
                                "jurisdiction_persuasive": ["All India"],
                                "title": title,
                                "ssl_verify": bool(args.ssl_verify),
                                "http_headers": {
                                    **({"Cookie": cookie_header} if cookie_header else {}),
                                    "Referer": detail_url,
                                },
                                "seed_url": section["listing_url"],
                                "detail_url": detail_url,
                                "section_label": section["label"],
                                "collected_at": datetime.now(UTC).isoformat(),
                            },
                        )
                        try:
                            persisted = orchestrator.ingest(db_session, adapter, context)
                        except Exception as exc:  # noqa: BLE001
                            db_session.rollback()
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
            f"Only ingested {successes}/{target} IRDAI PDFs "
            f"(attempted {attempted}, discovered {discovered}, skipped_existing {skipped_existing})."
        )
        if bool(args.allow_underfilled):
            print(msg, flush=True)
            return 0
        raise SystemExit(msg)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
