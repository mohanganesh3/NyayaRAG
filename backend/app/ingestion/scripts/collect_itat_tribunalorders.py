from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from datetime import UTC, date, datetime, timedelta
from html import unescape as html_unescape
from pathlib import Path
from time import sleep

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
from app.models import SourcePartition, SourcePartitionStatus
from sqlalchemy import select, text
from sqlalchemy.orm import Session

_ = model_registry

BASE_URL = "https://itat.gov.in"
SEARCH_URL = f"{BASE_URL}/judicial/tribunalorders"
CAPTCHA_CHECK_URL = f"{BASE_URL}/Ajax/checkCaptcha"
CAPTCHA_IMAGE_URL = f"{BASE_URL}/captcha/show"
DEFAULT_OCR_PYTHON = "/tmp/itatocr/bin/python"

_OPTION_RE = re.compile(r'<option value="([^"]+)">([^<]+)</option>', re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


def _default_database_url() -> str:
    db_path = BACKEND_ROOT.parent / "data" / "collection" / "staging" / "itat.db"
    return f"sqlite+pysqlite:///{db_path}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collect_itat_tribunalorders",
        description="Collect official ITAT order PDFs via the captcha-gated tribunal orders search.",
    )
    parser.add_argument("--database-url", default=_default_database_url())
    parser.add_argument("--ocr-python", default=DEFAULT_OCR_PYTHON)
    parser.add_argument(
        "--ocr-helper-script",
        default=str(BACKEND_ROOT / "app/ingestion/scripts/solve_itat_captcha.py"),
    )
    parser.add_argument("--start-date", default="2025-01-01")
    parser.add_argument("--end-date", default=datetime.now(UTC).date().isoformat())
    parser.add_argument("--bench", action="append", dest="benches", default=[])
    parser.add_argument("--app-type", action="append", dest="app_types", default=[])
    parser.add_argument(
        "--search-mode",
        action="append",
        choices=["order_date", "pron_date"],
        dest="search_modes",
        default=[],
    )
    parser.add_argument("--limit", type=int, default=250000)
    parser.add_argument("--query-limit", type=int, default=0)
    parser.add_argument("--captcha-attempts", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--sleep-seconds", type=float, default=0.1)
    parser.add_argument("--parser-version", default="itat-tribunalorders-v1")
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
    parser.add_argument("--log-every", type=int, default=25)
    return parser


def _headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": SEARCH_URL,
        "Origin": BASE_URL,
    }


def _clean(fragment: str | None) -> str:
    if not fragment:
        return ""
    fragment = _BR_RE.sub("\n", fragment)
    return " ".join(_TAG_RE.sub(" ", html_unescape(fragment)).split())


def _parse_iso_date(value: str) -> date:
    return date.fromisoformat(value)


def _format_query_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _iter_dates(start_date: date, end_date: date) -> list[date]:
    if end_date < start_date:
        return []
    cursor = end_date
    dates: list[date] = []
    while cursor >= start_date:
        dates.append(cursor)
        cursor -= timedelta(days=1)
    return dates


def _extract_select_options(html: str, select_id: str) -> list[tuple[str, str]]:
    marker = f'id="{select_id}"'
    idx = html.find(marker)
    if idx < 0:
        return []
    tail = html[idx:]
    select_end = tail.find("</select>")
    if select_end < 0:
        select_end = len(tail)
    block = tail[:select_end]
    options: list[tuple[str, str]] = []
    for value, label in _OPTION_RE.findall(block):
        value = value.strip()
        label = _clean(label)
        if not value or label.lower().startswith("select "):
            continue
        options.append((value, label))
    return options


def _row_entries(html: str) -> list[dict[str, str]]:
    marker = '<div id="results">'
    idx = html.find(marker)
    if idx >= 0:
        html = html[idx:]
    rows: list[dict[str, str]] = []
    for row_html in re.findall(r"<tr>(.*?)</tr>", html, re.IGNORECASE | re.DOTALL):
        if "/public/files/upload/" not in row_html:
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.IGNORECASE | re.DOTALL)
        if len(cells) < 5:
            continue
        pdf_match = re.search(
            r'href="(https://itat\.gov\.in/public/files/upload/[^"]+\.pdf)"',
            row_html,
            re.IGNORECASE,
        )
        detail_match = re.search(
            r'href="(https://itat\.gov\.in/judicial/casedetails\?cid=[^"]+)"',
            row_html,
            re.IGNORECASE,
        )
        if pdf_match is None:
            continue
        rows.append(
            {
                "appeal_block": _clean(cells[0]),
                "parties_block": _clean(cells[1]),
                "alpha_bench": _clean(cells[2]),
                "pdf_url": pdf_match.group(1),
                "detail_url": detail_match.group(1) if detail_match else "",
            }
        )
    return rows


def _pagination_payloads(html: str) -> list[dict[str, str]]:
    if 'name="btnPage"' not in html:
        return []
    csrftkn = re.search(r'id="csrftkn5" name="csrftkn" value="([^"]+)"', html)
    lq = re.search(r'name="lq" value="([^"]+)"', html)
    lqc = re.search(r'name="lqc" value="([^"]+)"', html)
    buttons = re.findall(r'name="btnPage" value="(\d+)"', html)
    if not (csrftkn and lq and lqc and buttons):
        return []
    payloads: list[dict[str, str]] = []
    for page_num in sorted({int(btn) for btn in buttons if int(btn) > 1}):
        payloads.append(
            {
                "hp": "",
                "csrftkn": csrftkn.group(1),
                "lq": lq.group(1),
                "lqc": lqc.group(1),
                "btnPage": str(page_num),
            }
        )
    return payloads


def _appeal_ref(appeal_block: str) -> str:
    return appeal_block.split(" Status:", 1)[0].strip()


def _parse_parties(parties_block: str) -> dict[str, str]:
    if " VS. " in parties_block:
        appellant, respondent = parties_block.split(" VS. ", 1)
        return {"appellant": appellant.strip(), "respondent": respondent.strip()}
    return {"appellant": parties_block.strip()}


def _partition_key(*, mode: str, bench: str, app_type: str, query_date: date) -> str:
    return f"{mode}|bench:{bench}|type:{app_type}|date:{query_date.isoformat()}"


def _partition_exists(
    session: Session,
    *,
    partition_key: str,
    surface_url: str,
) -> bool:
    row = session.execute(
        select(SourcePartition.status).where(
            SourcePartition.source_key == "itat",
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


def _solve_captcha(
    session: requests.Session,
    *,
    client: OCRClient,
    csrf: str,
    timeout_seconds: float,
    attempts: int,
) -> str | None:
    for _ in range(max(1, int(attempts))):
        image = session.get(CAPTCHA_IMAGE_URL, timeout=timeout_seconds)
        image.raise_for_status()
        guess = client.solve(image.content)
        if not guess:
            continue
        check = session.post(
            CAPTCHA_CHECK_URL,
            data={"captcha": guess},
            headers={"X-CSRF-TOKEN": csrf, "Referer": SEARCH_URL},
            timeout=timeout_seconds,
        )
        check.raise_for_status()
        data = check.json()
        if str(data.get("rslt")).lower() == "true":
            return guess
    return None


def _fetch_search_page(
    session: requests.Session,
    *,
    mode: str,
    bench: str,
    app_type: str,
    query_date: date,
    client: OCRClient,
    timeout_seconds: float,
    attempts: int,
) -> str | None:
    page = session.get(SEARCH_URL, timeout=timeout_seconds)
    page.raise_for_status()
    form_id = "2" if mode == "order_date" else "3"
    csrf = re.search(
        rf'id="csrftkn{form_id}" name="csrftkn" value="([0-9a-f]+)"',
        page.text,
        re.IGNORECASE,
    )
    if csrf is None:
        raise RuntimeError(f"csrf token missing for ITAT {mode}")
    captcha = _solve_captcha(
        session,
        client=client,
        csrf=csrf.group(1),
        timeout_seconds=timeout_seconds,
        attempts=attempts,
    )
    if captcha is None:
        return None
    payload = {
        "hp": "",
        "csrftkn": csrf.group(1),
        ("c2" if mode == "order_date" else "c3"): captcha,
        ("bench_name_2" if mode == "order_date" else "bench_name_3"): bench,
        ("app_type_2" if mode == "order_date" else "app_type_3"): app_type,
        mode: _format_query_date(query_date),
        ("bt2" if mode == "order_date" else "bt3"): "true",
    }
    response = session.post(
        SEARCH_URL,
        data=payload,
        headers={"Referer": SEARCH_URL},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    return response.text


def _ingest_rows(
    db_session: Session,
    *,
    rows: list[dict[str, str]],
    source_surface: str,
    partition_key: str,
    parser_version: str,
    orchestrator: IngestionOrchestrator,
    adapter: PdfLegalDocumentAdapter,
    query_date: date,
    bench_label: str,
    app_type: str,
    existing_urls: set[str],
) -> tuple[int, int, int]:
    discovered = 0
    attempted = 0
    ingested = 0
    seen: set[str] = set()

    for row in rows:
        pdf_url = row["pdf_url"]
        if pdf_url in seen:
            continue
        seen.add(pdf_url)
        discovered += 1

        if pdf_url in existing_urls or document_exists_by_source_url(
            db_session,
            source_system="itat",
            source_url=pdf_url,
        ):
            existing_urls.add(pdf_url)
            continue

        attempted += 1
        appeal_ref = _appeal_ref(row["appeal_block"])
        title = f"{appeal_ref} | {row['parties_block']}".strip()
        context = IngestionJobContext(
            source_key="itat",
            source_url=pdf_url,
            parser_version=parser_version,
            external_id=f"itat-order-{appeal_ref}",
            metadata={
                "court_name": "Income Tax Appellate Tribunal",
                "doc_type": "order",
                "practice_areas": ["tax"],
                "jurisdiction_binding": ["Income Tax Appellate Tribunal"],
                "jurisdiction_persuasive": ["All India"],
                "title": title,
                "date_text": _format_query_date(query_date),
                "decision_date": query_date.isoformat(),
                "seed_url": SEARCH_URL,
                "detail_url": row["detail_url"] or SEARCH_URL,
                "artifact_url": pdf_url,
                "source_surface": source_surface,
                "provenance_tier": "official",
                "source_document_ref": appeal_ref,
                "citation": appeal_ref,
                "parties": _parse_parties(row["parties_block"]),
                "bench": [bench_label, row["alpha_bench"]] if row["alpha_bench"] else [bench_label],
                "collector_type": "captcha_search_collector",
                "partition_key": partition_key,
                "partition_kind": "search_query",
                "partition_scheme": "mode_bench_app_type_query_date",
                "expected_proof_type": "query_result_closure",
                "case_number": appeal_ref,
                "search_app_type": app_type,
            },
        )
        try:
            orchestrator.ingest(db_session, adapter, context)
            db_session.commit()
            ingested += 1
            existing_urls.add(pdf_url)
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
    search_modes = args.search_modes or ["order_date"]

    engine = build_engine(args.database_url)
    Base.metadata.create_all(engine)

    adapter = PdfLegalDocumentAdapter()
    orchestrator = IngestionOrchestrator(document_only=bool(args.document_only))
    http = requests.Session()
    http.headers.update(_headers())
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
                        "WHERE source_system = 'itat' AND source_url IS NOT NULL"
                    )
                ).fetchall()
                if source_url
            }

            seed_page = http.get(SEARCH_URL, timeout=float(args.timeout_seconds))
            seed_page.raise_for_status()
            bench_options = _extract_select_options(seed_page.text, "bench_name_2")
            app_type_options = _extract_select_options(seed_page.text, "app_type_2")

            selected_benches = args.benches or [value for value, _ in bench_options]
            selected_app_types = args.app_types or [value for value, _ in app_type_options]
            bench_labels = {value: label for value, label in bench_options}

            for query_date in _iter_dates(start_date, end_date):
                for bench in selected_benches:
                    for app_type in selected_app_types:
                        for mode in search_modes:
                            if total_ingested >= target:
                                break
                            if int(args.query_limit) > 0 and total_queries >= int(args.query_limit):
                                break

                            partition_key = _partition_key(
                                mode=mode,
                                bench=bench,
                                app_type=app_type,
                                query_date=query_date,
                            )
                            surface_url = (
                                f"{SEARCH_URL}?mode={mode}&bench={bench}&app_type={app_type}"
                                f"&date={query_date.isoformat()}"
                            )
                            if _partition_exists(
                                db_session,
                                partition_key=partition_key,
                                surface_url=surface_url,
                            ):
                                continue

                            total_queries += 1
                            print(
                                f"[itat-orders] query={total_queries} mode={mode} "
                                f"bench={bench} type={app_type} date={query_date.isoformat()}",
                                flush=True,
                            )
                            try:
                                first_page = _fetch_search_page(
                                    http,
                                    mode=mode,
                                    bench=bench,
                                    app_type=app_type,
                                    query_date=query_date,
                                    client=ocr_client,
                                    timeout_seconds=float(args.timeout_seconds),
                                    attempts=max(1, int(args.captcha_attempts)),
                                )
                            except Exception as exc:  # noqa: BLE001
                                record_source_partition(
                                    db_session,
                                    source_key="itat",
                                    partition_key=partition_key,
                                    surface_url=surface_url,
                                    partition_kind="search_query",
                                    expected_hint=f"{mode}:{query_date.isoformat()}",
                                    status=SourcePartitionStatus.BROKEN,
                                    error_class=type(exc).__name__,
                                    proof_note=f"search failed: {exc}",
                                    payload={
                                        "collector_type": "captcha_search_collector",
                                        "partition_scheme": "mode_bench_app_type_query_date",
                                    },
                                )
                                db_session.commit()
                                continue

                            if first_page is None:
                                record_source_partition(
                                    db_session,
                                    source_key="itat",
                                    partition_key=partition_key,
                                    surface_url=surface_url,
                                    partition_kind="search_query",
                                    expected_hint=f"{mode}:{query_date.isoformat()}",
                                    status=SourcePartitionStatus.BROKEN,
                                    error_class="CaptchaSolveFailed",
                                    proof_note="captcha could not be solved within attempt budget",
                                    payload={
                                        "collector_type": "captcha_search_collector",
                                        "partition_scheme": "mode_bench_app_type_query_date",
                                    },
                                )
                                db_session.commit()
                                continue

                            if "No Records Found" in first_page:
                                record_source_partition(
                                    db_session,
                                    source_key="itat",
                                    partition_key=partition_key,
                                    surface_url=surface_url,
                                    partition_kind="search_query",
                                    expected_hint=f"{mode}:{query_date.isoformat()}",
                                    status=SourcePartitionStatus.VERIFIED,
                                    proof_note="no records found",
                                    payload={
                                        "collector_type": "captcha_search_collector",
                                        "partition_scheme": "mode_bench_app_type_query_date",
                                    },
                                )
                                db_session.commit()
                                continue

                            pages = [first_page]
                            for payload in _pagination_payloads(first_page):
                                try:
                                    response = http.post(
                                        SEARCH_URL,
                                        data=payload,
                                        headers={"Referer": SEARCH_URL},
                                        timeout=float(args.timeout_seconds),
                                    )
                                    response.raise_for_status()
                                    pages.append(response.text)
                                except Exception:
                                    continue

                            partition_discovered = 0
                            partition_attempted = 0
                            partition_ingested = 0
                            for page_html in pages:
                                rows = _row_entries(page_html)
                                discovered, attempted, ingested = _ingest_rows(
                                    db_session,
                                    rows=rows,
                                    source_surface=surface_url,
                                    partition_key=partition_key,
                                    parser_version=args.parser_version,
                                    orchestrator=orchestrator,
                                    adapter=adapter,
                                    query_date=query_date,
                                    bench_label=bench_labels.get(bench, bench),
                                    app_type=app_type,
                                    existing_urls=existing_urls,
                                )
                                partition_discovered += discovered
                                partition_attempted += attempted
                                partition_ingested += ingested
                                total_discovered += discovered
                                total_attempted += attempted
                                total_ingested += ingested

                            record_source_partition(
                                db_session,
                                source_key="itat",
                                partition_key=partition_key,
                                surface_url=surface_url,
                                partition_kind="search_query",
                                expected_hint=f"{mode}:{query_date.isoformat()}",
                                discovered_increment=partition_discovered,
                                ingested_increment=partition_ingested,
                                status=(
                                    SourcePartitionStatus.DONE
                                    if partition_discovered > 0
                                    else SourcePartitionStatus.VERIFIED
                                ),
                                proof_note=(
                                    f"pages={len(pages)} discovered={partition_discovered} "
                                    f"attempted={partition_attempted} ingested={partition_ingested}"
                                ),
                                payload={
                                    "collector_type": "captcha_search_collector",
                                    "partition_scheme": "mode_bench_app_type_query_date",
                                    "mode": mode,
                                    "bench": bench,
                                    "app_type": app_type,
                                    "query_date": query_date.isoformat(),
                                },
                            )
                            db_session.commit()

                            if int(args.log_every) > 0 and total_queries % int(args.log_every) == 0:
                                print(
                                    f"[itat-orders] total_queries={total_queries} "
                                    f"discovered={total_discovered} attempted={total_attempted} "
                                    f"ingested={total_ingested}",
                                    flush=True,
                                )

                            if float(args.sleep_seconds) > 0:
                                sleep(float(args.sleep_seconds))

                        if total_ingested >= target:
                            break
                    if total_ingested >= target:
                        break
                if total_ingested >= target:
                    break
                if int(args.query_limit) > 0 and total_queries >= int(args.query_limit):
                    break
    finally:
        ocr_client.close()

    print(
        f"[itat-orders] completed_at={datetime.now(UTC).isoformat()} "
        f"queries={total_queries} discovered={total_discovered} attempted={total_attempted} "
        f"ingested={total_ingested}",
        flush=True,
    )
    if total_ingested >= target or bool(args.allow_underfilled):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
