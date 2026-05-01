from __future__ import annotations

import json
import re
from pathlib import Path

import fitz

ACT_HANDLE = "2435"
REPO_ROOT = Path(__file__).resolve().parents[4]
STAGING_PATH = REPO_ROOT / "data" / "collection" / "staging" / f"act_{ACT_HANDLE}.json"
PDF_PATH = REPO_ROOT / "data" / "raw" / "india_code" / ACT_HANDLE / "act.pdf"

ARRANGEMENT_END_PAGE = 29
BODY_START_PAGE = 30

SECTION_INVENTORY_PATTERN = re.compile(
    r"(?m)^\s*((?:\d+[A-Z]*(?:-[A-Z]+)?))\.\s+(.*?)(?:\s+\.\.\.|\s+\d+\s*$|$)"
)
NON_ALNUM_PATTERN = re.compile(r"[^a-z0-9]+")
BRACKETED_PATTERN = re.compile(r"\[[^\]]*\]")


def main() -> int:
    if not STAGING_PATH.exists():
        raise FileNotFoundError(f"Missing staging file: {STAGING_PATH}")
    if not PDF_PATH.exists():
        raise FileNotFoundError(f"Missing India Code PDF: {PDF_PATH}")

    record = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    pdf = fitz.open(PDF_PATH)

    arrangement_inventory = build_arrangement_inventory(pdf)
    schedule_start_page = find_schedule_start_page(pdf)
    section_starts = find_section_starts(
        pdf=pdf,
        inventory=arrangement_inventory,
        schedule_start_page=schedule_start_page,
    )
    sections = build_sections_from_starts(
        pdf=pdf,
        starts=section_starts,
        schedule_start_page=schedule_start_page,
    )

    if len(sections) < 298:
        raise RuntimeError(
            f"Repair produced only {len(sections)} sections for the Income-tax Act."
        )

    record["sections"] = sections
    STAGING_PATH.write_text(json.dumps(record, indent=2, ensure_ascii=True), encoding="utf-8")

    print(
        json.dumps(
            {
                "handle": ACT_HANDLE,
                "title": record.get("title"),
                "inventory_entries": len(arrangement_inventory),
                "schedule_start_page": schedule_start_page,
                "section_starts": len(section_starts),
                "sections_written": len(sections),
                "staging_path": str(STAGING_PATH),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def build_arrangement_inventory(pdf: fitz.Document) -> list[tuple[str, str]]:
    text = "\n".join(
        pdf.load_page(page_number).get_text("text")
        for page_number in range(ARRANGEMENT_END_PAGE)
    )
    inventory: list[tuple[str, str]] = []
    seen: set[str] = set()

    for match in SECTION_INVENTORY_PATTERN.finditer(text):
        number = match.group(1).strip()
        heading = " ".join(match.group(2).split())
        if number in seen:
            continue
        inventory.append((number, clean_heading(heading)))
        seen.add(number)

    return inventory


def find_schedule_start_page(pdf: fitz.Document) -> int:
    for page_index in range(BODY_START_PAGE - 1, pdf.page_count):
        page_text = pdf.load_page(page_index).get_text("text")
        if "THE FIRST SCHEDULE" in page_text:
            return page_index + 1
    return pdf.page_count + 1


def find_section_starts(
    *,
    pdf: fitz.Document,
    inventory: list[tuple[str, str]],
    schedule_start_page: int,
) -> list[dict[str, object]]:
    starts: list[dict[str, object]] = []
    seen_numbers: set[str] = set()

    for page_number in range(BODY_START_PAGE, schedule_start_page):
        lines = page_lines(pdf.load_page(page_number - 1), page_number)
        for line_index, line in enumerate(lines):
            for number, heading in inventory:
                if number in seen_numbers:
                    continue
                prefix = f"{number}. "
                if not line.startswith(prefix):
                    continue
                remainder = line[len(prefix) :].strip()
                if not heading_matches(heading, remainder):
                    continue
                starts.append(
                    {
                        "page_number": page_number,
                        "line_index": line_index,
                        "section_number": number,
                        "heading": heading,
                    }
                )
                seen_numbers.add(number)
                break

    return starts


def build_sections_from_starts(
    *,
    pdf: fitz.Document,
    starts: list[dict[str, object]],
    schedule_start_page: int,
) -> list[dict[str, object]]:
    page_line_cache = {
        page_number: page_lines(pdf.load_page(page_number - 1), page_number)
        for page_number in range(BODY_START_PAGE, schedule_start_page)
    }
    sections: list[dict[str, object]] = []

    for index, current in enumerate(starts):
        next_start = starts[index + 1] if index + 1 < len(starts) else None
        current_page = int(current["page_number"])
        current_line = int(current["line_index"])
        current_number = str(current["section_number"])
        current_heading = str(current["heading"])

        collected_lines: list[str] = []
        for page_number in range(current_page, schedule_start_page):
            lines = page_line_cache[page_number]
            start_line = current_line if page_number == current_page else 0
            end_line = (
                int(next_start["line_index"])
                if next_start is not None and page_number == int(next_start["page_number"])
                else len(lines)
            )
            collected_lines.extend(lines[start_line:end_line])
            if next_start is not None and page_number == int(next_start["page_number"]):
                break

        if not collected_lines:
            continue

        first_line = collected_lines[0]
        prefix = f"{current_number}. "
        if first_line.startswith(prefix):
            first_line = first_line[len(prefix) :].strip()

        heading_line, first_body = split_heading_and_body(first_line, current_heading)
        heading = clean_heading(heading_line or current_heading)

        body_lines = [first_body] if first_body else []
        body_lines.extend(collected_lines[1:])
        text = "\n".join(line for line in body_lines if line).strip()
        if not text:
            text = heading

        sections.append(
            {
                "section_number": current_number,
                "heading": heading,
                "text": text,
                "original_text": text,
                "is_in_force": "[Omitted" not in heading and "Omitted by" not in text[:200],
                "subsections": [],
                "clauses": [],
                "subclauses": [],
                "provisos": [],
                "explanations": [],
                "amendments": [],
            }
        )

    return sections


def page_lines(page: fitz.Page, page_number: int) -> list[str]:
    lines: list[str] = []
    for raw_line in page.get_text("text").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == str(page_number):
            continue
        lines.append(line)
    return lines


def clean_heading(heading: str) -> str:
    heading = " ".join(heading.split())
    return heading.rstrip(". ").strip()


def normalize_for_match(text: str) -> str:
    text = BRACKETED_PATTERN.sub(" ", text.lower())
    text = NON_ALNUM_PATTERN.sub(" ", text)
    return " ".join(text.split())


def heading_matches(expected_heading: str, line_remainder: str) -> bool:
    expected = normalize_for_match(expected_heading)
    actual = normalize_for_match(line_remainder)
    if not expected or not actual:
        return False
    return (
        actual.startswith(expected[:32])
        or actual.startswith(expected[:24])
        or expected.startswith(actual[:24])
    )


def split_heading_and_body(line_remainder: str, fallback_heading: str) -> tuple[str, str]:
    for delimiter in ("—", ".—", " - ", "— "):
        if delimiter in line_remainder:
            left, right = line_remainder.split(delimiter, 1)
            heading = clean_heading(left)
            body = right.strip()
            if heading:
                return heading, body
    return clean_heading(fallback_heading), line_remainder.strip()


if __name__ == "__main__":
    raise SystemExit(main())
