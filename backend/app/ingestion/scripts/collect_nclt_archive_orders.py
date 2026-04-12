from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from time import sleep
from urllib.parse import urljoin, urlparse

import app.models as model_registry
import requests
import urllib3
from bs4 import BeautifulSoup
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
from sqlalchemy.orm import Session

_ = model_registry

ARCHIVE_BASE_URL = "https://archive.nclt.gov.in"
LIST_PATH = "/order-judgements"
CASE_SPLIT_RE = re.compile(r"\s+V(?:/s\.?|s\.?|S\.?)\s+", re.IGNORECASE)
STATUS_RE = re.compile(r"\[(.*?)\]")


@dataclass(slots=True)
class ListRow:
    detail_url: str
    case_no: str | None
    status: str | None
    petitioner: str | None
    respondent: str | None
    listing_text: str | None


@dataclass(slots=True)
class DocumentRecord:
    pdf_url: str
    detail_url: str
    doc_type: str
    case_no: str | None
    title: str | None
    date_text: str | None
    petitioner: str | None
    respondent: str | None
    status: str | None
    listing_text: str | None
    bench: str | None


def _default_database_url() -> str:
    db_path = BACKEND_ROOT.parent / "data" / "collection" / "staging" / "nclt.db"
    return f"sqlite+pysqlite:///{db_path}"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="collect_nclt_archive_orders",
        description=(
            "Collect NCLT archive order/judgment PDFs by paginating the archive "
            "order-judgements view and ingesting case detail attachments."
        ),
    )
    p.add_argument("--database-url", default=_default_database_url())
    p.add_argument("--start-page", type=int, default=0)
    p.add_argument("--max-pages", type=int, default=5000)
    p.add_argument("--limit", type=int, default=300000)
    p.add_argument("--timeout-seconds", type=float, default=60.0)
    p.add_argument("--sleep-seconds", type=float, default=0.02)
    p.add_argument("--list-retries", type=int, default=2)
    p.add_argument("--detail-retries", type=int, default=2)
    p.add_argument("--retry-backoff-seconds", type=float, default=1.5)
    p.add_argument("--parser-version", default="nclt-archive-v1")
    p.add_argument(
        "--document-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If true (default), skip chunk/embedding/graph projections during ingestion.",
    )
    p.add_argument(
        "--allow-underfilled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If true (default), do not exit non-zero when fewer than --limit docs are ingested.",
    )
    p.add_argument("--ssl-verify", action=argparse.BooleanOptionalAction, default=False)
    p.add_argument("--log-every", type=int, default=25)
    return p


def _headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.9",
    }


def _list_url(page: int) -> str:
    return f"{ARCHIVE_BASE_URL}{LIST_PATH}?page={page}"


def _get_with_retries(
    http: requests.Session,
    url: str,
    *,
    timeout_seconds: float,
    headers: dict[str, str],
    ssl_verify: bool,
    retries: int,
    backoff_seconds: float,
) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(max(0, retries) + 1):
        try:
            response = http.get(
                url,
                timeout=timeout_seconds,
                headers=headers,
                verify=ssl_verify,
            )
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt >= retries:
                raise
            sleep(max(0.0, backoff_seconds) * (attempt + 1))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"unreachable retry state for {url}")


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split())
    return text or None


def _split_parties(parties_text: str | None) -> tuple[str | None, str | None]:
    if not parties_text:
        return None, None
    base = re.split(r"Petitioner Advocate\s*:|Respondent Advocate\s*:", parties_text, maxsplit=1)[0]
    base = _clean_text(base)
    if not base:
        return None, None
    parts = CASE_SPLIT_RE.split(base, maxsplit=1)
    if len(parts) == 2:
        return _clean_text(parts[0]), _clean_text(parts[1])
    return base, None


def _stable_external_id(pdf_url: str) -> str:
    parsed = urlparse(pdf_url)
    file_name = parsed.path.rstrip("/").split("/")[-1]
    if file_name:
        return file_name
    return f"nclt-{sha256(pdf_url.encode('utf-8')).hexdigest()[:16]}"


def _doc_type_from_detail_url(detail_url: str) -> str:
    lower = detail_url.lower()
    if "judgment" in lower or "judgement" in lower:
        return "judgment"
    return "order"


def _normalize_date_text(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return cleaned


def _parse_list_rows(page_html: str) -> list[ListRow]:
    soup = BeautifulSoup(page_html, "html.parser")
    table = soup.find("table", class_="views-table")
    if table is None:
        return []

    rows: list[ListRow] = []
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all("td")
        if len(cells) < 4:
            continue
        anchor = cells[1].find("a", href=True)
        if anchor is None:
            continue

        detail_url = urljoin(ARCHIVE_BASE_URL, anchor["href"])
        case_status_text = _clean_text(cells[1].get_text(" ", strip=True)) or ""
        case_no = _clean_text(re.split(r"\[", case_status_text, maxsplit=1)[0])
        status_match = STATUS_RE.search(case_status_text)
        status = _clean_text(status_match.group(1)) if status_match else None

        parties_text = _clean_text(cells[2].get_text(" ", strip=True))
        petitioner, respondent = _split_parties(parties_text)
        listing_text = _clean_text(cells[3].get_text(" ", strip=True))

        rows.append(
            ListRow(
                detail_url=detail_url,
                case_no=case_no,
                status=status,
                petitioner=petitioner,
                respondent=respondent,
                listing_text=listing_text,
            )
        )
    return rows


def _extract_bench(soup: BeautifulSoup) -> str | None:
    body_text = _clean_text(soup.get_text(" ", strip=True)) or ""
    match = re.search(r"\b([A-Z][A-Za-z&.\- ]+ Bench)\b", body_text)
    if match:
        return _clean_text(match.group(1))
    return None


def _table_headers(table) -> list[str]:
    header_row = table.find("tr")
    if header_row is None:
        return []
    return [
        _clean_text(cell.get_text(" ", strip=True)) or ""
        for cell in header_row.find_all(["th", "td"])
    ]


def _parse_detail_page(detail_url: str, html: str, row: ListRow) -> list[DocumentRecord]:
    soup = BeautifulSoup(html, "html.parser")
    bench = _extract_bench(soup)
    default_doc_type = _doc_type_from_detail_url(detail_url)
    documents: list[DocumentRecord] = []
    seen_pdfs: set[str] = set()

    for table in soup.find_all("table", class_="views-table"):
        headers = _table_headers(table)
        if not headers or "Orders PDF" not in headers:
            continue

        rows = table.find_all("tr")[1:]
        for tr in rows:
            link = tr.find("a", href=True)
            if link is None:
                continue
            pdf_url = urljoin(detail_url, link["href"])
            if pdf_url in seen_pdfs:
                continue
            seen_pdfs.add(pdf_url)

            cells = [_clean_text(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
            doc_type = default_doc_type
            case_no = row.case_no
            title = None
            date_text = None

            if headers[:4] == ["Title", "Orders Paased/Description", "Date of Judgement", "Orders PDF"]:
                title = cells[0] if len(cells) > 0 else None
                date_text = _normalize_date_text(cells[2] if len(cells) > 2 else None)
                if default_doc_type == "order" and date_text:
                    doc_type = "judgment"
            elif "Case No Judgement(s)" in headers and "Date of Order" in headers:
                case_no = cells[1] if len(cells) > 1 and cells[1] else case_no
                date_text = _normalize_date_text(cells[2] if len(cells) > 2 else None)
            else:
                if len(cells) > 1:
                    title = cells[1]
                if len(cells) > 2:
                    date_text = _normalize_date_text(cells[2])

            if not title:
                title_bits = [part for part in [case_no, row.petitioner, row.respondent] if part]
                title = " v. ".join(title_bits[:2]) if len(title_bits) >= 2 else (case_no or "NCLT Order")

            documents.append(
                DocumentRecord(
                    pdf_url=pdf_url,
                    detail_url=detail_url,
                    doc_type=doc_type,
                    case_no=case_no,
                    title=title,
                    date_text=date_text,
                    petitioner=row.petitioner,
                    respondent=row.respondent,
                    status=row.status,
                    listing_text=row.listing_text,
                    bench=bench,
                )
            )

    return documents


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    target = max(0, int(args.limit))
    if target == 0:
        print("--limit=0 so nothing to ingest.")
        return 0

    engine = build_engine(args.database_url)
    Base.metadata.create_all(engine)

    adapter = PdfLegalDocumentAdapter()
    orchestrator = IngestionOrchestrator(document_only=bool(args.document_only))
    http = requests.Session()
    if not bool(args.ssl_verify):
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    pages = 0
    discovered_rows = 0
    discovered_pdfs = 0
    attempted = 0
    skipped_existing = 0
    successes = 0
    seen_detail_urls: set[str] = set()

    with Session(engine) as db_session:
        ensure_collection_control_schema(db_session)
        ensure_source_url_index(db_session)
        current_page = max(0, int(args.start_page))

        while successes < target and pages < int(args.max_pages):
            list_url = _list_url(current_page)
            partition_key = f"page:{current_page}"
            try:
                list_resp = _get_with_retries(
                    http,
                    list_url,
                    timeout_seconds=float(args.timeout_seconds),
                    headers=_headers(),
                    ssl_verify=bool(args.ssl_verify),
                    retries=max(0, int(args.list_retries)),
                    backoff_seconds=float(args.retry_backoff_seconds),
                )
            except Exception as exc:  # noqa: BLE001
                record_source_partition(
                    db_session,
                    source_key="nclt",
                    partition_key=partition_key,
                    surface_url=list_url,
                    partition_kind="archive_page",
                    expected_hint="list_fetch",
                    status="BROKEN",
                    error_class=type(exc).__name__,
                    proof_note=f"list fetch failed: {exc}",
                )
                db_session.commit()
                print(
                    f"[nclt] list fetch failed page={current_page} error={type(exc).__name__}: {exc}",
                    flush=True,
                )
                current_page += 1
                continue
            list_rows = _parse_list_rows(list_resp.text)
            pages += 1
            if not list_rows:
                break

            for row in list_rows:
                if row.detail_url in seen_detail_urls:
                    continue
                seen_detail_urls.add(row.detail_url)
                discovered_rows += 1
                record_source_partition(
                    db_session,
                    source_key="nclt",
                    partition_key=partition_key,
                    surface_url=list_url,
                    partition_kind="archive_page",
                    expected_hint="detail_rows",
                    discovered_increment=1,
                    status="RUNNING",
                    proof_note=f"detail={row.detail_url}",
                )

                try:
                    detail_resp = _get_with_retries(
                        http,
                        row.detail_url,
                        timeout_seconds=float(args.timeout_seconds),
                        headers={**_headers(), "Referer": list_url},
                        ssl_verify=bool(args.ssl_verify),
                        retries=max(0, int(args.detail_retries)),
                        backoff_seconds=float(args.retry_backoff_seconds),
                    )
                except Exception as exc:  # noqa: BLE001
                    record_source_partition(
                        db_session,
                        source_key="nclt",
                        partition_key=partition_key,
                        surface_url=list_url,
                        partition_kind="archive_page",
                        expected_hint="detail_fetch",
                        status="BROKEN",
                        error_class=type(exc).__name__,
                        proof_note=f"detail fetch failed: {row.detail_url}",
                    )
                    db_session.commit()
                    print(
                        f"[nclt] detail fetch failed page={current_page} detail={row.detail_url} "
                        f"error={type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    continue
                records = _parse_detail_page(row.detail_url, detail_resp.text, row)

                for record in records:
                    discovered_pdfs += 1
                    record_source_partition(
                        db_session,
                        source_key="nclt",
                        partition_key=partition_key,
                        surface_url=list_url,
                        partition_kind="archive_page",
                        expected_hint="pdf_records",
                        discovered_increment=1,
                        status="RUNNING",
                        proof_note=f"pdf={record.pdf_url}",
                    )
                    if document_exists_by_source_url(
                        db_session,
                        source_system="nclt",
                        source_url=record.pdf_url,
                    ):
                        skipped_existing += 1
                        continue

                    attempted += 1
                    parties: dict[str, str] = {}
                    if record.petitioner:
                        parties["petitioner"] = record.petitioner
                    if record.respondent:
                        parties["respondent"] = record.respondent

                    title = record.title or record.case_no or "NCLT Order"
                    if record.petitioner and record.respondent and " v. " not in title:
                        title = f"{record.petitioner} v. {record.respondent}"

                    context = IngestionJobContext(
                        source_key="nclt",
                        source_url=record.pdf_url,
                        parser_version=str(args.parser_version),
                        external_id=_stable_external_id(record.pdf_url),
                        metadata={
                            "court_name": "National Company Law Tribunal",
                            "doc_type": record.doc_type,
                            "practice_areas": ["corporate", "insolvency"],
                            "jurisdiction_binding": ["National Company Law Tribunal"],
                            "jurisdiction_persuasive": ["All India"],
                            "title": title,
                            "date_text": record.date_text,
                            "citation": record.case_no,
                            "bench": record.bench,
                            "parties": parties,
                            "ssl_verify": bool(args.ssl_verify),
                            "http_headers": {"Referer": record.detail_url},
                            "detail_url": record.detail_url,
                            "seed_url": list_url,
                            "source_surface": list_url,
                            "artifact_url": record.pdf_url,
                            "provenance_tier": "official",
                            "collector_type": "archive_detail_enumerator",
                            "partition_key": partition_key,
                            "partition_kind": "archive_page",
                            "expected_proof_type": "page_range_closure",
                            "partition_scheme": "page_range_x_detail_attachment",
                            "listing_text": record.listing_text,
                            "status": record.status,
                        },
                    )

                    try:
                        orchestrator.ingest(db_session, adapter, context)
                        record_source_partition(
                            db_session,
                            source_key="nclt",
                            partition_key=partition_key,
                            surface_url=list_url,
                            partition_kind="archive_page",
                            expected_hint="pdf_records",
                            ingested_increment=1,
                            status="RUNNING",
                            proof_note=f"last_ingested={record.pdf_url}",
                        )
                        db_session.commit()
                        successes += 1
                    except Exception as exc:  # noqa: BLE001
                        db_session.rollback()
                        record_source_partition(
                            db_session,
                            source_key="nclt",
                            partition_key=partition_key,
                            surface_url=list_url,
                            partition_kind="archive_page",
                            expected_hint="pdf_records",
                            status="BROKEN",
                            error_class=type(exc).__name__,
                            proof_note=str(exc)[:1000],
                        )
                        db_session.commit()
                        print(
                            f"[nclt] ingest failed detail={record.detail_url} pdf={record.pdf_url} "
                            f"error={type(exc).__name__}: {exc}",
                            flush=True,
                        )

                    if int(args.log_every) > 0 and attempted % int(args.log_every) == 0:
                        print(
                            f"[nclt] pages={pages} rows={discovered_rows} pdfs={discovered_pdfs} "
                            f"attempted={attempted} ingested={successes} "
                            f"skipped_existing={skipped_existing}",
                            flush=True,
                        )

                    if successes >= target:
                        break
                    if float(args.sleep_seconds) > 0:
                        sleep(float(args.sleep_seconds))

                if successes >= target:
                    break

            current_page += 1

    print(
        f"[nclt] completed_at={datetime.now(UTC).isoformat()} pages={pages} "
        f"rows={discovered_rows} pdfs={discovered_pdfs} attempted={attempted} "
        f"ingested={successes} skipped_existing={skipped_existing}",
        flush=True,
    )

    if successes >= target or bool(args.allow_underfilled):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
