from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from typing import Any
from urllib.parse import parse_qs, urlparse

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

DRTAPI_BASE = "https://drt.gov.in/drtapi/"

# NOTE: Despite the name, this endpoint provides DRT daily/final order listings for a
# given DRT scheme ID and date range.
REPORT_FROM_TO_ENDPOINT = "getDratOrderJudgementReportFromToDate"
CASE_DETAIL_DIARY_ENDPOINT = "getCaseDetailDiaryNoWise"
SCHEME_LIST_ENDPOINT = "getDrtDratScheamName"


def _default_database_url() -> str:
    db_path = BACKEND_ROOT.parent / "data" / "collection" / "staging" / "drt.db"
    return f"sqlite+pysqlite:///{db_path}"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="collect_drt_orders",
        description=(
            "Collector for Debt Recovery Tribunal (DRT) daily orders via drt.gov.in APIs. "
            "Enumerates daily orders by date range, resolves case details by diary number, "
            "and ingests the resulting PDF URLs into a staging SQLite DB."
        ),
    )
    p.add_argument("--database-url", default=_default_database_url())
    p.add_argument("--source-key", default="drt")
    p.add_argument("--parser-version", default="drt-orders-v1")

    p.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Max PDFs to ingest in this run (default: 1000).",
    )
    p.add_argument(
        "--document-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "If true (default), persist only canonical LegalDocument rows (skip chunking, embeddings, graph, and appeal projections)."
        ),
    )
    p.add_argument(
        "--allow-underfilled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If true (default), do not exit non-zero when fewer than --limit PDFs are ingested.",
    )

    p.add_argument(
        "--scheme-id",
        action="append",
        default=[],
        help=(
            "Repeatable. DRT schemeNameDrtId values to ingest. "
            "If omitted, the collector will ingest across all schemes returned by getDrtDratScheamName."
        ),
    )
    p.add_argument(
        "--order-type-id",
        default="1",
        help=(
            "dratDailyFinalOrderId value used by getDratOrderJudgementReportFromToDate. "
            "Empirically, '1' yields daily orders (default: 1)."
        ),
    )

    p.add_argument(
        "--from-date",
        default=None,
        help="ISO date (YYYY-MM-DD). If omitted, computed as (--to-date - --days-back).",
    )
    p.add_argument(
        "--to-date",
        default=None,
        help="ISO date (YYYY-MM-DD). If omitted, defaults to today.",
    )
    p.add_argument(
        "--days-back",
        type=int,
        default=3650,
        help="If --from-date is omitted, collect starting this many days back from --to-date (default: 3650).",
    )
    p.add_argument(
        "--window-days",
        type=int,
        default=31,
        help="Query window size in days per API call (default: 31).",
    )

    p.add_argument(
        "--reverse-chronological",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "If true (default), query the most-recent date windows first and walk backwards in time. "
            "This typically yields faster early growth for high-volume sources."
        ),
    )

    p.add_argument("--timeout-seconds", type=float, default=60.0)
    p.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.05,
        help="Optional polite delay between API requests (default: 0.05).",
    )
    p.add_argument(
        "--ssl-verify",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable/disable TLS verification for API + PDF downloads.",
    )
    return p


def _fmt_dmy(d: date) -> str:
    return f"{d.day:02d}/{d.month:02d}/{d.year:04d}"


def _parse_iso_date(value: str) -> date:
    return date.fromisoformat(value.strip())


def _stable_external_id(source_key: str, url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    file_param = None
    if isinstance(query, dict):
        raw_file = query.get("file")
        if isinstance(raw_file, list) and raw_file:
            file_param = str(raw_file[0] or "").strip() or None

    if file_param:
        return f"file-{sha256(file_param.encode('utf-8')).hexdigest()[:16]}"

    # If the URL is a direct PDF path, keep the filename; otherwise fall back to a URL hash.
    tail = parsed.path.rstrip("/").split("/")[-1]
    if tail.lower().endswith(".pdf"):
        return tail

    return f"url-{sha256(url.encode('utf-8')).hexdigest()[:16]}"


@dataclass(frozen=True)
class DiaryKey:
    scheme_id: str
    diary_no: int
    diary_year: int


def _parse_diary(diary: str) -> tuple[int, int] | None:
    # Common format: "2/2023". Occasionally may be plain "2".
    raw = (diary or "").strip()
    if not raw:
        return None
    if "/" in raw:
        a, b = raw.split("/", 1)
        if a.strip().isdigit() and b.strip().isdigit():
            return int(a.strip()), int(b.strip())
        return None
    if raw.isdigit():
        # Without year this isn't actionable.
        return None
    return None


def _post_json(
    session: requests.Session,
    endpoint: str,
    *,
    payload: dict[str, Any],
    timeout_seconds: float,
    ssl_verify: bool,
) -> Any:
    url = DRTAPI_BASE + endpoint
    # The portal expects form/multipart-style posts; urlencoded generally works.
    resp = session.post(
        url,
        data={k: "" if v is None else str(v) for k, v in payload.items()},
        timeout=float(timeout_seconds),
        verify=bool(ssl_verify),
    )
    resp.raise_for_status()
    return resp.json()


def _list_schemes(
    session: requests.Session,
    *,
    timeout_seconds: float,
    ssl_verify: bool,
) -> list[str]:
    data = _post_json(
        session,
        SCHEME_LIST_ENDPOINT,
        payload={},
        timeout_seconds=timeout_seconds,
        ssl_verify=ssl_verify,
    )
    schemes: list[str] = []
    if isinstance(data, list):
        for row in data:
            if not isinstance(row, dict):
                continue
            sid = row.get("schemeNameDrtId")
            if sid is None:
                continue
            schemes.append(str(sid).strip())
    # Dedup while preserving order.
    out: list[str] = []
    seen: set[str] = set()
    for sid in schemes:
        if not sid or sid in seen:
            continue
        seen.add(sid)
        out.append(sid)
    return out


def _ingest_report_rows(
    rows: list[object],
    *,
    scheme_id: str,
    http: requests.Session,
    db_session: Session,
    orchestrator: IngestionOrchestrator,
    adapter: PdfLegalDocumentAdapter,
    args: argparse.Namespace,
    seen_diaries: set[DiaryKey],
    seen_pdf_urls: set[str],
    successes: int,
    attempted: int,
    target: int,
) -> tuple[int, int]:
    if not isinstance(rows, list):
        return successes, attempted

    for row in rows:
        if successes >= target:
            break
        if not isinstance(row, dict):
            continue

        diary_parsed = _parse_diary(str(row.get("diaryno") or ""))
        if not diary_parsed:
            continue
        diary_no, diary_year = diary_parsed

        dk = DiaryKey(scheme_id=str(scheme_id), diary_no=int(diary_no), diary_year=int(diary_year))
        if dk in seen_diaries:
            continue
        seen_diaries.add(dk)

        # Resolve full case details and proceeding PDF URLs via diary number.
        try:
            detail = _post_json(
                http,
                CASE_DETAIL_DIARY_ENDPOINT,
                payload={
                    "schemeNameDrtId": scheme_id,
                    "diaryNo": str(diary_no),
                    "diaryYear": str(diary_year),
                },
                timeout_seconds=float(args.timeout_seconds),
                ssl_verify=bool(args.ssl_verify),
            )
        except Exception as exc:  # noqa: BLE001
            print(
                f"[case-skip] scheme={scheme_id} diary={diary_no}/{diary_year} "
                f"err={type(exc).__name__}: {exc}",
                flush=True,
            )
            continue

        proceedings: list[object] = []
        if isinstance(detail, dict):
            raw = detail.get("caseProceedingDetails") or []
            if isinstance(raw, list):
                proceedings = raw

        for proc in proceedings:
            if successes >= target:
                break
            if not isinstance(proc, dict):
                continue

            pdf_url = str(proc.get("orderUrl") or "").strip()
            if not pdf_url:
                continue
            if pdf_url in seen_pdf_urls:
                continue
            seen_pdf_urls.add(pdf_url)

            attempted += 1
            context = IngestionJobContext(
                source_key=str(args.source_key),
                source_url=pdf_url,
                parser_version=str(args.parser_version),
                external_id=_stable_external_id(str(args.source_key), pdf_url),
                metadata={
                    "court_name": "Debt Recovery Tribunal",
                    "doc_type": "order",
                    "practice_areas": ["banking"],
                    "jurisdiction_binding": ["All India"],
                    "jurisdiction_persuasive": ["All India"],
                    "collected_at": datetime.now(UTC).isoformat(),
                    "ssl_verify": bool(args.ssl_verify),
                    "scheme_id": scheme_id,
                    "diary_no": diary_no,
                    "diary_year": diary_year,
                    "case_no": (detail.get("caseno") if isinstance(detail, dict) else None),
                    "case_year": (detail.get("caseyear") if isinstance(detail, dict) else None),
                    "case_type": (detail.get("casetype") if isinstance(detail, dict) else None),
                    "petitioner": (
                        detail.get("petitionerName") if isinstance(detail, dict) else None
                    ),
                    "respondent": (
                        detail.get("respondentName") if isinstance(detail, dict) else None
                    ),
                    "listing_date": proc.get("causelistdate"),
                    "listing_purpose": proc.get("purpose"),
                    "tribunal_court_name": proc.get("courtName"),
                    "tribunal_court_no": proc.get("courtNo"),
                    # Some CIS endpoints behave better with a referer.
                    "http_headers": {"Referer": "https://drt.gov.in/"},
                },
            )

            try:
                persisted = orchestrator.ingest(db_session, adapter, context)
            except Exception as exc:  # noqa: BLE001
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

    return successes, attempted


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    engine = build_engine(args.database_url)
    Base.metadata.create_all(engine)

    target = max(0, int(args.limit))
    if target == 0:
        print("--limit=0 so nothing to ingest.")
        return 0

    to_d = _parse_iso_date(args.to_date) if args.to_date else date.today()
    if args.from_date:
        from_d = _parse_iso_date(args.from_date)
    else:
        from_d = to_d - timedelta(days=max(0, int(args.days_back)))

    if from_d > to_d:
        raise SystemExit("--from-date must be <= --to-date")

    window_days = max(1, int(args.window_days))

    http = requests.Session()

    scheme_ids = [str(s).strip() for s in (args.scheme_id or []) if str(s).strip()]
    if not scheme_ids:
        scheme_ids = _list_schemes(http, timeout_seconds=float(args.timeout_seconds), ssl_verify=bool(args.ssl_verify))

    if not scheme_ids:
        raise SystemExit("No scheme ids available (scheme list empty).")

    adapter = PdfLegalDocumentAdapter()
    orchestrator = IngestionOrchestrator(document_only=bool(args.document_only))

    successes = 0
    attempted = 0

    seen_diaries: set[DiaryKey] = set()
    seen_pdf_urls: set[str] = set()

    with Session(engine) as db_session:
        for scheme_id in scheme_ids:
            if successes >= target:
                break

            if bool(args.reverse_chronological):
                window_end = to_d
                while window_end >= from_d and successes < target:
                    window_start = max(from_d, window_end - timedelta(days=window_days - 1))

                    payload = {
                        "schemeNameDrtId": scheme_id,
                        "dratDailyFinalOrderId": str(args.order_type_id),
                        "fromDate": _fmt_dmy(window_start),
                        "toDate": _fmt_dmy(window_end),
                    }

                    try:
                        rows = _post_json(
                            http,
                            REPORT_FROM_TO_ENDPOINT,
                            payload=payload,
                            timeout_seconds=float(args.timeout_seconds),
                            ssl_verify=bool(args.ssl_verify),
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(
                            f"[crawl-skip] scheme={scheme_id} window={payload['fromDate']}..{payload['toDate']} "
                            f"err={type(exc).__name__}: {exc}",
                            flush=True,
                        )
                        window_end = window_start - timedelta(days=1)
                        continue

                    successes, attempted = _ingest_report_rows(
                        rows,
                        scheme_id=str(scheme_id),
                        http=http,
                        db_session=db_session,
                        orchestrator=orchestrator,
                        adapter=adapter,
                        args=args,
                        seen_diaries=seen_diaries,
                        seen_pdf_urls=seen_pdf_urls,
                        successes=successes,
                        attempted=attempted,
                        target=target,
                    )

                    # Be polite.
                    if float(args.sleep_seconds) > 0:
                        import time

                        time.sleep(float(args.sleep_seconds))

                    window_end = window_start - timedelta(days=1)
            else:
                cur = from_d
                while cur <= to_d and successes < target:
                    end = min(cur + timedelta(days=window_days - 1), to_d)

                    payload = {
                        "schemeNameDrtId": scheme_id,
                        "dratDailyFinalOrderId": str(args.order_type_id),
                        "fromDate": _fmt_dmy(cur),
                        "toDate": _fmt_dmy(end),
                    }

                    try:
                        rows = _post_json(
                            http,
                            REPORT_FROM_TO_ENDPOINT,
                            payload=payload,
                            timeout_seconds=float(args.timeout_seconds),
                            ssl_verify=bool(args.ssl_verify),
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(
                            f"[crawl-skip] scheme={scheme_id} window={payload['fromDate']}..{payload['toDate']} "
                            f"err={type(exc).__name__}: {exc}",
                            flush=True,
                        )
                        cur = end + timedelta(days=1)
                        continue

                    successes, attempted = _ingest_report_rows(
                        rows,
                        scheme_id=str(scheme_id),
                        http=http,
                        db_session=db_session,
                        orchestrator=orchestrator,
                        adapter=adapter,
                        args=args,
                        seen_diaries=seen_diaries,
                        seen_pdf_urls=seen_pdf_urls,
                        successes=successes,
                        attempted=attempted,
                        target=target,
                    )

                    # Be polite.
                    if float(args.sleep_seconds) > 0:
                        import time

                        time.sleep(float(args.sleep_seconds))

                    cur = end + timedelta(days=1)

    if successes < target:
        msg = f"Only ingested {successes}/{target} PDFs (attempted {attempted})."
        if bool(args.allow_underfilled):
            print(msg, flush=True)
            return 0
        raise SystemExit(msg)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
