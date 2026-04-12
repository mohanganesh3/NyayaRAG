from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
from time import sleep
from urllib.parse import parse_qs, urljoin, urlparse

import app.models as model_registry
import requests
from bs4 import BeautifulSoup
from app.core.config import BACKEND_ROOT
from app.db.base import Base
from app.db.session import build_engine
from app.ingestion.collector_utils import (
    document_exists_by_source_url,
    ensure_collection_control_schema,
    ensure_source_url_index,
    record_source_partition,
)
from app.ingestion.adapters import PdfLegalDocumentAdapter
from app.ingestion.contracts import IngestionJobContext
from app.ingestion.orchestrator import IngestionOrchestrator
from app.models import SourcePartitionStatus
from sqlalchemy.orm import Session

_ = model_registry

BASE_URL = "https://catjudgements.nic.in"
SEARCH_PATH = "/simple-search"


def _default_database_url() -> str:
    db_path = BACKEND_ROOT.parent / "data" / "collection" / "staging" / "cat.db"
    return f"sqlite+pysqlite:///{db_path}"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="collect_cat_repository",
        description=(
            "Collect Central Administrative Tribunal judgments by enumerating the "
            "catjudgements.nic.in repository search pages and per-item bitstreams."
        ),
    )
    p.add_argument("--database-url", default=_default_database_url())
    p.add_argument("--limit", type=int, default=5000)
    p.add_argument("--rpp", type=int, default=100)
    p.add_argument("--start-offset", type=int, default=0)
    p.add_argument("--max-pages", type=int, default=5000)
    p.add_argument("--timeout-seconds", type=float, default=60.0)
    p.add_argument("--sleep-seconds", type=float, default=0.02)
    p.add_argument("--fetch-retries", type=int, default=2)
    p.add_argument("--retry-backoff-seconds", type=float, default=1.5)
    p.add_argument("--parser-version", default="cat-repository-v1")
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
    p.add_argument("--ssl-verify", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--log-every", type=int, default=25)
    return p


def _headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.9",
    }


def _search_url(*, start: int, rpp: int) -> str:
    return (
        f"{BASE_URL}{SEARCH_PATH}?query=&sort_by=dc.date.issued_dt&order=desc"
        f"&rpp={rpp}&etal=0&start={start}"
    )


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


def _handle_links(search_html: str) -> list[str]:
    soup = BeautifulSoup(search_html, "html.parser")
    links: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if "/handle/123456789/" not in href or "viewItem=search" not in href:
            continue
        url = urljoin(BASE_URL, href)
        if url in seen:
            continue
        seen.add(url)
        links.append(url)
    return links


def _parse_item_page(item_url: str, html: str) -> tuple[str | None, str | None, str | None]:
    soup = BeautifulSoup(html, "html.parser")

    bitstream_url: str | None = None
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if "/bitstream/" in href and href.lower().endswith(".pdf"):
            bitstream_url = urljoin(BASE_URL, href)
            break

    title: str | None = None
    heading = soup.find(["h2", "h1"])
    if heading is not None:
        title = " ".join(heading.get_text(" ", strip=True).split()) or None
    if title is None and soup.title is not None and soup.title.string:
        title = " ".join(str(soup.title.string).split()) or None

    date_text: str | None = None
    for cell in soup.find_all(["td", "th"]):
        label = " ".join(cell.get_text(" ", strip=True).split()).lower()
        if label in {"date", "date issued", "issue date"}:
            nxt = cell.find_next("td")
            if nxt is not None:
                date_text = " ".join(nxt.get_text(" ", strip=True).split()) or None
                break

    if date_text is None:
        text = " ".join(soup.get_text(" ", strip=True).split())
        for marker in ["Date issued:", "Issue Date:", "Date:"]:
            idx = text.find(marker)
            if idx >= 0:
                date_text = text[idx + len(marker) : idx + len(marker) + 40].strip()
                break

    return bitstream_url, title, date_text


def _stable_external_id(bitstream_url: str, item_url: str) -> str:
    parsed = urlparse(bitstream_url)
    tail = parsed.path.rstrip("/").split("/")[-1]
    if tail.lower().endswith(".pdf"):
        return tail

    query = parse_qs(parsed.query)
    file_param = query.get("file", [])
    if file_param:
        return f"cat-{sha256(str(file_param[0]).encode('utf-8')).hexdigest()[:16]}"

    return f"cat-{sha256(item_url.encode('utf-8')).hexdigest()[:16]}"


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

    attempted = 0
    discovered = 0
    successes = 0
    skipped_existing = 0
    pages = 0
    seen_item_urls: set[str] = set()
    seen_pdf_urls: set[str] = set()

    with Session(engine) as db_session:
        ensure_collection_control_schema(db_session)
        ensure_source_url_index(db_session)
        offset = int(args.start_offset)
        while successes < target and pages < int(args.max_pages):
            search_url = _search_url(start=offset, rpp=int(args.rpp))
            partition_key = f"offset:{offset}|rpp:{int(args.rpp)}"
            try:
                response = _get_with_retries(
                    http,
                    search_url,
                    timeout_seconds=float(args.timeout_seconds),
                    headers=_headers(),
                    ssl_verify=bool(args.ssl_verify),
                    retries=max(0, int(args.fetch_retries)),
                    backoff_seconds=float(args.retry_backoff_seconds),
                )
            except Exception as exc:  # noqa: BLE001
                db_session.rollback()
                record_source_partition(
                    db_session,
                    source_key="cat",
                    partition_key=partition_key,
                    surface_url=search_url,
                    partition_kind="repository_search_page",
                    expected_hint=f"offset={offset}",
                    status=SourcePartitionStatus.BROKEN,
                    error_class=type(exc).__name__,
                    proof_note=f"search fetch failed: {exc}",
                    payload={"collector_type": "repository_handle"},
                )
                db_session.commit()
                print(
                    f"[cat] search page failed offset={offset} err={type(exc).__name__}: {exc}",
                    flush=True,
                )
                break

            item_urls = _handle_links(response.text)
            record_source_partition(
                db_session,
                source_key="cat",
                partition_key=partition_key,
                surface_url=search_url,
                partition_kind="repository_search_page",
                expected_hint=f"offset={offset}",
                discovered_increment=len(item_urls),
                status=SourcePartitionStatus.RUNNING,
                proof_note=f"discovered {len(item_urls)} item handles",
                payload={"collector_type": "repository_handle"},
            )
            db_session.commit()
            pages += 1
            if not item_urls:
                break

            for item_url in item_urls:
                if successes >= target:
                    break
                if item_url in seen_item_urls:
                    continue
                seen_item_urls.add(item_url)
                discovered += 1

                try:
                    item_resp = _get_with_retries(
                        http,
                        item_url,
                        timeout_seconds=float(args.timeout_seconds),
                        headers={**_headers(), "Referer": search_url},
                        ssl_verify=bool(args.ssl_verify),
                        retries=max(0, int(args.fetch_retries)),
                        backoff_seconds=float(args.retry_backoff_seconds),
                    )
                except Exception as exc:  # noqa: BLE001
                    db_session.rollback()
                    record_source_partition(
                        db_session,
                        source_key="cat",
                        partition_key=partition_key,
                        surface_url=search_url,
                        partition_kind="repository_search_page",
                        expected_hint=f"offset={offset}",
                        status=SourcePartitionStatus.BROKEN,
                        error_class=type(exc).__name__,
                        proof_note=f"item fetch failed: {item_url}",
                        payload={"collector_type": "repository_handle"},
                    )
                    db_session.commit()
                    print(
                        f"[cat] item fetch failed item={item_url} err={type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    continue
                bitstream_url, title, date_text = _parse_item_page(item_url, item_resp.text)
                if not bitstream_url or bitstream_url in seen_pdf_urls:
                    continue
                seen_pdf_urls.add(bitstream_url)
                if document_exists_by_source_url(
                    db_session,
                    source_system="cat",
                    source_url=bitstream_url,
                ):
                    skipped_existing += 1
                    if int(args.log_every) > 0 and skipped_existing % int(args.log_every) == 0:
                        print(
                            f"[cat] pages={pages} discovered={discovered} attempted={attempted} "
                            f"ingested={successes} skipped_existing={skipped_existing}",
                            flush=True,
                        )
                    continue
                attempted += 1

                context = IngestionJobContext(
                    source_key="cat",
                    source_url=bitstream_url,
                    parser_version=str(args.parser_version),
                    external_id=_stable_external_id(bitstream_url, item_url),
                    metadata={
                        "court_name": "Central Administrative Tribunal",
                        "doc_type": "judgment",
                        "practice_areas": ["service"],
                        "jurisdiction_binding": ["Central Administrative Tribunal"],
                        "jurisdiction_persuasive": ["All India"],
                        "title": title or "Central Administrative Tribunal Judgment",
                        "date_text": date_text,
                        "ssl_verify": bool(args.ssl_verify),
                        "http_headers": {"Referer": item_url},
                        "seed_url": search_url,
                        "detail_url": item_url,
                        "artifact_url": bitstream_url,
                        "source_surface": "repository_handle",
                        "provenance_tier": "official",
                        "collector_type": "repository_handle",
                        "partition_key": partition_key,
                        "partition_kind": "repository_search_page",
                        "partition_scheme": "offset_page",
                        "expected_proof_type": "repository_handle_complete",
                    },
                )

                try:
                    orchestrator.ingest(db_session, adapter, context)
                    record_source_partition(
                        db_session,
                        source_key="cat",
                        partition_key=partition_key,
                        surface_url=search_url,
                        partition_kind="repository_search_page",
                        expected_hint=f"offset={offset}",
                        ingested_increment=1,
                        status=SourcePartitionStatus.RUNNING,
                        proof_note=f"last_ingested={bitstream_url}",
                        payload={"collector_type": "repository_handle"},
                    )
                    db_session.commit()
                    successes += 1
                except Exception as exc:  # noqa: BLE001
                    db_session.rollback()
                    record_source_partition(
                        db_session,
                        source_key="cat",
                        partition_key=partition_key,
                        surface_url=search_url,
                        partition_kind="repository_search_page",
                        expected_hint=f"offset={offset}",
                        status=SourcePartitionStatus.BROKEN,
                        error_class=type(exc).__name__,
                        proof_note=f"ingest failed for {bitstream_url}",
                        payload={"collector_type": "repository_handle"},
                    )
                    db_session.commit()
                    print(
                        f"[cat] ingest failed item={item_url} pdf={bitstream_url} "
                        f"error={type(exc).__name__}: {exc}",
                        flush=True,
                    )

                if int(args.log_every) > 0 and attempted % int(args.log_every) == 0:
                    print(
                        f"[cat] pages={pages} discovered={discovered} attempted={attempted} "
                        f"ingested={successes} skipped_existing={skipped_existing}",
                        flush=True,
                    )

                if float(args.sleep_seconds) > 0:
                    sleep(float(args.sleep_seconds))

            offset += int(args.rpp)

    print(
        f"[cat] completed_at={datetime.now(UTC).isoformat()} pages={pages} "
        f"discovered={discovered} attempted={attempted} ingested={successes} "
        f"skipped_existing={skipped_existing}",
        flush=True,
    )

    if successes >= target or bool(args.allow_underfilled):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
