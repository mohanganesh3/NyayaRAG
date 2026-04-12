from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from urllib.parse import urljoin

import app.models as model_registry
import requests
from app.core.config import BACKEND_ROOT
from app.db.base import Base
from app.db.session import build_engine
from app.ingestion.adapters import PdfLegalDocumentAdapter
from app.ingestion.contracts import IngestionJobContext
from app.ingestion.orchestrator import IngestionOrchestrator
from sqlalchemy.orm import Session

_ = model_registry

CBDT_BASE_URL = "https://www.incometaxindia.gov.in"
CBDT_SITE_ID = "20117"
CBDT_CIRCULAR_STRUCTURE_ID = "36050"


def _default_database_url() -> str:
    db_path = BACKEND_ROOT.parent / "data" / "collection" / "staging" / "cbdt.db"
    return f"sqlite+pysqlite:///{db_path}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collect_cbdt_circulars",
        description=(
            "Collect CBDT circular PDFs from incometaxindia.gov.in (Liferay) and ingest them into a staging DB. "
            "Uses the public headless-delivery API to enumerate circular items and downloads their reportFile PDFs."
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
    parser.add_argument("--parser-version", default="cbdt-circulars-v1")
    parser.add_argument("--ssl-verify", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="Start from this Liferay API page (1-indexed).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=200,
        help="Hard cap on API pages to scan (safety guard).",
    )
    return parser


def _api_url() -> str:
    return f"{CBDT_BASE_URL}/o/headless-delivery/v1.0/sites/{CBDT_SITE_ID}/structured-contents"


def _headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{CBDT_BASE_URL}/circulars",
    }


def _extract_cf_data(item: dict[str, Any], field_name: str) -> str | None:
    content_fields = item.get("contentFields")
    if not isinstance(content_fields, list):
        return None
    for cf in content_fields:
        if not isinstance(cf, dict):
            continue
        if str(cf.get("name") or "") != field_name:
            continue
        cfv = cf.get("contentFieldValue")
        if isinstance(cfv, dict):
            value = cfv.get("data")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _extract_report_content_url(item: dict[str, Any]) -> str | None:
    content_fields = item.get("contentFields")
    if not isinstance(content_fields, list):
        return None
    for cf in content_fields:
        if not isinstance(cf, dict):
            continue
        if str(cf.get("name") or "") != "reportFile":
            continue
        cfv = cf.get("contentFieldValue")
        if not isinstance(cfv, dict):
            return None
        document = cfv.get("document")
        if not isinstance(document, dict):
            return None
        content_url = document.get("contentUrl")
        if isinstance(content_url, str) and content_url.strip():
            return content_url.strip()
    return None


def _stable_external_id(item: dict[str, Any], pdf_url: str) -> str:
    # Prefer the structured-content ID (stable); fall back to content hash.
    raw_id = item.get("id")
    if isinstance(raw_id, (int, str)) and str(raw_id).strip():
        return f"cbdt-{str(raw_id).strip()}"
    return f"cbdt-{sha256(pdf_url.encode('utf-8')).hexdigest()[:16]}"


def _iso_date_to_date_text(value: str | None) -> str | None:
    if not value:
        return None
    # Liferay emits ISO8601 like 2013-12-16T00:00:00Z.
    if len(value) >= 10 and value[4] == "-" and value[7] == "-":
        return value[:10]
    return value


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    engine = build_engine(args.database_url)
    Base.metadata.create_all(engine)

    target = max(0, int(args.limit))
    if target == 0:
        print("--limit=0 so nothing to ingest.")
        return 0

    page_size = max(1, min(200, int(args.page_size)))
    start_page = max(1, int(args.start_page))
    max_pages = max(1, int(args.max_pages))

    adapter = PdfLegalDocumentAdapter()
    orchestrator = IngestionOrchestrator()

    filter_expr = f"contentStructureId eq {CBDT_CIRCULAR_STRUCTURE_ID}"

    successes = 0
    attempted = 0
    scanned_pages = 0

    session = requests.Session()

    with Session(engine) as db_session:
        for page in range(start_page, start_page + max_pages):
            scanned_pages += 1
            params = {
                "flatten": "true",
                "filter": filter_expr,
                "page": str(page),
                "pageSize": str(page_size),
            }
            try:
                resp = session.get(
                    _api_url(),
                    params=params,
                    headers=_headers(),
                    timeout=float(args.timeout_seconds),
                    verify=bool(args.ssl_verify),
                )
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:  # noqa: BLE001 - collector should be resilient
                print(f"[api-skip] page={page} err={type(exc).__name__}: {exc}", flush=True)
                continue

            items = payload.get("items")
            if not isinstance(items, list):
                print(f"[api-skip] page={page} err=UnexpectedResponse", flush=True)
                continue
            if not items:
                # No more results.
                break

            for item in items:
                if successes >= target:
                    break
                if not isinstance(item, dict):
                    continue

                report_content_url = _extract_report_content_url(item)
                if not report_content_url:
                    continue
                pdf_url = urljoin(CBDT_BASE_URL, report_content_url)

                circular_number = _extract_cf_data(item, "circularNotificationNumber")
                circular_date = _iso_date_to_date_text(
                    _extract_cf_data(item, "circularNotificationDate")
                )
                upload_date = _iso_date_to_date_text(_extract_cf_data(item, "uploadDate"))
                title = circular_number or item.get("title") or "CBDT Circular"

                attempted += 1
                context = IngestionJobContext(
                    source_key="cbdt",
                    source_url=pdf_url,
                    parser_version=str(args.parser_version),
                    external_id=_stable_external_id(item, pdf_url),
                    metadata={
                        "court_name": "CBDT (incometaxindia.gov.in)",
                        "doc_type": "circular",
                        "practice_areas": ["tax"],
                        "jurisdiction_binding": ["All India"],
                        "jurisdiction_persuasive": ["All India"],
                        "title": str(title),
                        # Prefer circular date, fall back to upload date.
                        "date_text": circular_date or upload_date,
                        "citation": circular_number,
                        "ssl_verify": bool(args.ssl_verify),
                        "liferay": {
                            "structured_content_id": item.get("id"),
                            "content_structure_id": item.get("contentStructureId"),
                            "circular_number": circular_number,
                            "circular_date": circular_date,
                            "upload_date": upload_date,
                        },
                        "collected_at": datetime.now(UTC).isoformat(),
                    },
                )

                try:
                    persisted = orchestrator.ingest(db_session, adapter, context)
                except Exception as exc:  # noqa: BLE001 - best-effort collection
                    db_session.rollback()
                    print(
                        f"[skip] url={pdf_url} err={type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    continue

                successes += 1
                print(
                    f"[{successes}/{target}] ingested doc_id={persisted.doc_id} url={pdf_url}",
                    flush=True,
                )

            if successes >= target:
                break

        if successes < target:
            msg = (
                f"Only ingested {successes}/{target} PDFs (attempted {attempted}, "
                f"scanned_pages={scanned_pages}, page_size={page_size})."
            )
            if bool(args.allow_underfilled):
                print(msg, flush=True)
                return 0
            raise SystemExit(msg)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
