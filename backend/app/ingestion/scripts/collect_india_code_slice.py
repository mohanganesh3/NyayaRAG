# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[4]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ingestion.adapters.indiacode import IndiaCodeActAdapter

DEFAULT_HANDLES_PATH = REPO_ROOT / "data" / "collection" / "india_code_act_handles.json"
DEFAULT_STAGING_DIR = REPO_ROOT / "data" / "collection" / "staging"
DEFAULT_RAW_DIR = REPO_ROOT / "data" / "raw" / "india_code"
DEFAULT_AGENT_ID = 1
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
XHR_HEADERS = {
    **REQUEST_HEADERS,
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}
MAX_ATTEMPTS = 3
ACT_DELAY_SECONDS = 2.0
SECTION_DELAY_SECONDS = 1.0
DEFAULT_TIMEOUT_SECONDS = 30
RETRYABLE_STATUS_CODES = {429, 503}

SECTION_MARKER_PATTERNS = (
    (re.compile(r"^\((?P<num>\d+[A-Za-z]?)\)\s*(?P<text>.*)$"), 0, "paragraph"),
    (re.compile(r"^(?P<num>\d+[A-Za-z]?)\.\s*(?P<text>.*)$"), 0, "paragraph"),
    (re.compile(r"^\((?P<num>[a-z])\)\s*(?P<text>.*)$"), 1, "clause"),
    (re.compile(r"^(?P<num>[a-z])\.\s*(?P<text>.*)$"), 1, "clause"),
    (
        re.compile(r"^\((?P<num>[ivxlcdm]+)\)\s*(?P<text>.*)$", re.IGNORECASE),
        2,
        "subclause",
    ),
    (
        re.compile(r"^(?P<num>[ivxlcdm]+)\.\s*(?P<text>.*)$", re.IGNORECASE),
        2,
        "subclause",
    ),
    (re.compile(r"^(?P<label>Provided that\b.*)$", re.IGNORECASE), 0, "proviso"),
    (re.compile(r"^(?P<label>Explanation\s+\d+\b.*)$", re.IGNORECASE), 0, "explanation"),
    (re.compile(r"^(?P<label>Explanation\b.*)$", re.IGNORECASE), 0, "explanation"),
)


@dataclass(slots=True)
class AttemptResult:
    handle: str
    title: str
    status: str
    sections_collected: int
    staging_path: str | None = None
    error: str | None = None


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect a slice of India Code acts.")
    parser.add_argument("--start-index", type=int, required=True)
    parser.add_argument("--end-index", type=int, required=True)
    parser.add_argument("--agent-id", type=int, default=DEFAULT_AGENT_ID)
    parser.add_argument("--handles-path", type=Path, default=DEFAULT_HANDLES_PATH)
    parser.add_argument("--staging-dir", type=Path, default=DEFAULT_STAGING_DIR)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--request-delay-seconds", type=float, default=ACT_DELAY_SECONDS)
    parser.add_argument("--section-delay-seconds", type=float, default=SECTION_DELAY_SECONDS)
    args = parser.parse_args()

    if args.end_index < args.start_index:
        raise SystemExit("--end-index must be greater than or equal to --start-index")

    handles = load_handles(args.handles_path)
    if args.start_index < 0 or args.end_index >= len(handles):
        raise SystemExit(
            "slice "
            f"{args.start_index}:{args.end_index} is outside the handle list "
            f"of size {len(handles)}"
        )

    args.staging_dir.mkdir(parents=True, exist_ok=True)
    args.raw_dir.mkdir(parents=True, exist_ok=True)

    adapter = IndiaCodeActAdapter()
    attempts: list[AttemptResult] = []
    total_sections = 0
    total_bytes = 0

    for index in range(args.start_index, args.end_index + 1):
        item = handles[index]
        try:
            result, bytes_fetched, section_count = collect_act(
                adapter=adapter,
                handle_item=item,
                staging_dir=args.staging_dir,
                raw_dir=args.raw_dir,
                request_delay_seconds=args.request_delay_seconds,
                section_delay_seconds=args.section_delay_seconds,
            )
            total_sections += section_count
            total_bytes += bytes_fetched
            attempts.append(
                AttemptResult(
                    handle=str(item["handle"]),
                    title=str(item["title"]),
                    status=result["collection_status"],
                    sections_collected=section_count,
                    staging_path=str(args.staging_dir / f"act_{item['handle']}.json"),
                    error=result.get("error"),
                )
            )
        except Exception as exc:  # noqa: BLE001
            attempts.append(
                AttemptResult(
                    handle=str(item["handle"]),
                    title=str(item["title"]),
                    status="failed",
                    sections_collected=0,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
        if args.request_delay_seconds > 0:
            sleep(args.request_delay_seconds)

    total_attempted = len(attempts)
    total_succeeded = sum(1 for attempt in attempts if attempt.status == "ingested")
    total_failed = sum(1 for attempt in attempts if attempt.status != "ingested")
    report = {
        "agent_id": args.agent_id,
        "slice_start": args.start_index,
        "slice_end": args.end_index,
        "total_attempted": total_attempted,
        "total_succeeded": total_succeeded,
        "total_failed": total_failed,
        "total_sections_collected": total_sections,
        "bytes_fetched": total_bytes,
        "failed_handles": [
            {
                "handle": attempt.handle,
                "title": attempt.title,
                "error": attempt.error or "unknown_error",
                "status": attempt.status,
            }
            for attempt in attempts
            if attempt.status != "ingested"
        ],
        "items": [
            {
                "handle": attempt.handle,
                "title": attempt.title,
                "status": attempt.status,
                "sections_collected": attempt.sections_collected,
                "staging_path": attempt.staging_path,
                "error": attempt.error,
            }
            for attempt in attempts
        ],
        "generated_at": datetime.now(UTC).isoformat(),
    }

    report_path = args.staging_dir / f"agent_{args.agent_id}_run_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "agent_id": args.agent_id,
                "slice_start": args.start_index,
                "slice_end": args.end_index,
                "attempted": total_attempted,
                "succeeded": total_succeeded,
                "failed": total_failed,
                "sections_collected": total_sections,
                "bytes_fetched": total_bytes,
                "report_path": str(report_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def collect_act(
    *,
    adapter: IndiaCodeActAdapter,
    handle_item: dict[str, object],
    staging_dir: Path,
    raw_dir: Path,
    request_delay_seconds: float,
    section_delay_seconds: float,
) -> tuple[dict[str, object], int, int]:
    handle = str(handle_item["handle"])
    title = str(handle_item["title"])
    detail_url = str(handle_item["detail_url"])

    act_html = fetch_text(detail_url, headers=REQUEST_HEADERS)
    act_bytes = act_html.encode("utf-8")
    act_checksum = sha256_hex(act_bytes)

    act_raw_path = raw_dir / f"act_{handle}.html"
    act_raw_path.write_text(act_html, encoding="utf-8")

    metadata_rows = adapter._extract_metadata_rows(act_html)
    section_refs = adapter._extract_section_refs(act_html)
    act_id = adapter._extract_act_id(
        act_html,
        metadata_rows=metadata_rows,
        section_refs=section_refs,
    )
    if act_id is None:
        raise ValueError(f"Could not extract act_id from {detail_url}")

    sections: list[dict[str, object]] = []
    bytes_fetched = len(act_bytes)
    schedule_titles = adapter._extract_schedule_titles(act_html)

    for section_index, section_ref in enumerate(section_refs):
        query = urlencode(
            {
                "actid": act_id,
                "sectionID": section_ref["section_id"],
            }
        )
        section_url = f"https://www.indiacode.nic.in/SectionPageContent?{query}"
        section_body = fetch_text(section_url, headers=XHR_HEADERS)
        section_bytes = section_body.encode("utf-8")
        bytes_fetched += len(section_bytes)

        section_raw_path = (
            raw_dir
            / "sections"
            / f"act_{handle}_section_{section_ref['section_id']}.json"
        )
        section_raw_path.parent.mkdir(parents=True, exist_ok=True)
        section_raw_path.write_text(section_body, encoding="utf-8")

        section_json = json.loads(section_body)
        content_html = str(section_json.get("content", ""))
        footnote_html = str(section_json.get("footnote", ""))
        clean_text = adapter._clean_fragment(content_html)
        structured_text = build_structured_text(clean_text)

        sections.append(
            {
                "section_id": section_ref["section_id"],
                "section_number": section_ref["section_number"],
                "heading": section_ref["heading"],
                "text": clean_text,
                "structured_text": structured_text,
                "subsections": structured_text["segments"],
                "content_html": content_html,
                "footnote_html": footnote_html,
                "section_content_url": section_url,
                "raw_artifact_path": str(section_raw_path),
                "checksum": sha256_hex(section_bytes),
            }
        )

        if section_delay_seconds > 0 and section_index < len(section_refs) - 1:
            sleep(section_delay_seconds)

    if not sections:
        pdf_url = adapter._extract_pdf_url(act_html)
        if pdf_url is not None:
            pdf_bytes = adapter._http_get_bytes(pdf_url)
            bytes_fetched += len(pdf_bytes)

            pdf_dir = raw_dir / handle
            pdf_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = pdf_dir / "act.pdf"
            pdf_path.write_bytes(pdf_bytes)

            pdf_sections, pdf_schedule_titles = adapter._extract_pdf_sections(
                pdf_bytes,
                pdf_url=pdf_url,
                act_id=act_id,
                raw_dir=pdf_dir,
            )
            for schedule_title in pdf_schedule_titles:
                if schedule_title not in schedule_titles:
                    schedule_titles.append(schedule_title)

            for pdf_section in pdf_sections:
                content_html = str(pdf_section.get("content_html", ""))
                clean_text = adapter._clean_fragment(content_html)
                structured_text = build_structured_text(clean_text)
                section_id = str(pdf_section.get("section_id", "pdf"))
                section_raw_path = pdf_dir / "sections" / f"{section_id}.json"

                sections.append(
                    {
                        "section_id": section_id,
                        "section_number": str(pdf_section.get("section_number", "")),
                        "heading": str(pdf_section.get("heading", "") or ""),
                        "text": clean_text,
                        "structured_text": structured_text,
                        "subsections": structured_text["segments"],
                        "content_html": content_html,
                        "footnote_html": str(pdf_section.get("footnote_html", "")),
                        "section_content_url": str(pdf_section.get("section_content_url", pdf_url)),
                        "raw_artifact_path": str(section_raw_path),
                        "checksum": (
                            sha256_hex(section_raw_path.read_bytes())
                            if section_raw_path.exists()
                            else None
                        ),
                    }
                )

    parsed = {
        "handle": handle,
        "title": title,
        "act_number": metadata_rows.get("Act Number") or str(handle_item.get("act_number", "")),
        "year": _as_int(metadata_rows.get("Act Year") or handle_item.get("year")),
        "ministry": metadata_rows.get("Ministry"),
        "department": metadata_rows.get("Department"),
        "enactment_date": _normalize_date(metadata_rows.get("Enactment Date")),
        "commencement_date": _normalize_date(
            metadata_rows.get("Enforcement Date") or metadata_rows.get("Commencement Date")
        ),
        "is_repealed": _detect_repealed(act_html, metadata_rows),
        "actid": act_id,
        "sections": sections,
        "schedule_titles": schedule_titles,
        "source_url": detail_url,
        "fetch_timestamp": datetime.now(UTC).isoformat(),
        "raw_artifact_path": str(act_raw_path),
        "raw_checksum": act_checksum,
        "source_document_ref": handle,
        "collection_status": "ingested",
    }

    staging_payload = dict(parsed)
    staging_payload["checksum"] = sha256_hex(
        json.dumps(staging_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    )

    staging_path = staging_dir / f"act_{handle}.json"
    staging_path.write_text(
        json.dumps(staging_payload, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    return staging_payload, bytes_fetched, len(sections)


def fetch_text(url: str, *, headers: dict[str, str]) -> str:
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
                return response.read().decode("utf-8", errors="ignore")
        except HTTPError as exc:
            last_error = exc
            if exc.code not in RETRYABLE_STATUS_CODES or attempt >= MAX_ATTEMPTS:
                raise
        except (TimeoutError, URLError) as exc:
            last_error = exc

        if attempt < MAX_ATTEMPTS:
            sleep(5)

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to fetch {url}")


def build_structured_text(text: str) -> dict[str, object]:
    segments: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        marker = classify_line(line)
        if marker is None:
            if current is None:
                current = {
                    "level": 0,
                    "kind": "text",
                    "label": None,
                    "text": line,
                }
                segments.append(current)
            else:
                current["text"] = f"{current['text']}\n{line}"
            continue

        label, remainder, level, kind = marker
        current = {
            "level": level,
            "kind": kind,
            "label": label,
            "text": remainder,
        }
        segments.append(current)

    return {"segments": segments}


def classify_line(line: str) -> tuple[str | None, str, int, str] | None:
    for pattern, level, kind in SECTION_MARKER_PATTERNS:
        match = pattern.match(line)
        if match is None:
            continue
        if "num" in match.groupdict():
            label = match.group("num")
            remainder = match.group("text").strip()
            return label, remainder, level, kind
        label = match.group("label").strip()
        remainder = line[len(label):].strip()
        return label, remainder, level, kind
    return None


def load_handles(path: Path) -> list[dict[str, object]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array")
    handles: list[dict[str, object]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if "handle" not in item or "title" not in item or "detail_url" not in item:
            continue
        handles.append(item)
    return handles


def _normalize_date(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    if re.fullmatch(r"\d{2}-\d{2}-\d{4}", text):
        day, month, year = text.split("-")
        return f"{year}-{month}-{day}"
    return text


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"\d{4}", text)
    if match is not None and len(text) > 4:
        try:
            return int(match.group(0))
        except ValueError:
            return None
    try:
        return int(text)
    except ValueError:
        return None


def _detect_repealed(act_html: str, metadata_rows: dict[str, str]) -> bool:
    for key in ("Repealed", "Replaced By", "Repeal Status"):
        value = metadata_rows.get(key)
        if value and value.strip():
            return True
    text = act_html.lower()
    return "repealed act" in text or 'class="repealed"' in text


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
