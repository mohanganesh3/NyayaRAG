from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from hashlib import sha256
from html import unescape as html_unescape
from pathlib import Path
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

CCI_BASE_URL = "https://www.cci.gov.in/"
CCI_LISTINGS: tuple[dict[str, object], ...] = (
    {
        "label": "antitrust",
        "endpoint": "https://www.cci.gov.in/antitrust/orders/list",
        "referer": "https://www.cci.gov.in/antitrust/orders",
        "file_fields": ("file_content",),
    },
    {
        "label": "combination_section31",
        "endpoint": "https://www.cci.gov.in/combination/orders-section31",
        "referer": "https://www.cci.gov.in/combination/orders-section31",
        "file_fields": ("order_file_content", "summary_file_content", "media_file_content"),
    },
    {
        "label": "combination_section43a_44",
        "endpoint": "https://www.cci.gov.in/combination/orders-section43a_44",
        "referer": "https://www.cci.gov.in/combination/orders-section43a_44",
        "file_fields": ("order_file_content", "summary_file_content", "media_file_content"),
    },
)


def _default_database_url() -> str:
    db_path = BACKEND_ROOT.parent / "data" / "collection" / "staging" / "cci.db"
    return f"sqlite+pysqlite:///{db_path}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collect_cci_orders",
        description=(
            "Collect Competition Commission of India order PDFs from the official "
            "DataTables-backed endpoints and ingest them into the staging DB."
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
    parser.add_argument("--parser-version", default="cci-orders-v1")
    parser.add_argument("--ssl-verify", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--page-size", type=int, default=100)
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
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer,
    }


def _iter_file_entries(row: dict[str, object], field_names: tuple[str, ...]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for field_name in field_names:
        raw = row.get(field_name)
        if not isinstance(raw, str) or not raw.strip() or raw.strip().lower() == "null":
            continue
        try:
            decoded = json.loads(html_unescape(raw))
        except Exception:
            continue
        if not isinstance(decoded, list):
            continue
        for item in decoded:
            if not isinstance(item, dict):
                continue
            file_name = str(item.get("file_name") or "").strip()
            if not file_name:
                continue
            title = str(item.get("title") or "").strip() or "Document"
            entries.append({"title": title, "file_name": file_name})
    return entries


def _row_date_text(row: dict[str, object]) -> str | None:
    for key in ("order_date", "main_order_date", "decision_date", "notification_date", "date_of_order"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _row_title(row: dict[str, object], file_title: str) -> str:
    pieces: list[str] = []
    for key in ("case_no", "combination_no", "title", "description", "party_name", "type", "section"):
        value = row.get(key)
        if isinstance(value, str):
            cleaned = " ".join(html_unescape(value).split())
            if cleaned and cleaned not in pieces:
                pieces.append(cleaned)
    if file_title and file_title not in pieces:
        pieces.append(file_title)
    if not pieces:
        return "CCI Order"
    return " | ".join(pieces[:3])


def _stable_external_id(label: str, row_id: object, file_name: str) -> str:
    file_tail = Path(file_name).name or sha256(file_name.encode("utf-8")).hexdigest()[:16]
    return f"cci-{label}-{row_id}-{file_tail}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    engine = build_engine(args.database_url)
    Base.metadata.create_all(engine)

    target = max(0, int(args.limit))
    if target == 0:
        print("--limit=0 so nothing to ingest.")
        return 0

    page_size = max(1, min(500, int(args.page_size)))
    adapter = PdfLegalDocumentAdapter()
    orchestrator = IngestionOrchestrator(document_only=bool(args.document_only))
    http = requests.Session()

    successes = 0
    attempted = 0
    discovered = 0
    seen_urls: set[str] = set()

    with Session(engine) as db_session:
        for listing in CCI_LISTINGS:
            if successes >= target:
                break

            endpoint = str(listing["endpoint"])
            referer = str(listing["referer"])
            field_names = tuple(str(field) for field in listing["file_fields"])
            start = 0

            while successes < target:
                params = {"draw": 1, "start": start, "length": page_size}
                try:
                    response = http.get(
                        endpoint,
                        params=params,
                        headers=_headers(referer=referer),
                        timeout=float(args.timeout_seconds),
                        verify=bool(args.ssl_verify),
                    )
                    response.raise_for_status()
                    payload = response.json()
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[api-skip] endpoint={endpoint} start={start} err={type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    break

                rows = payload.get("data")
                if not isinstance(rows, list) or not rows:
                    break

                for row in rows:
                    if successes >= target:
                        break
                    if not isinstance(row, dict):
                        continue

                    for file_entry in _iter_file_entries(row, field_names):
                        if successes >= target:
                            break
                        file_name = file_entry["file_name"]
                        pdf_url = urljoin(CCI_BASE_URL, file_name.lstrip("/"))
                        if pdf_url in seen_urls:
                            continue
                        seen_urls.add(pdf_url)
                        discovered += 1
                        attempted += 1
                        context = IngestionJobContext(
                            source_key="cci",
                            source_url=pdf_url,
                            parser_version=str(args.parser_version),
                            external_id=_stable_external_id(str(listing["label"]), row.get("id"), file_name),
                            metadata={
                                "court_name": "Competition Commission of India",
                                "doc_type": "order",
                                "practice_areas": ["competition"],
                                "jurisdiction_binding": ["All India"],
                                "jurisdiction_persuasive": ["All India"],
                                "title": _row_title(row, file_entry["title"]),
                                "date_text": _row_date_text(row),
                                "ssl_verify": bool(args.ssl_verify),
                                "seed_url": endpoint,
                                "http_headers": {"Referer": referer},
                                "listing_label": listing["label"],
                                "file_title": file_entry["title"],
                                "cci_row_id": row.get("id"),
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

                start += page_size

    if successes < target:
        msg = (
            f"Only ingested {successes}/{target} PDFs "
            f"(attempted {attempted}, discovered {discovered}) from CCI listings."
        )
        if bool(args.allow_underfilled):
            print(msg, flush=True)
            return 0
        raise SystemExit(msg)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
