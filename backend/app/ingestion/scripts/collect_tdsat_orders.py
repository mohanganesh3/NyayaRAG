from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
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

BASE_URL = "https://tdsat.gov.in/Delhi/services/"
SURFACES = (
    ("judgment", "judgment.php", "judgment"),
    ("daily_order", "dailyorderlist.php", "order"),
)


def _default_database_url() -> str:
    db_path = BACKEND_ROOT.parent / "data" / "collection" / "staging" / "tdsat.db"
    return f"sqlite+pysqlite:///{db_path}"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="collect_tdsat_orders",
        description=(
            "Collect TDSAT judgments and daily orders by posting yearly date ranges "
            "to the official search forms and ingesting the returned PDF rows."
        ),
    )
    p.add_argument("--database-url", default=_default_database_url())
    p.add_argument("--year-from", type=int, default=2001)
    p.add_argument("--year-to", type=int, default=datetime.now(UTC).year)
    p.add_argument("--limit", type=int, default=30000)
    p.add_argument("--timeout-seconds", type=float, default=60.0)
    p.add_argument("--sleep-seconds", type=float, default=0.02)
    p.add_argument("--parser-version", default="tdsat-year-slice-v1")
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


def _stable_external_id(pdf_url: str) -> str:
    parsed = urlparse(pdf_url)
    file_name = parsed.path.rstrip("/").split("/")[-1]
    if file_name:
        return file_name
    return f"tdsat-{sha256(pdf_url.encode('utf-8')).hexdigest()[:16]}"


def _normalize_date_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    if not cleaned:
        return None
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return cleaned


def _split_parties(title: str | None) -> tuple[str | None, str | None]:
    if not title:
        return None, None
    upper = title.upper()
    if " VS " in upper:
        left, right = title.split(" VS ", 1)
        left = " ".join(left.split())
        right = " ".join(right.split())
        return left or None, right or None
    return title, None


def _year_payload(year: int) -> dict[str, str]:
    end = date(year, 12, 31)
    current = date.today()
    if year == current.year:
        end = current
    return {
        "from_date1": f"01/01/{year}",
        "to_date1": end.strftime("%d/%m/%Y"),
        "frm3": "",
        "submit11": "Go",
    }


def _iter_result_rows(html: str, response_url: str):
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        for tr in rows[1:]:
            link = tr.find("a", href=True)
            if link is None or ".pdf" not in link["href"].lower():
                continue
            cells = [" ".join(td.get_text(" ", strip=True).split()) for td in tr.find_all("td")]
            if len(cells) < 5:
                continue
            yield {
                "pdf_url": urljoin(response_url, link["href"]),
                "case_no": cells[1],
                "coram": cells[2],
                "title": cells[3],
                "date_text": _normalize_date_text(cells[4]),
            }


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

    discovered = 0
    attempted = 0
    skipped_existing = 0
    successes = 0
    seen_pdf_urls: set[str] = set()

    year_from = int(args.year_from)
    year_to = int(args.year_to)
    years = range(year_to, year_from - 1, -1)

    with Session(engine) as db_session:
        ensure_collection_control_schema(db_session)
        ensure_source_url_index(db_session)

        for year in years:
            for surface_name, endpoint, doc_type in SURFACES:
                if successes >= target:
                    break
                partition_key = f"year:{year}|surface:{surface_name}"
                surface_url = urljoin(BASE_URL, endpoint)

                response = http.post(
                    surface_url,
                    data=_year_payload(year),
                    timeout=float(args.timeout_seconds),
                    headers=_headers(),
                    verify=bool(args.ssl_verify),
                )
                response.raise_for_status()

                for row in _iter_result_rows(response.text, response.url):
                    pdf_url = str(row["pdf_url"])
                    if pdf_url in seen_pdf_urls:
                        continue
                    seen_pdf_urls.add(pdf_url)
                    discovered += 1
                    record_source_partition(
                        db_session,
                        source_key="tdsat",
                        partition_key=partition_key,
                        surface_url=surface_url,
                        partition_kind="year_surface",
                        expected_hint=str(year),
                        discovered_increment=1,
                        status="RUNNING",
                        proof_note=f"pdf={pdf_url}",
                    )

                    if document_exists_by_source_url(
                        db_session,
                        source_system="tdsat",
                        source_url=pdf_url,
                    ):
                        skipped_existing += 1
                        continue

                    attempted += 1
                    title = str(row["title"])
                    petitioner, respondent = _split_parties(title)
                    parties: dict[str, str] = {}
                    if petitioner:
                        parties["petitioner"] = petitioner
                    if respondent:
                        parties["respondent"] = respondent

                    coram = str(row["coram"]).strip().rstrip(",")
                    bench = [coram] if coram else []
                    case_no = str(row["case_no"]).strip() or None

                    context = IngestionJobContext(
                        source_key="tdsat",
                        source_url=pdf_url,
                        parser_version=str(args.parser_version),
                        external_id=_stable_external_id(pdf_url),
                        metadata={
                            "court_name": "Telecom Disputes Settlement and Appellate Tribunal",
                            "doc_type": doc_type,
                            "practice_areas": ["telecom"],
                            "jurisdiction_binding": [
                                "Telecom Disputes Settlement and Appellate Tribunal"
                            ],
                            "jurisdiction_persuasive": ["All India"],
                            "title": title,
                            "date_text": row["date_text"],
                            "citation": case_no,
                            "bench": bench,
                            "parties": parties,
                            "ssl_verify": bool(args.ssl_verify),
                            "http_headers": {
                                "Referer": surface_url,
                            },
                            "surface": surface_name,
                            "year": year,
                            "seed_url": surface_url,
                            "source_surface": surface_url,
                            "artifact_url": pdf_url,
                            "provenance_tier": "official",
                            "collector_type": "search_result_enumerator",
                            "partition_key": partition_key,
                            "partition_kind": "year_surface",
                            "partition_scheme": "year_x_surface",
                            "expected_proof_type": "year_surface_closure",
                        },
                    )

                    try:
                        orchestrator.ingest(db_session, adapter, context)
                        record_source_partition(
                            db_session,
                            source_key="tdsat",
                            partition_key=partition_key,
                            surface_url=surface_url,
                            partition_kind="year_surface",
                            expected_hint=str(year),
                            ingested_increment=1,
                            status="RUNNING",
                            proof_note=f"last_ingested={pdf_url}",
                        )
                        db_session.commit()
                        successes += 1
                    except Exception as exc:  # noqa: BLE001
                        db_session.rollback()
                        record_source_partition(
                            db_session,
                            source_key="tdsat",
                            partition_key=partition_key,
                            surface_url=surface_url,
                            partition_kind="year_surface",
                            expected_hint=str(year),
                            status="BROKEN",
                            error_class=type(exc).__name__,
                            proof_note=str(exc)[:1000],
                        )
                        db_session.commit()
                        print(
                            f"[tdsat] ingest failed year={year} surface={surface_name} "
                            f"pdf={pdf_url} error={type(exc).__name__}: {exc}",
                            flush=True,
                        )

                    if int(args.log_every) > 0 and attempted % int(args.log_every) == 0:
                        print(
                            f"[tdsat] year={year} surface={surface_name} discovered={discovered} "
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

    print(
        f"[tdsat] completed_at={datetime.now(UTC).isoformat()} discovered={discovered} "
        f"attempted={attempted} ingested={successes} skipped_existing={skipped_existing}",
        flush=True,
    )

    if successes >= target or bool(args.allow_underfilled):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
