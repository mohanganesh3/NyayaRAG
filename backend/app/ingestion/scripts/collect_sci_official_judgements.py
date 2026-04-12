from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from html import unescape as html_unescape
from pathlib import Path
from time import sleep
from urllib.parse import urljoin
from urllib.parse import urlencode

import requests
import logging
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

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
from app.models import SourcePartition, SourcePartitionStatus
from sqlalchemy import select, text
from sqlalchemy.orm import Session

_ = model_registry

BASE_URLS = (
    "https://www.sci.gov.in",
    "https://main.sci.gov.in",
)
FREE_TEXT_PATH = "/free-text-judgements/"
AJAX_PATH = "/wp-admin/admin-ajax.php"
DEFAULT_OCR_PYTHON = "/home/mohanganesh/project002/backend/.venv/bin/python3"

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_TITLE_DATE_RE = re.compile(r"^(?P<title>.*?)(?:\s*/\s*(?P<date>\d{2}-\d{2}-\d{4}))?$")
_ROW_PAIR_RE = re.compile(
    r'<tr id="(?P<row_id>[a-f0-9]+)" class="dailyOrderFreeText">(?P<row_html>.*?)</tr>\s*'
    r'<tr id="freeText(?P=row_id)"[^>]*>(?P<detail_html>.*?)</tr>',
    re.IGNORECASE | re.DOTALL,
)
_PDF_URL_RE = re.compile(
    r'href="(?P<pdf_url>https://api\.sci\.gov\.in/[^"]+\.pdf)"',
    re.IGNORECASE,
)
_COURT_NO_RE = re.compile(r"\bCOURT\s+NO\.?\s*([A-Z0-9-]+)\b", re.IGNORECASE)
_CASE_NUMBER_RE = re.compile(
    r"\b(?:Petition(?:\(s\))?|Civil Appeal|Criminal Appeal|Diary No\.?|Writ Petition|Special Leave Petition)[^.\n]*",
    re.IGNORECASE,
)


@dataclass(slots=True)
class SearchRow:
    row_id: str
    title: str
    date_text: str | None
    pdf_url: str
    preview_text: str
    court_no: str | None
    case_number: str | None


def _default_database_url() -> str:
    db_path = BACKEND_ROOT.parent / "data" / "collection" / "staging" / "sc_supreme_court_official.db"
    return f"sqlite+pysqlite:///{db_path}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collect_sci_official_judgements",
        description="Collect Supreme Court judgments from the official SCI free-text AJAX search.",
    )
    parser.add_argument("--database-url", default=_default_database_url())
    parser.add_argument("--ocr-python", default=DEFAULT_OCR_PYTHON)
    parser.add_argument(
        "--ocr-helper-script",
        default=str(BACKEND_ROOT / "app/ingestion/scripts/solve_itat_captcha.py"),
    )
    parser.add_argument("--start-date", default="1950-01-26")
    parser.add_argument("--end-date", default=(datetime.now(UTC).date() - timedelta(days=1)).isoformat())
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--query", action="append", dest="queries", default=[])
    parser.add_argument("--limit", type=int, default=500000)
    parser.add_argument("--query-limit", type=int, default=0)
    parser.add_argument("--max-pages-per-window", type=int, default=200)
    parser.add_argument("--captcha-attempts", type=int, default=8)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--sleep-seconds", type=float, default=0.05)
    parser.add_argument("--parser-version", default="supreme-court-sci-free-text-v1")
    parser.add_argument(
        "--base-url",
        action="append",
        dest="base_urls",
        default=[],
        help="Optional SCI hosts to try in order. Defaults to the known official hosts.",
    )
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
        help="If true (default), do not exit non-zero when fewer than --limit docs ingest.",
    )
    parser.add_argument("--log-every", type=int, default=10)
    return parser


def _free_text_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}{FREE_TEXT_PATH}"


def _ajax_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}{AJAX_PATH}"


def _headers(referer: str) -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer,
        "X-Requested-With": "XMLHttpRequest",
    }


def _clean(fragment: str | None) -> str:
    if not fragment:
        return ""
    return _WHITESPACE_RE.sub(" ", _TAG_RE.sub(" ", html_unescape(fragment))).strip()


def _parse_iso_date(value: str) -> date:
    return date.fromisoformat(value)


def _format_query_date(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def _normalize_query_term(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def _iter_windows(start_date: date, end_date: date, window_days: int) -> list[tuple[date, date]]:
    if end_date < start_date:
        return []
    span = max(1, int(window_days))
    cursor = end_date
    windows: list[tuple[date, date]] = []
    while cursor >= start_date:
        window_start = max(start_date, cursor - timedelta(days=span - 1))
        windows.append((window_start, cursor))
        cursor = window_start - timedelta(days=1)
    return windows


def _partition_key(query: str, window_start: date, window_end: date) -> str:
    return f"query:{query}|from:{window_start.isoformat()}|to:{window_end.isoformat()}"


def _partition_exists(session: Session, *, partition_key: str, surface_url: str) -> bool:
    row = session.execute(
        select(SourcePartition.status).where(
            SourcePartition.source_key == "supreme_court",
            SourcePartition.partition_key == partition_key,
            SourcePartition.surface_url == surface_url,
        )
    ).scalar_one_or_none()
    return row in {SourcePartitionStatus.DONE, SourcePartitionStatus.VERIFIED}


class OCRClient:
    def __init__(self, python_path: str, helper_script: str) -> None:
        self._proc = subprocess.Popen(
            [python_path, helper_script, "--server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

    def solve(self, image_bytes: bytes) -> str:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            handle.write(image_bytes)
            path = handle.name
        try:
            assert self._proc.stdin is not None
            assert self._proc.stdout is not None
            self._proc.stdin.write(path + "\n")
            self._proc.stdin.flush()
            line = self._proc.stdout.readline().strip()
            if not line or line.startswith("ERROR:"):
                return ""
            return line
        finally:
            Path(path).unlink(missing_ok=True)

    def close(self) -> None:
        if self._proc.stdin:
            self._proc.stdin.close()
        if self._proc.stdout:
            self._proc.stdout.close()
        self._proc.terminate()


def _captcha_answer(raw_guess: str) -> str:
    guess = raw_guess.strip()
    match = re.fullmatch(r"\s*(\d+)\s*([+\-xX*])\s*(\d+)\s*", guess)
    if match is None:
        return guess
    left, operator, right = match.groups()
    lhs = int(left)
    rhs = int(right)
    if operator == "+":
        return str(lhs + rhs)
    if operator == "-":
        return str(lhs - rhs)
    return str(lhs * rhs)


def _form_tokens(page_html: str, *, page_url: str) -> tuple[str, str, str, str]:
    scid = re.search(r'name="scid"[^>]+value="([^"]+)"', page_html)
    token = re.search(r'name="(_token|tok_[^"]+)"[^>]+value="([^"]+)"', page_html)
    image = re.search(r'<img[^>]+src="([^"]*captcha[^"]+)"', page_html)

    if scid is None or token is None or image is None:
        raise RuntimeError("SCI free-text form tokens are missing")

    captcha_url = urljoin(page_url, html_unescape(image.group(1)))
    return scid.group(1), token.group(1), token.group(2), captcha_url


def _request_results(
    http: requests.Session,
    *,
    ajax_url: str,
    referer: str,
    payload: dict[str, str],
    timeout_seconds: float,
) -> dict[str, object]:
    response = http.get(
        ajax_url,
        params=payload,
        headers=_headers(referer),
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    return response.json()


def _first_page_payload_and_response(
    http: requests.Session,
    *,
    base_urls: list[str],
    query: str,
    window_start: date,
    window_end: date,
    client: OCRClient,
    timeout_seconds: float,
    captcha_attempts: int,
) -> tuple[dict[str, str] | None, dict[str, object] | None, str | None, str | None]:
    host_errors: list[str] = []
    for base_url in base_urls:
        free_text_url = _free_text_url(base_url)
        ajax_url = _ajax_url(base_url)
        for _ in range(max(1, int(captcha_attempts))):
            try:
                page = http.get(free_text_url, headers=_headers(free_text_url), timeout=timeout_seconds)
                page.raise_for_status()
                scid, token_name, token_value, captcha_url = _form_tokens(page.text, page_url=page.url)

                image = http.get(captcha_url, headers=_headers(free_text_url), timeout=timeout_seconds)
                image.raise_for_status()
                raw_guess = client.solve(image.content)
                answer = _captcha_answer(raw_guess)
                if not answer:
                    continue

                payload = {
                    "action": "get_judgements_free_text",
                    "search_text": query,
                    "from_date": _format_query_date(window_start),
                    "to_date": _format_query_date(window_end),
                    "es_ajax_request": "1",
                    "scid": scid,
                    token_name: token_value,
                    "siwp_captcha_value": answer,
                    "_ch_field": "",
                }
                data = _request_results(
                    http,
                    ajax_url=ajax_url,
                    referer=free_text_url,
                    payload=payload,
                    timeout_seconds=timeout_seconds,
                )
                if bool(data.get("success")):
                    return payload, data, None, base_url

                message = str(data.get("data") or "")
                if "captcha code entered was incorrect" in message.lower():
                    continue
                return payload, None, message, base_url
            except Exception as exc:  # noqa: BLE001
                host_errors.append(f"{base_url}: {exc}")
                break
    if host_errors:
        return None, None, "; ".join(host_errors), None
    return None, None, "captcha could not be solved within attempt budget", None


def _extract_rows(results_html: str) -> list[SearchRow]:
    rows: list[SearchRow] = []
    for match in _ROW_PAIR_RE.finditer(results_html):
        row_html = match.group("row_html")
        detail_html = match.group("detail_html")
        pdf_match = _PDF_URL_RE.search(detail_html)
        if pdf_match is None:
            continue
        title_match = re.search(r"<td>\s*(.*?)\s*</td>", row_html, re.IGNORECASE | re.DOTALL)
        title_text = _clean(title_match.group(1) if title_match else "")
        if not title_text:
            continue
        title_bits = _TITLE_DATE_RE.match(title_text)
        if title_bits is not None:
            title = _normalize_query_term(title_bits.group("title") or title_text)
            date_text = title_bits.group("date")
        else:
            title = title_text
            date_text = None

        preview_html = re.sub(
            r"<div>.*?</div>",
            "",
            detail_html,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
        preview_text = _clean(preview_html)
        court_match = _COURT_NO_RE.search(preview_text)
        case_number_match = _CASE_NUMBER_RE.search(preview_text)

        rows.append(
            SearchRow(
                row_id=match.group("row_id"),
                title=title,
                date_text=date_text,
                pdf_url=pdf_match.group("pdf_url"),
                preview_text=preview_text,
                court_no=(f"Court No. {court_match.group(1)}" if court_match else None),
                case_number=_normalize_query_term(case_number_match.group(0)) if case_number_match else None,
            )
        )
    return rows


def _decision_date_iso(date_text: str | None) -> str | None:
    if not date_text:
        return None
    try:
        return datetime.strptime(date_text, "%d-%m-%Y").date().isoformat()
    except ValueError:
        return None


def _split_parties(title: str) -> dict[str, str]:
    for token in (" VS. ", " VS ", " VERSUS ", " vs. ", " vs ", " versus "):
        if token in title:
            left, right = title.split(token, 1)
            left = _normalize_query_term(left)
            right = _normalize_query_term(right)
            if left and right:
                return {"appellant": left, "respondent": right}
    return {"appellant": title} if title else {}


def _external_id(pdf_url: str) -> str:
    return Path(pdf_url).name


def _surface_url(base_url: str, query: str, window_start: date, window_end: date, page: int) -> str:
    return f"{_free_text_url(base_url)}?{urlencode({'query': query, 'from': window_start.isoformat(), 'to': window_end.isoformat(), 'page': page})}"


def _ingest_rows(
    db_session: Session,
    *,
    rows: list[SearchRow],
    base_url: str,
    source_surface: str,
    partition_key: str,
    query: str,
    parser_version: str,
    orchestrator: IngestionOrchestrator,
    adapter: PdfLegalDocumentAdapter,
    existing_urls: set[str],
) -> tuple[int, int, int]:
    discovered = 0
    attempted = 0
    ingested = 0
    seen: set[str] = set()

    for row in rows:
        if row.pdf_url in seen:
            continue
        seen.add(row.pdf_url)
        discovered += 1

        if row.pdf_url in existing_urls or document_exists_by_source_url(
            db_session,
            source_system="supreme_court",
            source_url=row.pdf_url,
        ):
            existing_urls.add(row.pdf_url)
            continue

        attempted += 1
        decision_date = _decision_date_iso(row.date_text)
        external_id = _external_id(row.pdf_url)
        bench = [row.court_no] if row.court_no else []
        context = IngestionJobContext(
            source_key="supreme_court",
            source_url=row.pdf_url,
            parser_version=parser_version,
            external_id=external_id,
            metadata={
                "court_name": "Supreme Court of India",
                "doc_type": "judgment",
                "practice_areas": [],
                "jurisdiction_binding": ["Supreme Court of India"],
                "jurisdiction_persuasive": ["All India"],
                "title": row.title,
                "date_text": row.date_text,
                "decision_date": decision_date,
                "seed_url": _free_text_url(base_url),
                "detail_url": source_surface,
                "artifact_url": row.pdf_url,
                "source_surface": source_surface,
                "provenance_tier": "official",
                "source_document_ref": external_id,
                "citation": row.case_number,
                "parties": _split_parties(row.title),
                "bench": bench,
                "collector_type": "ajax_captcha_search_collector",
                "partition_key": partition_key,
                "partition_kind": "free_text_date_window",
                "partition_scheme": "query_term_x_date_window_x_page",
                "expected_proof_type": "window_page_closure",
                "case_number": row.case_number,
                "search_query": query,
            },
        )
        try:
            orchestrator.ingest(db_session, adapter, context)
            db_session.commit()
            ingested += 1
            existing_urls.add(row.pdf_url)
        except Exception:
            db_session.rollback()
            continue

    return discovered, attempted, ingested


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target = max(0, int(args.limit))
    if target == 0:
        print("--limit=0 so nothing to ingest.")
        return 0

    start_date = _parse_iso_date(args.start_date)
    end_date = _parse_iso_date(args.end_date)
    window_days = max(1, int(args.window_days))
    queries = [_normalize_query_term(item) for item in (args.queries or ["vs"]) if _normalize_query_term(item)]
    if not queries:
        queries = ["vs"]
    base_urls = [
        item.rstrip("/")
        for item in (args.base_urls or list(BASE_URLS))
        if _normalize_query_term(item)
    ]
    if not base_urls:
        base_urls = list(BASE_URLS)

    engine = build_engine(args.database_url)
    Base.metadata.create_all(engine)

    adapter = PdfLegalDocumentAdapter()
    orchestrator = IngestionOrchestrator(document_only=bool(args.document_only))
    http = requests.Session()
    http.verify = False
    http.headers.update(_headers(_free_text_url(base_urls[0])))
    ocr_client = OCRClient(args.ocr_python, args.ocr_helper_script)

    total_discovered = 0
    total_attempted = 0
    total_ingested = 0
    total_queries = 0

    try:
        with Session(engine) as db_session:
            ensure_collection_control_schema(db_session)
            ensure_source_url_index(db_session)
            existing_urls = {
                str(source_url)
                for (source_url,) in db_session.execute(
                    text(
                        "SELECT source_url FROM legal_documents "
                        "WHERE source_system = 'supreme_court' AND source_url IS NOT NULL"
                    )
                ).fetchall()
                if source_url
            }

            windows = _iter_windows(start_date, end_date, window_days)
            for query in queries:
                for window_start, window_end in windows:
                    if total_ingested >= target:
                        break
                    if int(args.query_limit) > 0 and total_queries >= int(args.query_limit):
                        break

                    partition_key = _partition_key(query, window_start, window_end)
                    surface_url = _surface_url(base_urls[0], query, window_start, window_end, 1)
                    if _partition_exists(
                        db_session,
                        partition_key=partition_key,
                        surface_url=surface_url,
                    ):
                        continue

                    total_queries += 1
                    print(
                        f"[sci-free-text] query={total_queries} term={query!r} "
                        f"from={window_start.isoformat()} to={window_end.isoformat()}",
                        flush=True,
                    )

                    payload, first_page, error_message, active_base_url = _first_page_payload_and_response(
                        http,
                        base_urls=base_urls,
                        query=query,
                        window_start=window_start,
                        window_end=window_end,
                        client=ocr_client,
                        timeout_seconds=float(args.timeout_seconds),
                        captcha_attempts=max(1, int(args.captcha_attempts)),
                    )
                    if first_page is None:
                        status = (
                            SourcePartitionStatus.VERIFIED
                            if error_message and "nothing found" in error_message.lower()
                            else SourcePartitionStatus.BROKEN
                        )
                        record_source_partition(
                            db_session,
                            source_key="supreme_court",
                            partition_key=partition_key,
                            surface_url=surface_url,
                            partition_kind="free_text_date_window",
                            expected_hint=f"{query}:{window_start.isoformat()}->{window_end.isoformat()}",
                            status=status,
                            error_class="CaptchaSolveFailed" if payload is None else None,
                            proof_note=error_message,
                            payload={
                                "collector_type": "ajax_captcha_search_collector",
                                "partition_scheme": "query_term_x_date_window_x_page",
                                "query": query,
                                "window_start": window_start.isoformat(),
                                "window_end": window_end.isoformat(),
                            },
                        )
                        db_session.commit()
                        continue
                    assert active_base_url is not None
                    surface_url = _surface_url(active_base_url, query, window_start, window_end, 1)

                    partition_discovered = 0
                    partition_attempted = 0
                    partition_ingested = 0
                    pages_seen: list[int] = []
                    previous_ids: set[str] = set()
                    broken_message: str | None = None

                    for page_number in range(1, max(1, int(args.max_pages_per_window)) + 1):
                        if page_number == 1:
                            page_data = first_page
                        else:
                            page_payload = dict(payload)
                            page_payload["sci_page"] = str(page_number)
                            page_payload["sci_pagination_nonce"] = ""
                            try:
                                page_data = _request_results(
                                    http,
                                    ajax_url=_ajax_url(active_base_url),
                                    referer=_free_text_url(active_base_url),
                                    payload=page_payload,
                                    timeout_seconds=float(args.timeout_seconds),
                                )
                            except Exception as exc:  # noqa: BLE001
                                broken_message = f"page {page_number} failed: {exc}"
                                break
                            if not bool(page_data.get("success")):
                                broken_message = str(page_data.get("data") or f"page {page_number} failed")
                                break

                        page_rows = _extract_rows(str(page_data.get("data", {}).get("resultsHtml", "")))
                        if not page_rows:
                            break
                        current_ids = {row.row_id for row in page_rows}
                        if current_ids == previous_ids:
                            break
                        previous_ids = current_ids
                        pages_seen.append(page_number)

                        page_surface = _surface_url(active_base_url, query, window_start, window_end, page_number)
                        discovered, attempted, ingested = _ingest_rows(
                            db_session,
                            rows=page_rows,
                            base_url=active_base_url,
                            source_surface=page_surface,
                            partition_key=partition_key,
                            query=query,
                            parser_version=args.parser_version,
                            orchestrator=orchestrator,
                            adapter=adapter,
                            existing_urls=existing_urls,
                        )
                        partition_discovered += discovered
                        partition_attempted += attempted
                        partition_ingested += ingested
                        total_discovered += discovered
                        total_attempted += attempted
                        total_ingested += ingested
                        print(
                            f"[sci-free-text] term={query!r} window={window_start.isoformat()}..{window_end.isoformat()} "
                            f"page={page_number} discovered={discovered} attempted={attempted} ingested={ingested} "
                            f"total_ingested={total_ingested}",
                            flush=True,
                        )

                    status = (
                        SourcePartitionStatus.BROKEN
                        if broken_message
                        else (SourcePartitionStatus.DONE if partition_discovered > 0 else SourcePartitionStatus.VERIFIED)
                    )
                    record_source_partition(
                        db_session,
                        source_key="supreme_court",
                        partition_key=partition_key,
                        surface_url=surface_url,
                        partition_kind="free_text_date_window",
                        expected_hint=f"{query}:{window_start.isoformat()}->{window_end.isoformat()}",
                        discovered_increment=partition_discovered,
                        ingested_increment=partition_ingested,
                        status=status,
                        error_class="PaginationFailed" if broken_message else None,
                        proof_note=(
                            broken_message
                            or (
                                f"pages={pages_seen or [1]} discovered={partition_discovered} "
                                f"attempted={partition_attempted} ingested={partition_ingested}"
                            )
                        ),
                        payload={
                            "collector_type": "ajax_captcha_search_collector",
                            "partition_scheme": "query_term_x_date_window_x_page",
                            "query": query,
                            "window_start": window_start.isoformat(),
                            "window_end": window_end.isoformat(),
                            "pages_seen": pages_seen,
                        },
                    )
                    db_session.commit()

                    if int(args.log_every) > 0 and total_queries % int(args.log_every) == 0:
                        print(
                            f"[sci-free-text] total_queries={total_queries} "
                            f"discovered={total_discovered} attempted={total_attempted} "
                            f"ingested={total_ingested}",
                            flush=True,
                        )

                    if float(args.sleep_seconds) > 0:
                        sleep(float(args.sleep_seconds))

                if total_ingested >= target:
                    break
                if int(args.query_limit) > 0 and total_queries >= int(args.query_limit):
                    break
    finally:
        ocr_client.close()

    print(
        f"[sci-free-text] completed_at={datetime.now(UTC).isoformat()} "
        f"queries={total_queries} discovered={total_discovered} attempted={total_attempted} "
        f"ingested={total_ingested}",
        flush=True,
    )
    if total_ingested >= target or bool(args.allow_underfilled):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
