from __future__ import annotations

import argparse
from html import unescape as html_unescape
import re
from datetime import UTC, datetime
from hashlib import sha256
from urllib.parse import urljoin, urlparse

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

EGAZETTE_BASE = "https://egazette.gov.in/Default.aspx"
EGAZETTE_PDF_BASE = "https://egazette.gov.in/WriteReadData/"


def _default_database_url() -> str:
    db_path = BACKEND_ROOT.parent / "data" / "collection" / "staging" / "egazette.db"
    return f"sqlite+pysqlite:///{db_path}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collect_egazette_recent_uploads",
        description=(
            "Best-effort collector for eGazette (egazette.gov.in) RecentUploads categories. "
            "This portal uses ASP.NET cookieless sessions encoded in the URL; we start from Default.aspx to obtain a live session path, "
            "then crawl RecentUploads pages for PDF-like links and ingest them."
        ),
    )
    parser.add_argument("--database-url", default=_default_database_url())
    parser.add_argument(
        "--source-key",
        default="gazette",
        help="Source key to persist on documents (default: gazette).",
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--document-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "If true (default), persist only canonical LegalDocument rows (skip chunking, embeddings, graph, and appeal projections). "
            "Recommended for high-volume collection runs."
        ),
    )
    parser.add_argument(
        "--allow-underfilled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If true, do not exit non-zero when fewer than --limit PDFs are ingested.",
    )
    parser.add_argument("--parser-version", default="egazette-recent-uploads-v1")
    parser.add_argument("--ssl-verify", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        help="Repeatable. RecentUploads category IDs (e.g., 1..5). Defaults to 1..5 if omitted.",
    )
    parser.add_argument(
        "--include-viewgazette",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If true, treat ViewGazette/ViewGazette.aspx links as PDF candidates even when they don't end with .pdf.",
    )
    parser.add_argument(
        "--crawl-depth",
        type=int,
        default=0,
        help="Optional: follow non-PDF HTML links from RecentUploads pages up to this depth to discover PDFs.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=30,
        help="Max HTML pages to fetch across categories+crawl.",
    )
    return parser


def _headers(*, referer: str | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://egazette.gov.in",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def _is_pdf_candidate(url: str, *, include_viewgazette: bool) -> bool:
    u = url.lower()
    if ".pdf" in u:
        return True
    if include_viewgazette and ("viewgazette" in u or "gazette" in u and "view" in u):
        return True
    return False


def _discover_links(page_url: str, html: str) -> tuple[list[str], list[str]]:
    pdfs: set[str] = set()
    htmls: set[str] = set()

    for attr in ("href", "src"):
        for raw in re.findall(rf"{attr}=[\"']([^\"']+)[\"']", html, flags=re.IGNORECASE):
            if not raw or raw.startswith("#"):
                continue
            if raw.lower().startswith("javascript:"):
                continue
            abs_url = urljoin(page_url, raw)
            parsed = urlparse(abs_url)
            if parsed.scheme not in {"http", "https"}:
                continue
            if abs_url.lower().endswith((
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
            )):
                continue
            if _is_pdf_candidate(abs_url, include_viewgazette=True):
                pdfs.add(abs_url.split("#")[0])
            else:
                htmls.add(abs_url.split("#")[0])

    return sorted(pdfs), sorted(htmls)


def _parse_hidden_inputs(html: str) -> dict[str, str]:
    payload: dict[str, str] = {}
    for m in re.finditer(r'<input[^>]+type="hidden"[^>]*>', html, flags=re.IGNORECASE):
        inp = m.group(0)
        name_m = re.search(r'name="([^"]+)"', inp)
        val_m = re.search(r'value="([^"]*)"', inp)
        if name_m is None:
            continue
        payload[name_m.group(1)] = val_m.group(1) if val_m else ""
    return payload


def _extract_recent_upload_rows(html: str) -> list[dict[str, str]]:
    # RecentUploads uses an ASP.NET GridView with spans like:
    # <span id="gvGazetteList_lbl_UGID_0">CG-DL-E-30032026-271426</span>
    # Extract values by index.
    def _grab(field: str) -> dict[int, str]:
        pattern = re.compile(
            rf'gvGazetteList_lbl_{re.escape(field)}_(\d+)"[^>]*>([^<]+)<',
            flags=re.IGNORECASE,
        )
        out: dict[int, str] = {}
        for i, raw in pattern.findall(html):
            try:
                idx = int(i)
            except ValueError:
                continue
            out[idx] = html_unescape(raw).strip()
        return out

    ugid = _grab("UGID")
    publish_date = _grab("PublishDate")
    issue_date = _grab("IssueDate")
    subject = _grab("Subject")
    ministry = _grab("Ministry")
    department = _grab("Department")
    office = _grab("Office")
    category = _grab("Category")
    part_section = _grab("PartSection")
    file_size = _grab("FileSize")

    rows: list[dict[str, str]] = []
    for idx in sorted(ugid.keys()):
        rows.append(
            {
                "ugid": ugid.get(idx, ""),
                "publish_date": publish_date.get(idx, ""),
                "issue_date": issue_date.get(idx, ""),
                "subject": subject.get(idx, ""),
                "ministry": ministry.get(idx, ""),
                "department": department.get(idx, ""),
                "office": office.get(idx, ""),
                "category": category.get(idx, ""),
                "part_section": part_section.get(idx, ""),
                "file_size": file_size.get(idx, ""),
            }
        )
    return rows


def _ugid_to_pdf_url(ugid: str, publish_date: str) -> str | None:
    # UGID format typically ends with a numeric document id, e.g. CG-DL-E-30032026-271426
    parts = [p for p in ugid.split("-") if p]
    if not parts:
        return None
    doc_num = parts[-1]
    if not doc_num.isdigit():
        return None

    year = publish_date.split("-")[-1].strip() if publish_date else ""
    if not year.isdigit():
        # Fallback: try to locate a 4-digit year inside the UGID.
        m = re.search(r"(19\d{2}|20\d{2})", ugid)
        year = m.group(1) if m else str(datetime.now(UTC).year)

    return urljoin(EGAZETTE_PDF_BASE, f"{year}/{doc_num}.pdf")


def _stable_external_id(source_key: str, url: str) -> str:
    tail = urlparse(url).path.rstrip("/").split("/")[-1]
    if tail:
        return tail
    return f"{source_key}-{sha256(url.encode('utf-8')).hexdigest()[:16]}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    engine = build_engine(args.database_url)
    Base.metadata.create_all(engine)

    target = max(0, int(args.limit))
    if target == 0:
        print("--limit=0 so nothing to ingest.")
        return 0

    categories = [str(c).strip() for c in (args.category or []) if str(c).strip()]
    if not categories:
        categories = ["1", "2", "3", "4", "5"]

    max_pages = max(1, int(args.max_pages))
    crawl_depth = max(0, int(args.crawl_depth))

    session = requests.Session()

    # 1) Obtain a live session-encoded base path by visiting Default.aspx.
    landing = session.get(
        EGAZETTE_BASE,
        headers=_headers(),
        timeout=float(args.timeout_seconds),
        verify=bool(args.ssl_verify),
        allow_redirects=True,
    )
    landing.raise_for_status()
    base = landing.url.rsplit("/", 1)[0] + "/"
    landing_referer = landing.url

    adapter = PdfLegalDocumentAdapter()
    orchestrator = IngestionOrchestrator(document_only=bool(args.document_only))

    successes = 0
    attempted = 0
    fetched_pages = 0

    # Track external IDs to avoid re-ingesting the same UGID within a run.
    seen_external_ids: set[str] = set()

    with Session(engine) as db_session:
        for cat in categories:
            if fetched_pages >= max_pages or successes >= target:
                break

            category_url = urljoin(base, f"RecentUploads.aspx?Category={cat}")
            try:
                resp = session.get(
                    category_url,
                    headers=_headers(referer=landing_referer),
                    timeout=float(args.timeout_seconds),
                    verify=bool(args.ssl_verify),
                    allow_redirects=True,
                )
                resp.raise_for_status()
                fetched_pages += 1
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[crawl-skip] url={category_url} err={type(exc).__name__}: {exc}",
                    flush=True,
                )
                continue

            if resp.url.lower().endswith("/error.aspx") or "pagenotfound" in resp.text.lower():
                print(f"[portal-blocked] url={category_url} final={resp.url}", flush=True)
                continue

            current_html = resp.text
            current_url = resp.url
            page_no = 1
            last_page_ugids: list[str] | None = None

            while fetched_pages <= max_pages and successes < target:
                rows = _extract_recent_upload_rows(current_html)
                page_ugids = [r.get("ugid", "").strip() for r in rows if r.get("ugid")]
                if not page_ugids:
                    break
                if last_page_ugids is not None and page_ugids == last_page_ugids:
                    # Paging reached the end (or portal returned the same page again).
                    break
                last_page_ugids = list(page_ugids)

                for row in rows:
                    if successes >= target:
                        break

                    ugid = row.get("ugid", "").strip()
                    if not ugid or ugid in seen_external_ids:
                        continue

                    pdf_url = _ugid_to_pdf_url(ugid, row.get("publish_date", ""))
                    if not pdf_url:
                        continue

                    seen_external_ids.add(ugid)
                    attempted += 1
                    context = IngestionJobContext(
                        source_key=str(args.source_key),
                        source_url=pdf_url,
                        parser_version=str(args.parser_version),
                        external_id=ugid,
                        metadata={
                            "court_name": "Gazette of India (eGazette)",
                            "doc_type": "notification",
                            "practice_areas": ["administrative", "statutory"],
                            "jurisdiction_binding": ["All India"],
                            "jurisdiction_persuasive": ["All India"],
                            "title": row.get("subject") or "Gazette notification",
                            "date_text": row.get("publish_date") or row.get("issue_date"),
                            "ssl_verify": bool(args.ssl_verify),
                            "seed_urls": [EGAZETTE_BASE],
                            "collected_at": datetime.now(UTC).isoformat(),
                            "ugid": ugid,
                            "ministry": row.get("ministry"),
                            "department": row.get("department"),
                            "office": row.get("office"),
                            "category": row.get("category"),
                            "part_section": row.get("part_section"),
                            "file_size": row.get("file_size"),
                            # PDFs are served directly from /WriteReadData and usually do not require cookies,
                            # but adding a referer can reduce sporadic 403 blocks.
                            "http_headers": {"Referer": current_url},
                        },
                    )

                    try:
                        persisted = orchestrator.ingest(db_session, adapter, context)
                    except Exception as exc:  # noqa: BLE001
                        db_session.rollback()
                        print(f"[skip] url={pdf_url} err={type(exc).__name__}: {exc}", flush=True)
                        continue

                    successes += 1
                    print(
                        f"[{successes}/{target}] ingested doc_id={persisted.doc_id} url={pdf_url}",
                        flush=True,
                    )

                if fetched_pages >= max_pages or successes >= target:
                    break

                # Advance to next page within this category using GridView paging.
                page_no += 1
                payload = _parse_hidden_inputs(current_html)
                payload["__EVENTTARGET"] = "gvGazetteList"
                payload["__EVENTARGUMENT"] = f"Page${page_no}"
                try:
                    nxt = session.post(
                        category_url,
                        data=payload,
                        headers=_headers(referer=current_url),
                        timeout=float(args.timeout_seconds),
                        verify=bool(args.ssl_verify),
                        allow_redirects=True,
                    )
                    nxt.raise_for_status()
                    fetched_pages += 1
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[crawl-skip] url={category_url} err={type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    break

                if nxt.url.lower().endswith("/error.aspx") or "pagenotfound" in nxt.text.lower():
                    print(f"[portal-blocked] url={category_url} final={nxt.url}", flush=True)
                    break

                current_html = nxt.text
                current_url = nxt.url

        if successes < target:
            msg = f"Only ingested {successes}/{target} PDFs (attempted {attempted}, pages={fetched_pages})."
            if bool(args.allow_underfilled):
                print(msg, flush=True)
                return 0
            raise SystemExit(msg)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
