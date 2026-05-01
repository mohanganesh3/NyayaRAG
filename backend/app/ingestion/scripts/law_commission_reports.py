#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

try:
    from pypdf import PdfReader
except ModuleNotFoundError:  # pragma: no cover - handled at runtime for discover-only usage
    PdfReader = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_BASE_URL = "https://lawcommissionofindia.nic.in/"
DEFAULT_REPORTS_HUB_URL = urljoin(DEFAULT_BASE_URL, "law-commission-reports/")
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "raw" / "law_commission"
DEFAULT_INDEX_PATH = DEFAULT_OUTPUT_DIR / "law_commission_index.jsonl"
DEFAULT_SUMMARY_PATH = DEFAULT_OUTPUT_DIR / "law_commission_summary.json"
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NyayaRAG/1.0; law-commission-collector)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
REPORT_PAGE_HREF_PATTERN = re.compile(r"^/report_[a-z0-9]+/?$", re.IGNORECASE)
REPORT_PAGE_URL_PATTERN = re.compile(r"/report_[a-z0-9]+/?$", re.IGNORECASE)
REPORT_ROW_PATTERN = re.compile(r"^(?P<number>\d{1,3})\s+(?P<body>.+)$")
STANDALONE_REPORT_NUMBER_PATTERN = re.compile(r"^\d{1,3}$")
NOTE_ROW_PATTERN = re.compile(r"^[–-]\s*(?P<note>Dissent Note|Supplementary Note)\s+(?P<body>.+)$")
DATE_SUFFIX_PATTERN = re.compile(
    r"(?P<date>(?:\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})|\d{4})$",
)
DATE_LINE_PATTERN = re.compile(
    r"^(?:\d{4}|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})$",
)
ATTACHMENT_SIZE_PATTERN = re.compile(r"^\d+(?:\.\d+)?\s*(?:KB|MB)\)?$", re.IGNORECASE)
WHITESPACE_PATTERN = re.compile(r"\s+")
BLOCK_TAGS = {
    "article",
    "div",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "p",
    "section",
    "tr",
    "td",
    "th",
}


@dataclass(frozen=True, slots=True)
class CommissionPage:
    title: str
    url: str
    report_range: str | None
    chairman: str | None


@dataclass(frozen=True, slots=True)
class AnchorEvent:
    line_number: int
    href: str
    text: str


@dataclass(frozen=True, slots=True)
class ReportArtifact:
    commission_title: str
    commission_url: str
    report_number: str
    report_title: str
    submission_date: str | None
    note_kind: str | None
    part_label: str | None
    source_page_url: str
    pdf_url: str
    html_snapshot_path: str
    pdf_path: str | None = None
    pdf_sha256: str | None = None
    pdf_bytes: int | None = None
    pdf_page_count: int | None = None
    text_path: str | None = None
    text_sha256: str | None = None
    text_chars: int | None = None
    extraction_status: str = "pending"
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CollectionSummary:
    hub_url: str
    commissions_discovered: int
    report_artifacts: int
    downloaded_pdfs: int
    extracted_texts: int
    skipped_existing: int
    failed_items: int
    generated_at: str


class LineAndLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.links: list[AnchorEvent] = []
        self._anchor_href: str | None = None
        self._anchor_text_parts: list[str] = []
        self._anchor_start_line = 1
        self._line_number = 1
        self._skip_depth = 0

    @property
    def text(self) -> str:
        return "".join(self.parts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return
        if tag == "a":
            self._anchor_href = self._attr_value(attrs, "href")
            self._anchor_text_parts = []
            self._anchor_start_line = self._line_number
            return
        if tag in BLOCK_TAGS:
            self._append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth > 0:
            return
        if tag == "a" and self._anchor_href is not None:
            anchor_text = normalize_whitespace("".join(self._anchor_text_parts))
            self.links.append(
                AnchorEvent(
                    line_number=self._anchor_start_line,
                    href=unescape(self._anchor_href),
                    text=anchor_text,
                )
            )
            self._anchor_href = None
            self._anchor_text_parts = []
            return
        if tag in BLOCK_TAGS:
            self._append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._anchor_href is not None:
            self._anchor_text_parts.append(data)
        self._append(data)

    def _append(self, text: str) -> None:
        if not text:
            return
        self.parts.append(text)
        self._line_number += text.count("\n")

    def _attr_value(self, attrs: list[tuple[str, str | None]], key: str) -> str | None:
        for attr_key, attr_value in attrs:
            if attr_key.lower() == key and attr_value is not None:
                return attr_value
        return None


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "discover":
        discovered = discover_law_commission_pages(
            fetch_text(args.hub_url, timeout=args.timeout_seconds),
            args.hub_url,
        )
        payload = [
            extract_commission_page_details(
                fetch_text(page.url, timeout=args.timeout_seconds),
                page.url,
            )
            for page in discovered
        ]
        print(
            json.dumps(
                [asdict(page) for page in payload],
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    if args.command != "collect":
        parser.print_help()
        return 1

    summary = collect(
        hub_url=args.hub_url,
        output_dir=args.output_dir,
        index_path=args.index_path,
        summary_path=args.summary_path,
        limit=args.limit,
        delay_seconds=args.delay_seconds,
        skip_existing=args.skip_existing,
        extract_text=not args.no_extract_text,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(asdict(summary), indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Law Commission reports and PDFs.")
    subparsers = parser.add_subparsers(dest="command")

    discover_parser = subparsers.add_parser(
        "discover",
        help="Discover the Law Commission report pages from the reports hub.",
    )
    discover_parser.add_argument("--hub-url", default=DEFAULT_REPORTS_HUB_URL)
    discover_parser.add_argument("--timeout-seconds", type=float, default=30.0)

    collect_parser = subparsers.add_parser(
        "collect",
        help="Download report pages and PDFs, then write an index.",
    )
    collect_parser.add_argument("--hub-url", default=DEFAULT_REPORTS_HUB_URL)
    collect_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    collect_parser.add_argument("--index-path", type=Path, default=DEFAULT_INDEX_PATH)
    collect_parser.add_argument("--summary-path", type=Path, default=DEFAULT_SUMMARY_PATH)
    collect_parser.add_argument("--limit", type=int, default=None)
    collect_parser.add_argument("--delay-seconds", type=float, default=0.0)
    collect_parser.add_argument("--skip-existing", action="store_true")
    collect_parser.add_argument("--no-extract-text", action="store_true")
    collect_parser.add_argument("--timeout-seconds", type=float, default=30.0)

    return parser


def collect(
    *,
    hub_url: str,
    output_dir: Path,
    index_path: Path,
    summary_path: Path,
    limit: int | None,
    delay_seconds: float,
    skip_existing: bool,
    extract_text: bool,
    timeout_seconds: float,
) -> CollectionSummary:
    output_dir.mkdir(parents=True, exist_ok=True)
    html_dir = output_dir / "html"
    pdf_dir = output_dir / "pdfs"
    text_dir = output_dir / "texts"
    html_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    if extract_text:
        text_dir.mkdir(parents=True, exist_ok=True)

    hub_html = fetch_text(hub_url, timeout=timeout_seconds)
    hub_snapshot = html_dir / "law_commission_reports_hub.html"
    hub_snapshot.write_text(hub_html, encoding="utf-8")

    commissions = discover_law_commission_pages(hub_html, hub_url)
    if limit is not None:
        commissions = commissions[:limit]

    report_records: list[ReportArtifact] = []
    downloaded_pdfs = 0
    extracted_texts = 0
    skipped_existing = 0
    failed_items = 0

    for commission in commissions:
        page_html = fetch_text(commission.url, timeout=timeout_seconds)
        commission_details = extract_commission_page_details(page_html, commission.url)
        commission_slug = slug_from_url(commission.url)
        commission_html_path = html_dir / f"{commission_slug}.html"
        commission_html_path.write_text(page_html, encoding="utf-8")

        report_rows = parse_law_commission_page(
            page_html,
            commission.url,
            commission_details.title,
        )
        for row in report_rows:
            pdf_filename = filename_from_url(row.pdf_url)
            pdf_path = pdf_dir / commission_slug / pdf_filename
            text_path = text_dir / commission_slug / f"{pdf_filename}.txt"
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            if extract_text:
                text_path.parent.mkdir(parents=True, exist_ok=True)

            if skip_existing and pdf_path.exists():
                skipped_existing += 1

                text_value = None
                text_sha = None
                text_chars = None

                # If we are extracting text, ensure we have a text artifact even when the PDF
                # already exists (avoid re-downloading, but do backfill missing text files).
                if extract_text:
                    if text_path.exists():
                        text_value = text_path.read_text(encoding="utf-8", errors="ignore")
                    else:
                        try:
                            text_value = extract_pdf_text(pdf_path)
                            text_path.write_text(text_value, encoding="utf-8")
                            extracted_texts += 1
                        except Exception:  # noqa: BLE001 - best-effort backfill
                            text_value = None

                    if text_value is not None:
                        text_sha = sha256(text_value.encode("utf-8")).hexdigest()
                        text_chars = len(text_value)

                report_records.append(
                    ReportArtifact(
                        commission_title=row.commission_title,
                        commission_url=row.commission_url,
                        report_number=row.report_number,
                        report_title=row.report_title,
                        submission_date=row.submission_date,
                        note_kind=row.note_kind,
                        part_label=row.part_label,
                        source_page_url=row.source_page_url,
                        pdf_url=row.pdf_url,
                        html_snapshot_path=str(commission_html_path),
                        pdf_path=str(pdf_path),
                        text_path=str(text_path) if (extract_text and text_value is not None) else None,
                        text_sha256=text_sha,
                        text_chars=text_chars,
                        extraction_status="skipped_existing",
                    )
                )
                continue

            try:
                pdf_bytes = download_binary(row.pdf_url, pdf_path, timeout=timeout_seconds)
                downloaded_pdfs += 1
                pdf_sha = sha256(pdf_path.read_bytes()).hexdigest()
                pdf_page_count = count_pdf_pages(pdf_path)

                text_chars = None
                text_sha = None
                text_value = None
                if extract_text:
                    text_value = extract_pdf_text(pdf_path)
                    text_path.write_text(text_value, encoding="utf-8")
                    text_sha = sha256(text_value.encode("utf-8")).hexdigest()
                    text_chars = len(text_value)
                    extracted_texts += 1

                report_records.append(
                    ReportArtifact(
                        commission_title=row.commission_title,
                        commission_url=row.commission_url,
                        report_number=row.report_number,
                        report_title=row.report_title,
                        submission_date=row.submission_date,
                        note_kind=row.note_kind,
                        part_label=row.part_label,
                        source_page_url=row.source_page_url,
                        pdf_url=row.pdf_url,
                        html_snapshot_path=str(commission_html_path),
                        pdf_path=str(pdf_path),
                        pdf_sha256=pdf_sha,
                        pdf_bytes=pdf_bytes,
                        pdf_page_count=pdf_page_count,
                        text_path=str(text_path) if extract_text else None,
                        text_sha256=text_sha,
                        text_chars=text_chars,
                        extraction_status="downloaded",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                failed_items += 1
                report_records.append(
                    ReportArtifact(
                        commission_title=row.commission_title,
                        commission_url=row.commission_url,
                        report_number=row.report_number,
                        report_title=row.report_title,
                        submission_date=row.submission_date,
                        note_kind=row.note_kind,
                        part_label=row.part_label,
                        source_page_url=row.source_page_url,
                        pdf_url=row.pdf_url,
                        html_snapshot_path=str(commission_html_path),
                        pdf_path=str(pdf_path),
                        text_path=str(text_path) if extract_text else None,
                        extraction_status="failed",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )

            if delay_seconds > 0:
                time.sleep(delay_seconds)

    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", encoding="utf-8") as handle:
        for record in report_records:
            handle.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n")

    summary = CollectionSummary(
        hub_url=hub_url,
        commissions_discovered=len(commissions),
        report_artifacts=len(report_records),
        downloaded_pdfs=downloaded_pdfs,
        extracted_texts=extracted_texts,
        skipped_existing=skipped_existing,
        failed_items=failed_items,
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(asdict(summary), indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return summary


def discover_law_commission_pages(html: str, hub_url: str) -> list[CommissionPage]:
    parser = LineAndLinkParser()
    parser.feed(html)
    lines = parser.text.replace("\r", "\n").split("\n")
    links_by_line = _group_links_by_line(parser.links)
    discovered: list[CommissionPage] = []
    seen_urls: set[str] = set()

    for line_number, line in enumerate(lines, start=1):
        line = normalize_whitespace(line)
        if not line:
            continue
        line_links = links_by_line.get(line_number, [])
        report_links = [
            link
            for link in line_links
            if REPORT_PAGE_URL_PATTERN.search(link.href)
            or REPORT_PAGE_HREF_PATTERN.match(urlparse(link.href).path)
        ]
        if not report_links:
            continue
        title = _extract_commission_title(line)
        if title is None:
            title = link_title_fallback(report_links[0].href)
        report_range = _extract_report_range(line)
        chairman = _extract_chairman(line)
        for link in report_links:
            absolute_url = urljoin(hub_url, link.href)
            if absolute_url in seen_urls:
                continue
            seen_urls.add(absolute_url)
            discovered.append(
                CommissionPage(
                    title=title,
                    url=absolute_url,
                    report_range=report_range,
                    chairman=chairman,
                )
            )
    return discovered


def extract_commission_page_details(html: str, page_url: str) -> CommissionPage:
    title = extract_page_title(html) or link_title_fallback(page_url)
    parser = LineAndLinkParser()
    parser.feed(html)
    lines = parser.text.replace("\r", "\n").split("\n")
    normalized_lines = [normalize_whitespace(line) for line in lines if normalize_whitespace(line)]
    report_range = None
    chairman = None
    for line in normalized_lines:
        if report_range is None:
            report_range = _extract_report_range(line)
        if chairman is None:
            chairman = _extract_chairman(line)
        if report_range is not None and chairman is not None:
            break
    return CommissionPage(
        title=title,
        url=page_url,
        report_range=report_range,
        chairman=chairman,
    )


@dataclass(frozen=True, slots=True)
class ParsedReportRow:
    commission_title: str
    commission_url: str
    report_number: str
    report_title: str
    submission_date: str | None
    note_kind: str | None
    part_label: str | None
    source_page_url: str
    pdf_url: str


@dataclass(slots=True)
class ReportBlock:
    report_number: str
    note_kind: str | None
    title_parts: list[str] = field(default_factory=list)
    submission_date: str | None = None
    links: list[AnchorEvent] = field(default_factory=list)


@dataclass(slots=True)
class ReportStart:
    report_number: str
    title_parts: list[str]
    submission_date: str | None


@dataclass(slots=True)
class NoteStart:
    note_kind: str
    title_parts: list[str]
    submission_date: str | None


def parse_law_commission_page(
    html: str,
    page_url: str,
    commission_title: str,
) -> list[ParsedReportRow]:
    parser = LineAndLinkParser()
    parser.feed(html)
    lines = parser.text.replace("\r", "\n").split("\n")
    links_by_line = _group_links_by_line(parser.links)
    rows: list[ParsedReportRow] = []
    current_block: ReportBlock | None = None

    def flush_current_block() -> None:
        nonlocal current_block
        if current_block is None:
            return
        rows.extend(
            _materialize_report_rows(
                commission_title=commission_title,
                commission_url=page_url,
                source_page_url=page_url,
                block=current_block,
            )
        )
        current_block = None

    for line_number, line in enumerate(lines, start=1):
        line = normalize_whitespace(line)
        if not line:
            continue
        line_links = links_by_line.get(line_number, [])
        report_start = _parse_report_start(line)
        if report_start is not None:
            flush_current_block()
            current_block = ReportBlock(
                report_number=report_start.report_number,
                note_kind=None,
                title_parts=report_start.title_parts,
                submission_date=report_start.submission_date,
                links=list(line_links),
            )
            continue

        note_start = _parse_note_start(line)
        if note_start is not None and current_block is not None:
            report_number = current_block.report_number
            flush_current_block()
            current_block = ReportBlock(
                report_number=report_number,
                note_kind=note_start.note_kind,
                title_parts=note_start.title_parts,
                submission_date=note_start.submission_date,
                links=list(line_links),
            )
            continue

        if current_block is None:
            continue

        if line_links:
            current_block.links.extend(line_links)
            if _is_attachment_label_line(line, line_links):
                continue
        if current_block.links and _is_attachment_continuation_line(line):
            continue

        if _is_date_line(line) and current_block.submission_date is None:
            current_block.submission_date = line
            continue

        trailing_date = _extract_date_suffix(line)
        if (
            current_block.submission_date is None
            and trailing_date is not None
            and not trailing_date.isdigit()
        ):
            current_block.submission_date = trailing_date
            prefix = strip_date_suffix(line)
            if prefix and not _is_report_page_noise(prefix):
                current_block.title_parts.append(prefix)
            continue

        if _is_report_page_noise(line):
            continue

        current_block.title_parts.append(line)

    flush_current_block()
    return rows


def _parse_report_start(line: str) -> ReportStart | None:
    match = REPORT_ROW_PATTERN.match(line)
    if match is not None:
        body = normalize_whitespace(match.group("body"))
        return ReportStart(
            report_number=match.group("number"),
            title_parts=[strip_date_suffix(body)] if strip_date_suffix(body) else [],
            submission_date=_extract_date_suffix(body),
        )
    if STANDALONE_REPORT_NUMBER_PATTERN.match(line):
        return ReportStart(report_number=line, title_parts=[], submission_date=None)
    return None


def _parse_note_start(line: str) -> NoteStart | None:
    match = NOTE_ROW_PATTERN.match(line)
    if match is None:
        return None
    body = normalize_whitespace(match.group("body"))
    return NoteStart(
        note_kind=match.group("note").replace(" ", "_").lower(),
        title_parts=[strip_date_suffix(body) or match.group("note")],
        submission_date=_extract_date_suffix(body),
    )


def _materialize_report_rows(
    *,
    commission_title: str,
    commission_url: str,
    source_page_url: str,
    block: ReportBlock,
) -> list[ParsedReportRow]:
    report_title = normalize_whitespace(" ".join(block.title_parts))
    if not report_title:
        report_title = "Untitled report"
    rows: list[ParsedReportRow] = []
    for link in block.links:
        if not link.href.lower().endswith(".pdf") and "pdf" not in link.text.lower():
            continue
        rows.append(
            ParsedReportRow(
                commission_title=commission_title,
                commission_url=commission_url,
                report_number=block.report_number,
                report_title=report_title,
                submission_date=block.submission_date,
                note_kind=block.note_kind,
                part_label=link.text or None,
                source_page_url=source_page_url,
                pdf_url=urljoin(source_page_url, link.href),
            )
        )
    return rows


def fetch_text(url: str, timeout: float = 30.0) -> str:
    request = Request(url, headers=REQUEST_HEADERS)
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def download_binary(url: str, destination: Path, timeout: float = 30.0, attempts: int = 3) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = Request(url, headers=REQUEST_HEADERS)
            with urlopen(request, timeout=timeout) as response:
                payload = response.read()
            destination.write_bytes(payload)
            return len(payload)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(min(5.0, attempt * 1.5))
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to download {url}")


def extract_pdf_text(pdf_path: Path) -> str:
    _require_pdf_reader()
    reader = PdfReader(str(pdf_path))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text.rstrip())
    return "\n\n".join(page for page in pages if page).strip()


def count_pdf_pages(pdf_path: Path) -> int:
    _require_pdf_reader()
    reader = PdfReader(str(pdf_path))
    return len(reader.pages)


def normalize_lines(text: str) -> list[str]:
    return [
        normalize_whitespace(line)
        for line in text.replace("\r", "\n").split("\n")
        if normalize_whitespace(line)
    ]


def normalize_whitespace(value: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", unescape(value)).strip()


def strip_date_suffix(text: str) -> str:
    cleaned = normalize_whitespace(text)
    match = DATE_SUFFIX_PATTERN.search(cleaned)
    if match is None:
        return cleaned.rstrip(" .:-")
    return cleaned[: match.start()].rstrip(" .:-")


def extract_submission_date(text: str) -> str | None:
    return _extract_date_suffix(text)


def _extract_date_suffix(text: str) -> str | None:
    match = DATE_SUFFIX_PATTERN.search(normalize_whitespace(text))
    return match.group("date") if match is not None else None


def _is_date_line(line: str) -> bool:
    return DATE_LINE_PATTERN.fullmatch(normalize_whitespace(line)) is not None


def _is_report_page_noise(line: str) -> bool:
    normalized = normalize_whitespace(line)
    return normalized in {
        "Report No.",
        "Subject",
        "Year of submission",
        "Download pdf",
        "Download PDF",
        "Accessible",
        "Click Here",
    } or normalized.startswith("Chairman")


def _is_attachment_label_line(line: str, line_links: list[AnchorEvent]) -> bool:
    normalized = normalize_whitespace(line).lower()
    if normalized.startswith("accessible") or normalized.startswith("click here"):
        return True
    if normalized.startswith("part "):
        return True
    return any(
        link.text.lower().startswith("accessible") or link.text.lower().startswith("part ")
        for link in line_links
    )


def _is_attachment_continuation_line(line: str) -> bool:
    normalized = normalize_whitespace(line)
    return bool(ATTACHMENT_SIZE_PATTERN.fullmatch(normalized) or normalized == "|")


def _group_links_by_line(links: list[AnchorEvent]) -> dict[int, list[AnchorEvent]]:
    grouped: dict[int, list[AnchorEvent]] = {}
    for link in links:
        grouped.setdefault(link.line_number, []).append(link)
    return grouped


def _extract_commission_title(line: str) -> str | None:
    prefix = line.split("(", 1)[0].strip()
    if prefix and "Law Commission" in prefix:
        return prefix
    if prefix and "Commission" in prefix:
        return prefix
    return None


def _extract_report_range(line: str) -> str | None:
    match = re.search(r"\(\s*(?P<range>\d+\s+to\s+\d+)\s*\)", line)
    return match.group("range") if match is not None else None


def _extract_chairman(line: str) -> str | None:
    match = re.search(r"\((?P<chairman>Chairman[^)]*)\)", line)
    return match.group("chairman") if match is not None else None


def link_title_fallback(url: str) -> str:
    slug = slug_from_url(url)
    return slug.replace("_", " ").replace("-", " ").title()


def extract_page_title(html: str) -> str | None:
    patterns = (
        re.compile(
            r"<meta[^>]+name=[\"']title[\"'][^>]+content=[\"'](?P<title>[^\"']+)[\"']",
            re.IGNORECASE,
        ),
        re.compile(r"<title>(?P<title>.*?)</title>", re.IGNORECASE | re.DOTALL),
        re.compile(r"<h1[^>]*>(?P<title>.*?)</h1>", re.IGNORECASE | re.DOTALL),
    )
    for pattern in patterns:
        match = pattern.search(html)
        if match is None:
            continue
        title = normalize_whitespace(match.group("title"))
        title = re.sub(
            r"\s*\|\s*Law Commission of India\s*\|\s*India$",
            "",
            title,
            flags=re.IGNORECASE,
        )
        title = re.sub(
            r"\s*\|\s*Law Commission of India$",
            "",
            title,
            flags=re.IGNORECASE,
        )
        if title:
            return title
    return None


def _require_pdf_reader() -> None:
    if PdfReader is None:
        raise RuntimeError(
            "pypdf is required for PDF extraction; install the backend dependencies or run "
            "the script inside the project virtual environment."
        )


def slug_from_url(url: str) -> str:
    parsed = urlparse(url)
    slug = Path(parsed.path.rstrip("/")).name
    return slug or "index"


def filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    filename = Path(parsed.path).name
    if not filename.lower().endswith(".pdf"):
        filename = f"{filename}.pdf"
    return filename


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
