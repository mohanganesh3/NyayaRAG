from __future__ import annotations

import re
import sqlite3
from datetime import date
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

DB_PATH = Path("data/collection/live_corpus.db")

AMENDMENT_EVENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "SUBSTITUTED",
        re.compile(
            r"(?i)(?:subs\.|substituted)\s+by\s+(?:the\s+)?(?P<act_ref>"
            r"(?:[^\n.;]{0,140}?Act[^\n.;]{0,100}?)"
            r"(?:\(\s*Act?\s*\d+\s*of\s*\d{4}\s*\)|\(\s*\d+\s*of\s*\d{4}\s*\)|Act\s*\d+\s*of\s*\d{4})"
            r")"
        ),
    ),
    (
        "INSERTED",
        re.compile(
            r"(?i)(?:ins\.|inserted|added|explanation\s+added)\s+by\s+(?:the\s+)?(?P<act_ref>"
            r"(?:[^\n.;]{0,140}?Act[^\n.;]{0,100}?)"
            r"(?:\(\s*Act?\s*\d+\s*of\s*\d{4}\s*\)|\(\s*\d+\s*of\s*\d{4}\s*\)|Act\s*\d+\s*of\s*\d{4})"
            r")"
        ),
    ),
    (
        "OMITTED",
        re.compile(
            r"(?i)(?:omitted|rep\.|repealed)\s+by\s+(?:the\s+)?(?P<act_ref>"
            r"(?:[^\n.;]{0,140}?Act[^\n.;]{0,100}?)"
            r"(?:\(\s*Act?\s*\d+\s*of\s*\d{4}\s*\)|\(\s*\d+\s*of\s*\d{4}\s*\)|Act\s*\d+\s*of\s*\d{4})"
            r")"
        ),
    ),
    (
        "AMENDED",
        re.compile(
            r"(?i)amended\s+by\s+(?:the\s+)?(?P<act_ref>"
            r"(?:[^\n.;]{0,140}?Act[^\n.;]{0,100}?)"
            r"(?:\(\s*Act?\s*\d+\s*of\s*\d{4}\s*\)|\(\s*\d+\s*of\s*\d{4}\s*\)|Act\s*\d+\s*of\s*\d{4})"
            r")"
        ),
    ),
]
ACT_NUMBER_YEAR_PATTERN = re.compile(r"(?i)(?:Act\s*)?(\d+)\s*of\s*(\d{4})")
EFFECTIVE_DATE_PATTERN = re.compile(
    r"(?i)w\.?\s*e\.?\s*f\.?\s*\.?\s*\(?\s*(\d{1,2}[-./]\d{1,2}[-./]\d{4})\s*\)?"
)
WHITESPACE_PATTERN = re.compile(r"\s+")


def main() -> int:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Missing database: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, statute_doc_id, section_number, text FROM statute_sections WHERE text IS NOT NULL")
        rows = cur.fetchall()

        inserted = 0
        scanned = 0
        for section_id, statute_doc_id, section_number, text in rows:
            scanned += 1
            for amendment_row in extract_rows_for_section(
                section_id=section_id,
                statute_doc_id=statute_doc_id,
                section_number=section_number,
                text=text,
            ):
                cur.execute(
                    """
                    INSERT OR IGNORE INTO statute_amendments
                    (id, section_id, amendment_label, amendment_date, effective_date, summary, previous_text, updated_text)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        amendment_row["id"],
                        amendment_row["section_id"],
                        amendment_row["amendment_label"],
                        amendment_row["amendment_date"],
                        amendment_row["effective_date"],
                        amendment_row["summary"],
                        None,
                        None,
                    ),
                )
                inserted += cur.rowcount

        conn.commit()

        cur.execute("SELECT COUNT(*) FROM statute_amendments")
        total_rows = cur.fetchone()[0]
        cur.execute(
            """
            SELECT
              SUM(CASE WHEN amendment_label LIKE 'SUBSTITUTED%' THEN 1 ELSE 0 END),
              SUM(CASE WHEN amendment_label LIKE 'INSERTED%' THEN 1 ELSE 0 END),
              SUM(CASE WHEN amendment_label LIKE 'OMITTED%' THEN 1 ELSE 0 END),
              SUM(CASE WHEN amendment_label LIKE 'AMENDED%' THEN 1 ELSE 0 END)
            FROM statute_amendments
            """
        )
        substituted, inserted_rows, omitted, amended = cur.fetchone()

        print(
            {
                "sections_scanned": scanned,
                "rows_inserted_this_run": inserted,
                "total_amendment_rows": total_rows,
                "by_type": {
                    "SUBSTITUTED": substituted or 0,
                    "INSERTED": inserted_rows or 0,
                    "OMITTED": omitted or 0,
                    "AMENDED": amended or 0,
                },
            }
        )
    finally:
        conn.close()

    return 0


def extract_rows_for_section(
    *,
    section_id: str,
    statute_doc_id: str,
    section_number: str,
    text: str,
) -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    seen_keys: set[str] = set()
    compact_text = collapse_whitespace(text)

    for event_type, pattern in AMENDMENT_EVENT_PATTERNS:
        for match in pattern.finditer(compact_text):
            act_ref = collapse_whitespace(match.group("act_ref"))
            act_match = ACT_NUMBER_YEAR_PATTERN.search(act_ref)
            if act_match is None:
                continue

            act_number = act_match.group(1)
            act_year = act_match.group(2)
            snippet_window = compact_text[match.start() : min(len(compact_text), match.end() + 220)]
            snippet = collapse_whitespace(snippet_window)
            effective_date = extract_effective_date(snippet)

            amendment_label = f"{event_type} | Act {act_number} of {act_year}"
            if effective_date is not None:
                amendment_label += f" | {effective_date.isoformat()}"

            row_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"{section_id}|{event_type}|{act_number}|{act_year}|{effective_date}|{snippet}",
                )
            )

            dedupe_key = f"{section_id}|{event_type}|{act_number}|{act_year}|{effective_date}|{snippet}"
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)

            rows.append(
                {
                    "id": row_id,
                    "section_id": section_id,
                    "statute_doc_id": statute_doc_id,
                    "section_number": section_number,
                    "amendment_label": amendment_label,
                    "amendment_date": None,
                    "effective_date": effective_date.isoformat() if effective_date else None,
                    "summary": snippet[:2000],
                }
            )

    return rows


def collapse_whitespace(text: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", text).strip()


def extract_effective_date(snippet: str) -> date | None:
    match = EFFECTIVE_DATE_PATTERN.search(snippet)
    if match is None:
        return None
    candidate = match.group(1).replace(".", "-").replace("/", "-")
    day_text, month_text, year_text = candidate.split("-")
    try:
        return date(int(year_text), int(month_text), int(day_text))
    except ValueError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
