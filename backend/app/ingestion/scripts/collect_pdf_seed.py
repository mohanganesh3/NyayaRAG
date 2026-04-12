from __future__ import annotations

import argparse
import re
import time
from collections import deque
from collections.abc import Iterable
from datetime import UTC, datetime
from html import unescape as html_unescape
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse, urlunparse

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
from app.ingestion.http_client import robust_get
from app.ingestion.contracts import IngestionJobContext
from app.ingestion.orchestrator import IngestionOrchestrator
from sqlalchemy.orm import Session

_ = model_registry


def _default_database_url() -> str:
    db_path = BACKEND_ROOT.parent / "data" / "collection" / "staging" / "pdf_seed.db"
    return f"sqlite+pysqlite:///{db_path}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collect_pdf_seed",
        description="Collect a small batch of PDFs linked from a seed HTML page into a corpus DB.",
    )
    parser.add_argument("--database-url", default=_default_database_url())
    parser.add_argument("--source-key", required=True)
    parser.add_argument("--parser-version", default="pdf-seed-v1")
    parser.add_argument("--seed-url", action="append", required=True)
    parser.add_argument(
        "--seed-xhr",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="If true, fetch seed URLs as XHR/JSON (adds X-Requested-With + JSON Accept headers). Useful for DataTables-backed listings.",
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--document-only",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "If true, persist only canonical LegalDocument rows (skip chunking, embeddings, graph, and appeal projections). "
            "Recommended for high-volume collection runs; projections can be built later."
        ),
    )
    parser.add_argument(
        "--allow-underfilled",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="If true, do not exit non-zero when fewer than --limit PDFs are ingested (useful for long-running best-effort crawls).",
    )
    parser.add_argument("--court-name", default=None)
    parser.add_argument(
        "--doc-type",
        default="order",
        help="order|judgment|circular|notification|instruction",
    )
    parser.add_argument("--practice-area", action="append", default=[])
    parser.add_argument("--jurisdiction-binding", action="append", default=[])
    parser.add_argument("--jurisdiction-persuasive", action="append", default=[])
    parser.add_argument(
        "--ssl-verify",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable/disable TLS verification for seed + PDF downloads (use --no-ssl-verify for sites with bad chains).",
    )
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        help="Optional polite delay between HTTP requests (seconds). Use small values (e.g. 0.2) to reduce 403/rate-limit blocks.",
    )
    parser.add_argument(
        "--crawl-depth",
        type=int,
        default=0,
        help="Optionally crawl linked HTML pages up to this depth to discover PDFs (e.g., listing -> detail page -> PDF).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=50,
        help="Maximum number of HTML pages to fetch across seeds+crawl (prevents runaway crawling).",
    )
    parser.add_argument("--log-every", type=int, default=1)
    parser.add_argument(
        "--pdf-include-regex",
        action="append",
        default=[],
        help=(
            "Optional regex filter(s). If provided, only discovered document URLs matching at least one "
            "include pattern are kept. This also enables non-.pdf download routes such as /openfile/... "
            "when the include pattern matches them."
        ),
    )
    parser.add_argument(
        "--pdf-exclude-regex",
        action="append",
        default=[],
        help="Optional regex filter(s). Any PDF URL matching an exclude pattern is dropped.",
    )
    return parser


def _fetch_html(url: str, *, timeout_seconds: float, ssl_verify: bool, seed_xhr: bool) -> str:
    # Some portals block simplistic/bot-like headers (403), but allow normal browser-like requests.
    # Keep this reasonably realistic while still being stable across sites.
    headers: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    if seed_xhr:
        headers["X-Requested-With"] = "XMLHttpRequest"
        headers["Accept"] = "application/json,text/plain,*/*"
    resp = robust_get(url, headers=headers, timeout=timeout_seconds, verify=ssl_verify)
    resp.raise_for_status()
    return resp.text


def _normalize_candidate_url(seed_url: str, raw: str) -> str:
    raw = raw.strip().replace("\\/", "/").replace("\\", "/")
    joined = urljoin(seed_url, raw)
    parsed = urlparse(joined)
    return urlunparse(
        parsed._replace(
            path=quote(parsed.path, safe="/%:@()+,;-._~"),
            query=quote(parsed.query, safe="=&%:+,;@()-._~"),
        )
    )


def _looks_like_document_url(url: str, *, include_patterns: list[re.Pattern[str]]) -> bool:
    if ".pdf" in url.lower():
        return True
    return any(pattern.search(url) for pattern in include_patterns)


def _discover_pdf_links(
    seed_url: str,
    html: str,
    *,
    include_patterns: list[re.Pattern[str]],
) -> list[str]:
    # Some portals (e.g., DataTables server-side listings) return JSON where
    # HTML fragments are JSON-escaped (href=\"...\" and \/ in URLs). Do a
    # lightweight unescape so our existing HTML-ish regexes still work.
    html = html.replace("\\/", "/").replace('\\"', '"')
    html = html_unescape(html)
    links: set[str] = set()

    def _normalize_pdf_url(url: str) -> str:
        # Canonicalize known portals that advertise http links but serve https.
        if url.startswith("http://catjudgements.nic.in/"):
            return "https://catjudgements.nic.in/" + url.removeprefix("http://catjudgements.nic.in/")
        return url

    # 1) Standard document-bearing attributes
    for attr in ("href", "src", "data-href", "data-url"):
        for raw in re.findall(rf"{attr}=[\"']([^\"']+)[\"']", html, re.IGNORECASE):
            if not raw or raw.startswith("#"):
                continue
            if raw.lower().startswith("javascript:"):
                continue
            url = _normalize_candidate_url(seed_url, raw)
            if not _looks_like_document_url(url, include_patterns=include_patterns):
                continue
            links.add(_normalize_pdf_url(url.split("#")[0]))

    # 2) Common JS-driven document launches
    for raw in re.findall(r"""(?i)(?:window\.open|location\.href\s*=)\s*\(?\s*['"]([^'"]+)['"]""", html):
        url = _normalize_candidate_url(seed_url, raw)
        if not _looks_like_document_url(url, include_patterns=include_patterns):
            continue
        links.add(_normalize_pdf_url(url.split("#")[0]))

    # 3) Inline absolute URLs (e.g. iframe src='...file=https://...pdf')
    for raw in re.findall(r"https?://[^\s\"'<>]+\.pdf", html, re.IGNORECASE):
        links.add(_normalize_pdf_url(raw.split("#")[0]))

    # 4) Inline absolute URLs for non-.pdf download routes matched by include regex.
    if include_patterns:
        for raw in re.findall(r"https?://[^\s\"'<>]+", html, re.IGNORECASE):
            if not _looks_like_document_url(raw, include_patterns=include_patterns):
                continue
            links.add(_normalize_pdf_url(raw.split("#")[0]))

    # 5) Inline "file=<url>" parameters where the URL may be embedded
    for raw in re.findall(r"file=([^\s\"'<>]+)", html, re.IGNORECASE):
        url = _normalize_candidate_url(seed_url, raw)
        if not _looks_like_document_url(url, include_patterns=include_patterns):
            continue
        links.add(_normalize_pdf_url(url.split("#")[0]))

    return sorted(links)


def _discover_html_links(seed_url: str, html: str, *, allowed_netlocs: set[str]) -> list[str]:
    # Same rationale as _discover_pdf_links(): tolerate JSON-escaped HTML.
    html = html.replace("\\/", "/").replace('\\"', '"')
    html = html_unescape(html)
    def _normalize_special_urls(url: str) -> str:
        # DSpace RSS feeds sometimes emit Handle URLs that don't resolve publicly.
        # Map them back to the local portal so we can crawl item pages.
        # Example: http(s)://hdl.handle.net/123456789/144937 -> https://catjudgements.nic.in/handle/123456789/144937
        m = re.match(r"https?://hdl\.handle\.net/(\d+/\d+)$", url)
        if m:
            return f"https://catjudgements.nic.in/handle/{m.group(1)}"
        return url

    links: set[str] = set()
    for href in re.findall(r"href=[\"']([^\"']+)[\"']", html, re.IGNORECASE):
        if not href or href.startswith("#"):
            continue
        if href.lower().startswith("javascript:"):
            continue
        url = _normalize_special_urls(urljoin(seed_url, href))

        # Skip templated/static-site placeholders that occasionally leak into hrefs,
        # e.g. "${currentPath}" or "{{path}}". These are not routable URLs and
        # lead to noisy 404s on some portals.
        if "${" in url or "{{" in url or "{%" in url:
            continue

        # Many portals embed opaque tokens in URLs (e.g. query params containing "::").
        # These are rarely useful for document crawling and often lead to repeated 403s.
        if "::" in url:
            continue

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc and parsed.netloc not in allowed_netlocs:
            continue
        if ".pdf" in url.lower():
            continue

        path_lower = parsed.path.lower()
        # Skip obvious static assets.
        if any(
            path_lower.endswith(ext)
            for ext in (
                ".css",
                ".js",
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".svg",
                ".ico",
                ".woff",
                ".woff2",
                ".ttf",
                ".mp4",
                ".webm",
                ".zip",
                ".rar",
                ".7z",
                ".csv",
                ".xlsx",
                ".xls",
                ".doc",
                ".docx",
            )
        ):
            continue

        # Skip obvious CMS/admin action routes that are not document pages and frequently 403/time out.
        if any(
            seg in path_lower
            for seg in (
                "/admin",
                "/user",
                "/logout",
                "/login",
                "/node/add",
                "/edit",
                "/delete",
            )
        ):
            continue

        # Follow common HTML-ish pages (conservative but not .html-only).
        looks_like_html = (
            path_lower.endswith((".html", ".htm", ".php", ".jsp", ".do", ".aspx"))
            or "/handle/" in path_lower
            or path_lower.startswith("/browse")
            or path_lower.startswith("/feed/")
        )

        # Many government portals use extensionless content routes (e.g. /judicial/notice_board,
        # /order-date-wise, /page/foo). If the URL looks like a routable page (no file extension)
        # and it's within the allowed host, treat it as crawlable HTML.
        if not looks_like_html:
            last_segment = Path(parsed.path).name
            has_extension = "." in last_segment
            if parsed.path not in {"", "/"} and not has_extension:
                looks_like_html = True

        # Some portals paginate purely via query params, e.g. /whats-new?page=2.
        # Allow crawling those pagination links even when the path has no extension.
        is_pagination = bool(re.search(r"(?:^|&)page=\d+(?:&|$)", parsed.query))
        if is_pagination:
            looks_like_html = True
        if not looks_like_html:
            continue

        links.add(url.split("#")[0])

    # RSS/Atom feeds: extract item URLs from <link> elements.
    if "<rss" in html.lower() or "<feed" in html.lower():
        for raw in re.findall(r"<link>(https?://[^<]+)</link>", html, re.IGNORECASE):
            url = _normalize_special_urls(raw.strip())
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"}:
                continue
            if parsed.netloc and parsed.netloc not in allowed_netlocs:
                continue
            if ".pdf" in parsed.path.lower():
                continue
            if parsed.path in {"", "/"}:
                continue
            links.add(url.split("#")[0])
    def _crawl_priority(url: str) -> tuple[int, str]:
        # Heuristic ordering to reach document detail pages quickly.
        # Many portals (e.g., DSpace) only expose PDFs on /handle/... item pages.
        path = urlparse(url).path.lower()
        if "/handle/" in path:
            return (0, url)
        if "simple-search" in path:
            return (1, url)
        if "search" in path:
            return (2, url)
        if "browse" in path:
            return (3, url)
        return (4, url)

    return sorted(links, key=_crawl_priority)


def _stable_external_id(source_key: str, url: str) -> str:
    parsed = urlparse(url)
    tail = parsed.path.rstrip("/").split("/")[-1]
    if tail:
        return tail
    return f"{source_key}-{abs(hash(url))}"


def _chunks(items: Iterable[str], *, limit: int) -> list[str]:
    out: list[str] = []
    for item in items:
        out.append(item)
        if len(out) >= limit:
            break
    return out


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    engine = build_engine(args.database_url)
    Base.metadata.create_all(engine)

    seed_urls: list[str] = list(args.seed_url)

    include_patterns = [re.compile(p) for p in (args.pdf_include_regex or []) if str(p).strip()]
    exclude_patterns = [re.compile(p) for p in (args.pdf_exclude_regex or []) if str(p).strip()]

    def _pdf_url_allowed(url: str) -> bool:
        if include_patterns and not any(p.search(url) for p in include_patterns):
            return False
        if exclude_patterns and any(p.search(url) for p in exclude_patterns):
            return False
        return True

    allowed_netlocs = {urlparse(u).netloc for u in seed_urls if urlparse(u).netloc}
    queue: deque[tuple[str, int]] = deque((u, 0) for u in seed_urls)
    visited_pages: set[str] = set()
    pdf_links: set[str] = set()
    pending_pdfs: deque[tuple[str, str]] = deque()
    seen_pdfs: set[str] = set()

    max_pages = max(1, int(args.max_pages))
    crawl_depth = max(0, int(args.crawl_depth))

    target = max(0, int(args.limit))
    if target == 0:
        # Discovery-only mode.
        while queue and len(visited_pages) < max_pages:
            page_url, depth = queue.popleft()
            if page_url in visited_pages:
                continue
            visited_pages.add(page_url)

            try:
                html = _fetch_html(
                    page_url,
                    timeout_seconds=float(args.timeout_seconds),
                    ssl_verify=bool(args.ssl_verify),
                    seed_xhr=bool(args.seed_xhr) and depth == 0,
                )
            except Exception as exc:  # noqa: BLE001 - crawler should be resilient
                print(f"[crawl-skip] url={page_url} err={type(exc).__name__}: {exc}", flush=True)
                if float(args.sleep_seconds) > 0:
                    time.sleep(float(args.sleep_seconds))
                continue

            for pdf_url in _discover_pdf_links(
                page_url,
                html,
                include_patterns=include_patterns,
            ):
                if _pdf_url_allowed(pdf_url):
                    pdf_links.add(pdf_url)

            if depth < crawl_depth:
                for child in _discover_html_links(page_url, html, allowed_netlocs=allowed_netlocs):
                    if child not in visited_pages:
                        queue.append((child, depth + 1))

            if float(args.sleep_seconds) > 0:
                time.sleep(float(args.sleep_seconds))

        unique_links = sorted(pdf_links)
        if not unique_links:
            raise SystemExit(f"No PDF links found from seed(s): {seed_urls}")
        print(f"Discovered {len(unique_links)} PDF links; --limit=0 so nothing to ingest.")
        return 0

    adapter = PdfLegalDocumentAdapter()
    orchestrator = IngestionOrchestrator(document_only=bool(args.document_only))

    metadata: dict[str, object] = {
        "court_name": args.court_name,
        "doc_type": str(args.doc_type),
        "practice_areas": list(args.practice_area or []),
        "jurisdiction_binding": list(args.jurisdiction_binding or []),
        "jurisdiction_persuasive": list(args.jurisdiction_persuasive or []),
        "ssl_verify": bool(args.ssl_verify),
        "seed_urls": seed_urls,
        "collected_at": datetime.now(UTC).isoformat(),
    }

    with Session(engine) as session:
        ensure_collection_control_schema(session)
        ensure_source_url_index(session)
        successes = 0
        attempted = 0
        skipped_existing = 0

        def _partition_key(surface_url: str) -> str:
            parsed = urlparse(surface_url)
            return f"surface:{parsed.netloc}{parsed.path or '/'}"

        def _ingest_one(pdf_url: str, discovered_from: str) -> None:
            nonlocal successes, attempted, skipped_existing
            if successes >= target:
                return
            if document_exists_by_source_url(
                session,
                source_system=str(args.source_key),
                source_url=pdf_url,
            ):
                skipped_existing += 1
                record_source_partition(
                    session,
                    source_key=str(args.source_key),
                    partition_key=_partition_key(discovered_from),
                    surface_url=discovered_from,
                    partition_kind="seed_surface",
                    expected_hint=str(args.source_key),
                    status="RUNNING",
                    proof_note="discovered_existing_artifact",
                )
                return
            attempted += 1
            per_doc_metadata = {
                **metadata,
                "seed_url": discovered_from,
                "source_surface": discovered_from,
                "artifact_url": pdf_url,
                "provenance_tier": str(metadata.get("provenance_tier") or "official"),
                "collector_type": "search_or_seed_crawl",
            }
            context = IngestionJobContext(
                source_key=str(args.source_key),
                source_url=pdf_url,
                parser_version=str(args.parser_version),
                external_id=_stable_external_id(str(args.source_key), pdf_url),
                metadata=per_doc_metadata,
            )
            try:
                persisted = orchestrator.ingest(session, adapter, context)
            except Exception as exc:  # noqa: BLE001 - collector should be resilient
                session.rollback()
                record_source_partition(
                    session,
                    source_key=str(args.source_key),
                    partition_key=_partition_key(discovered_from),
                    surface_url=discovered_from,
                    partition_kind="seed_surface",
                    expected_hint=str(args.source_key),
                    status="BROKEN",
                    error_class=type(exc).__name__,
                    proof_note=str(exc)[:1000],
                )
                session.commit()
                print(
                    f"[skip] url={pdf_url} err={type(exc).__name__}: {exc}",
                    flush=True,
                )
                return

            successes += 1
            record_source_partition(
                session,
                source_key=str(args.source_key),
                partition_key=_partition_key(discovered_from),
                surface_url=discovered_from,
                partition_kind="seed_surface",
                expected_hint=str(args.source_key),
                ingested_increment=1,
                status="RUNNING",
                proof_note=f"last_artifact={pdf_url}",
            )
            if int(args.log_every) > 0 and (successes % int(args.log_every) == 0):
                print(
                    f"[{successes}/{target}] ingested doc_id={persisted.doc_id} url={pdf_url}",
                    flush=True,
                )

        # Crawl + ingest incrementally so long-running crawls start inserting quickly.
        while (queue or pending_pdfs) and len(visited_pages) < max_pages and successes < target:
            # Prefer ingesting already-discovered PDFs first.
            while pending_pdfs and successes < target:
                pdf_url, discovered_from = pending_pdfs.popleft()
                _ingest_one(pdf_url, discovered_from)

            if successes >= target:
                break
            if not queue:
                break

            page_url, depth = queue.popleft()
            if page_url in visited_pages:
                continue
            visited_pages.add(page_url)

            try:
                html = _fetch_html(
                    page_url,
                    timeout_seconds=float(args.timeout_seconds),
                    ssl_verify=bool(args.ssl_verify),
                    seed_xhr=bool(args.seed_xhr) and depth == 0,
                )
            except Exception as exc:  # noqa: BLE001 - crawler should be resilient
                print(f"[crawl-skip] url={page_url} err={type(exc).__name__}: {exc}", flush=True)
                if float(args.sleep_seconds) > 0:
                    time.sleep(float(args.sleep_seconds))
                continue

            for pdf_url in _discover_pdf_links(
                page_url,
                html,
                include_patterns=include_patterns,
            ):
                if not _pdf_url_allowed(pdf_url):
                    continue
                if pdf_url in seen_pdfs:
                    continue
                seen_pdfs.add(pdf_url)
                pdf_links.add(pdf_url)
                pending_pdfs.append((pdf_url, page_url))
                record_source_partition(
                    session,
                    source_key=str(args.source_key),
                    partition_key=_partition_key(page_url),
                    surface_url=page_url,
                    partition_kind="seed_surface",
                    expected_hint=str(args.source_key),
                    discovered_increment=1,
                    status="RUNNING",
                    proof_note=f"discovered_artifact={pdf_url}",
                )

            if depth < crawl_depth:
                for child in _discover_html_links(page_url, html, allowed_netlocs=allowed_netlocs):
                    if child not in visited_pages:
                        queue.append((child, depth + 1))

            if float(args.sleep_seconds) > 0:
                time.sleep(float(args.sleep_seconds))

        # Drain any remaining discovered PDFs (if crawling stopped early).
        while pending_pdfs and successes < target:
            pdf_url, discovered_from = pending_pdfs.popleft()
            _ingest_one(pdf_url, discovered_from)

        if successes < target:
            msg = (
                f"Only ingested {successes}/{target} PDFs "
                f"(attempted {attempted}, discovered {len(seen_pdfs)}, skipped_existing {skipped_existing}) "
                f"from seed(s): {seed_urls}"
            )
            if bool(args.allow_underfilled):
                print(msg, flush=True)
                return 0
            raise SystemExit(msg)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
