from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SEARCH_URL = (
    "https://www.indiacode.nic.in/handle/123456789/1362/simple-search"
    "?query=&searchradio=acts&sort_by=dc.title_sort&order=ASC&rpp={rpp}&etal=0&start={start}"
)
DETAIL_URL = "https://www.indiacode.nic.in/handle/123456789/{handle}?view_type=browse"
DEFAULT_OUTPUT_JSON = Path("data/collection/india_code_act_handles.json")
DEFAULT_REPORT = Path("data/collection/india_code_discovery_report.md")
DEFAULT_RESEARCH = Path("data/collection/india_code_research_findings.md")
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
RESULTS_COUNT_PATTERN = re.compile(r"Results\s+\d+-\d+\s+of\s+(\d+)", re.IGNORECASE)
RESULT_ROW_PATTERN = re.compile(
    r"<tr><td headers=\"t1\"[^>]*>(?P<enactment_date>.*?)</td>"
    r"<td headers=\"t2\"[^>]*><em>(?P<act_number>.*?)</em></td>"
    r"<td headers=\"t3\"[^>]*>(?P<title>.*?)</td>"
    r"<td headers=\"t4\"[^>]*><a href=\"(?P<href>"
    r"/handle/123456789/(?P<handle>\d+)\?view_type=search[^\"]*)\">"
    r"View\.\.\.</a></td></tr>",
    re.IGNORECASE | re.DOTALL,
)
YEAR_PATTERN = re.compile(r"(?:19|20)\d{2}")


@dataclass(slots=True)
class PageResult:
    start: int
    count: int
    handles: list[dict[str, str]]


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover India Code central-act handles.")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--research", type=Path, default=DEFAULT_RESEARCH)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    args = parser.parse_args()

    output_json = args.output_json.resolve()
    report_path = args.report.resolve()
    research_path = args.research.resolve()

    discovery = discover_handles(page_size=args.page_size, delay_seconds=args.delay_seconds)

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(discovery["handles"], indent=2, ensure_ascii=True),
        encoding="utf-8",
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(build_report(discovery), encoding="utf-8")

    if not research_path.exists():
        research_path.parent.mkdir(parents=True, exist_ok=True)
        research_path.write_text(build_research_notes(discovery), encoding="utf-8")

    print(json.dumps(
        {
            "expected_count": discovery["expected_count"],
            "discovered_count": len(discovery["handles"]),
            "failed_offsets": discovery["failed_offsets"],
            "output_json": str(output_json),
            "report": str(report_path),
            "research": str(research_path),
        },
        indent=2,
        sort_keys=True,
    ))
    return 0


def discover_handles(page_size: int, delay_seconds: float) -> dict[str, object]:
    first_page = fetch_page(0, page_size)
    expected_count = first_page.count
    total_pages = max(1, math.ceil(expected_count / page_size))

    handles: list[dict[str, str]] = []
    seen_handles: set[str] = set()
    failed_offsets: list[dict[str, object]] = []

    for page_number in range(total_pages):
        start = page_number * page_size
        try:
            page = first_page if start == 0 else fetch_page(start, page_size)
        except Exception as exc:  # noqa: BLE001
            failed_offsets.append(
                {
                    "start": start,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue

        for item in page.handles:
            handle = item["handle"]
            if handle in seen_handles:
                continue
            seen_handles.add(handle)
            handles.append(item)

        if delay_seconds > 0 and page_number < total_pages - 1:
            sleep(delay_seconds)

    return {
        "expected_count": expected_count,
        "handles": handles,
        "failed_offsets": failed_offsets,
    }


def fetch_page(start: int, page_size: int) -> PageResult:
    url = SEARCH_URL.format(rpp=page_size, start=start)
    body = fetch_text(url)
    count_match = RESULTS_COUNT_PATTERN.search(body)
    if count_match is None:
        raise ValueError(f"Could not determine total result count from start={start}")

    result_count = int(count_match.group(1))
    rows = parse_rows(body)
    handles = []
    for row in rows:
        title = row["title"]
        year = extract_year(title)
        handle = row["handle"]
        handles.append(
            {
                "handle": handle,
                "title": title,
                "year": year,
                "detail_url": DETAIL_URL.format(handle=handle),
            }
        )

    return PageResult(start=start, count=result_count, handles=handles)


def parse_rows(html: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for match in RESULT_ROW_PATTERN.finditer(html):
        title = clean_text(match.group("title"))
        handle = match.group("handle")
        if not title or not handle:
            continue
        rows.append(
            {
                "enactment_date": clean_text(match.group("enactment_date")),
                "act_number": clean_text(match.group("act_number")),
                "title": title,
                "handle": handle,
            }
        )
    return rows


def fetch_text(url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        request = Request(url, headers=REQUEST_HEADERS)
        try:
            with urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", errors="ignore")
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 503} or attempt >= 3:
                raise
        except (TimeoutError, URLError) as exc:
            last_error = exc

        if attempt < 3:
            sleep(5)

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to fetch {url}")


def clean_text(value: str) -> str:
    return " ".join(unescape(value).split()).strip()


def extract_year(title: str) -> str:
    matches = YEAR_PATTERN.findall(title)
    if not matches:
        return ""
    years = YEAR_PATTERN.findall(title)
    return years[-1] if years else ""


def build_report(discovery: dict[str, object]) -> str:
    expected_count = int(discovery["expected_count"])
    handles = list(discovery["handles"])
    failed_offsets = list(discovery["failed_offsets"])
    matched = expected_count == len(handles) and not failed_offsets
    lines = [
        "# India Code Discovery Report",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        f"Expected handles from portal: {expected_count}",
        f"Discovered unique handles: {len(handles)}",
        f"Count matches portal: {'yes' if matched else 'no'}",
        f"Failed offsets: {len(failed_offsets)}",
    ]
    if failed_offsets:
        lines.append("")
        lines.append("Failed offsets:")
        for failure in failed_offsets:
            lines.append(f"- start={failure['start']}: {failure['error']}")
    lines.append("")
    lines.append("Output JSON: data/collection/india_code_act_handles.json")
    return "\n".join(lines) + "\n"


def build_research_notes(discovery: dict[str, object]) -> str:
    return "\n".join(
        [
            "# India Code Research Findings",
            f"Checked: {datetime.now(UTC).date().isoformat()}",
            "",
            "Portal observations:",
            "- India Code is currently serving DSpace-style HTML pages, not a documented "
            "JSON or XML bulk API.",
            "- The live simple-search index for central acts reports 843 results.",
            "- Search pages support pagination via `start` and `rpp` query parameters.",
            "- Search result rows expose title, act number, enactment date, and a handle link.",
            "- Act detail pages follow `/handle/123456789/<handle>?view_type=browse`.",
            "- Act detail pages expose `Act ID`, `Act Number`, `Act Year`, "
            "`Short Title`, `Long Title`, `Ministry`, `Department`, "
            "`Enactment Date`, and `Last Updated` in metadata rows.",
            "- Section text is loaded separately from "
            "`/SectionPageContent?actid=...&sectionID=...`.",
            "- The page source also references `/sectionlink`, "
            "`/ChapterIndexWiseSection`, and `/ActPreambleServlet` XHR endpoints.",
            "",
            f"Current portal count used for discovery: {int(discovery['expected_count'])}",
            f"Handles discovered in this pass: {len(discovery['handles'])}",
            "",
            "This note is the ground-truth discovery baseline for India Code "
            "central-act handle enumeration.",
            "",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
