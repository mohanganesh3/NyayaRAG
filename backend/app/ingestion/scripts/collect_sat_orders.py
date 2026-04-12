from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from hashlib import sha256
from html import unescape as html_unescape
from urllib.parse import urlparse

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

SAT_ORDERS_URL = "https://satweb.sat.gov.in/orders"
SAT_DATE_SEARCH_URL = "https://satweb.sat.gov.in/get-orders-by-date"
VIEW_URL_RE = re.compile(r'href="(https://satweb\.sat\.gov\.in/view-order/[^"]+)"', re.IGNORECASE)
TOKEN_RE = re.compile(r'id="security_token"\s+value="([^"]+)"', re.IGNORECASE)
ROW_RE = re.compile(
    r"<tr>\s*"
    r"<td>\s*(?P<serial>.*?)\s*</td>\s*"
    r"<td>\s*(?P<al_no>.*?)\s*</td>\s*"
    r"<td[^>]*>\s*(?P<appeal_no>.*?)\s*</td>\s*"
    r"<td>\s*(?P<parties>.*?)\s*</td>\s*"
    r"<td>\s*(?P<court>.*?)\s*</td>\s*"
    r"<td>\s*(?P<order_date>.*?)\s*</td>\s*"
    r"<td>\s*<a\s+href=\"(?P<view_url>https://satweb\.sat\.gov\.in/view-order/[^\"]+)\"",
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")


def _default_database_url() -> str:
    db_path = BACKEND_ROOT.parent / "data" / "collection" / "staging" / "sat.db"
    return f"sqlite+pysqlite:///{db_path}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collect_sat_orders",
        description=(
            "Collect Securities Appellate Tribunal orders from the live date-search endpoint "
            "and ingest them into the staging DB."
        ),
    )
    parser.add_argument("--database-url", default=_default_database_url())
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--allow-underfilled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If true, do not exit non-zero when fewer than --limit orders are ingested.",
    )
    parser.add_argument("--parser-version", default="sat-orders-v1")
    parser.add_argument("--ssl-verify", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--start-year", type=int, default=1995)
    parser.add_argument("--end-year", type=int, default=datetime.now(UTC).year)
    parser.add_argument(
        "--appeal-type",
        action="append",
        default=[],
        help="Appeal type codes from the SAT portal (defaults to 1,2,3).",
    )
    parser.add_argument(
        "--document-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If true, skip chunk/embedding/graph projections during ingestion.",
    )
    parser.add_argument("--log-every", type=int, default=10)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    return parser


def _headers(*, referer: str = SAT_ORDERS_URL, xhr: bool = False) -> dict[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*" if xhr else "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer,
    }
    if xhr:
        headers["X-Requested-With"] = "XMLHttpRequest"
    return headers


def _clean_html(value: str) -> str:
    cleaned = TAG_RE.sub(" ", html_unescape(value or ""))
    return " ".join(cleaned.split()).strip()


def _refresh_token(http: requests.Session, *, timeout_seconds: float, ssl_verify: bool) -> str:
    response = http.get(
        SAT_ORDERS_URL,
        headers=_headers(),
        timeout=timeout_seconds,
        verify=ssl_verify,
    )
    response.raise_for_status()
    match = TOKEN_RE.search(response.text)
    if not match:
        raise RuntimeError("SAT security token not found on orders page")
    return match.group(1).strip()


def _query_year(
    http: requests.Session,
    *,
    appeal_type: str,
    year: int,
    token: str,
    timeout_seconds: float,
    ssl_verify: bool,
) -> tuple[str, list[dict[str, str]]]:
    data = {
        "apl_type": appeal_type,
        "startDate": f"01-01-{year}",
        "endDate": f"31-12-{year}",
        "security_token": token,
    }
    response = http.post(
        SAT_DATE_SEARCH_URL,
        data=data,
        headers=_headers(xhr=True),
        timeout=timeout_seconds,
        verify=ssl_verify,
    )
    response.raise_for_status()
    payload = response.json()
    next_token = str(payload.get("token") or "").strip()
    content = str(payload.get("content") or "")
    if "Invalid token" in content:
        raise RuntimeError("SAT portal rejected the security token")

    rows: list[dict[str, str]] = []
    for match in ROW_RE.finditer(content):
        rows.append(
            {
                "appeal_type": appeal_type,
                "year": str(year),
                "al_no": _clean_html(match.group("al_no")),
                "appeal_no": _clean_html(match.group("appeal_no")),
                "parties": _clean_html(match.group("parties")),
                "court": _clean_html(match.group("court")),
                "order_date": _clean_html(match.group("order_date")),
                "view_url": match.group("view_url").strip(),
            }
        )

    if not rows:
        for url in VIEW_URL_RE.findall(content):
            rows.append(
                {
                    "appeal_type": appeal_type,
                    "year": str(year),
                    "al_no": "",
                    "appeal_no": "",
                    "parties": "",
                    "court": "",
                    "order_date": "",
                    "view_url": url.strip(),
                }
            )

    return next_token or token, rows


def _download_pdf_bytes(
    http: requests.Session,
    *,
    view_url: str,
    timeout_seconds: float,
    ssl_verify: bool,
) -> bytes:
    response = http.get(
        view_url,
        headers=_headers(),
        timeout=timeout_seconds,
        verify=ssl_verify,
        allow_redirects=True,
    )
    response.raise_for_status()
    if "application/pdf" not in (response.headers.get("content-type") or "").lower():
        if not response.content.lstrip().startswith(b"%PDF"):
            raise RuntimeError("SAT view-order response was not a PDF")
    return response.content


def _stable_external_id(view_url: str) -> str:
    parsed = urlparse(view_url)
    tail = parsed.path.rstrip("/").split("/")[-1]
    digest = sha256(view_url.encode("utf-8")).hexdigest()[:16]
    return f"sat-{tail}-{digest}"


def _title_for_row(row: dict[str, str]) -> str:
    pieces = [row.get("appeal_no", ""), row.get("parties", ""), row.get("court", "")]
    title = " | ".join(piece for piece in pieces if piece)
    return title or f"SAT Order {row.get('view_url', '').rstrip('/').split('/')[-1]}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    engine = build_engine(args.database_url)
    Base.metadata.create_all(engine)

    target = max(0, int(args.limit))
    if target == 0:
        print("--limit=0 so nothing to ingest.")
        return 0

    appeal_types = [str(value).strip() for value in (args.appeal_type or []) if str(value).strip()]
    if not appeal_types:
        appeal_types = ["1", "2", "3"]

    start_year = int(args.start_year)
    end_year = int(args.end_year)
    if start_year > end_year:
        start_year, end_year = end_year, start_year

    adapter = PdfLegalDocumentAdapter()
    orchestrator = IngestionOrchestrator(document_only=bool(args.document_only))
    http = requests.Session()

    successes = 0
    attempted = 0
    discovered = 0
    seen_urls: set[str] = set()
    token = _refresh_token(
        http,
        timeout_seconds=float(args.timeout_seconds),
        ssl_verify=bool(args.ssl_verify),
    )

    with Session(engine) as db_session:
        for year in range(end_year, start_year - 1, -1):
            if successes >= target:
                break
            for appeal_type in appeal_types:
                if successes >= target:
                    break

                try:
                    token, rows = _query_year(
                        http,
                        appeal_type=appeal_type,
                        year=year,
                        token=token,
                        timeout_seconds=float(args.timeout_seconds),
                        ssl_verify=bool(args.ssl_verify),
                    )
                except Exception:
                    token = _refresh_token(
                        http,
                        timeout_seconds=float(args.timeout_seconds),
                        ssl_verify=bool(args.ssl_verify),
                    )
                    try:
                        token, rows = _query_year(
                            http,
                            appeal_type=appeal_type,
                            year=year,
                            token=token,
                            timeout_seconds=float(args.timeout_seconds),
                            ssl_verify=bool(args.ssl_verify),
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(
                            f"[query-skip] appeal_type={appeal_type} year={year} "
                            f"err={type(exc).__name__}: {exc}",
                            flush=True,
                        )
                        continue

                discovered += len(rows)
                for row in rows:
                    if successes >= target:
                        break
                    view_url = row["view_url"]
                    if view_url in seen_urls:
                        continue
                    seen_urls.add(view_url)
                    attempted += 1
                    try:
                        pdf_bytes = _download_pdf_bytes(
                            http,
                            view_url=view_url,
                            timeout_seconds=float(args.timeout_seconds),
                            ssl_verify=bool(args.ssl_verify),
                        )
                        extracted_text = adapter._extract_pdf_text(pdf_bytes)
                    except Exception as exc:  # noqa: BLE001
                        print(f"[skip] url={view_url} err={type(exc).__name__}: {exc}", flush=True)
                        continue

                    context = IngestionJobContext(
                        source_key="sat",
                        source_url=view_url,
                        parser_version=str(args.parser_version),
                        external_id=_stable_external_id(view_url),
                        inline_payload=extracted_text,
                        metadata={
                            "court_name": "Securities Appellate Tribunal",
                            "doc_type": "order",
                            "practice_areas": ["securities"],
                            "jurisdiction_binding": ["All India"],
                            "jurisdiction_persuasive": ["All India"],
                            "title": _title_for_row(row),
                            "date_text": row.get("order_date") or None,
                            "ssl_verify": bool(args.ssl_verify),
                            "appeal_type": row.get("appeal_type"),
                            "al_no": row.get("al_no"),
                            "appeal_no": row.get("appeal_no"),
                            "parties": row.get("parties"),
                            "court_label": row.get("court"),
                            "seed_url": SAT_ORDERS_URL,
                            "collected_at": datetime.now(UTC).isoformat(),
                        },
                    )
                    try:
                        persisted = orchestrator.ingest(db_session, adapter, context)
                    except Exception as exc:  # noqa: BLE001
                        db_session.rollback()
                        print(f"[skip] url={view_url} err={type(exc).__name__}: {exc}", flush=True)
                        continue

                    successes += 1
                    if int(args.log_every) > 0 and successes % int(args.log_every) == 0:
                        print(
                            f"[{successes}/{target}] ingested doc_id={persisted.doc_id} url={view_url}",
                            flush=True,
                        )

    if successes < target:
        msg = (
            f"Only ingested {successes}/{target} SAT orders "
            f"(attempted {attempted}, discovered {discovered})."
        )
        if bool(args.allow_underfilled):
            print(msg, flush=True)
            return 0
        raise SystemExit(msg)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
