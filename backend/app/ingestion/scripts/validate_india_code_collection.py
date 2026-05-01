from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_DATABASE = Path("data/collection/live_corpus.db")
DEFAULT_HANDLES = Path("data/collection/india_code_act_handles.json")
DEFAULT_OUTPUT = Path("data/collection/india_code_validation_report.json")

KEY_ACTS: list[dict[str, Any]] = [
    {
        "name": "Companies Act 2013",
        "patterns": ["Companies Act"],
        "expected_min_sections": 470,
        "note": "Sections only; schedules/forms are not normalized in the current schema.",
    },
    {
        "name": "Income Tax Act 1961",
        "patterns": ["Income Tax Act", "Income-tax Act"],
        "expected_min_sections": 298,
        "note": "Sections only; schedules/forms are not normalized in the current schema.",
    },
    {
        "name": "Indian Penal Code 1860",
        "patterns": ["Indian Penal Code", "IPC"],
        "expected_min_sections": 511,
        "note": "Legacy-code section count validation only.",
    },
    {
        "name": "Code of Civil Procedure 1908",
        "patterns": ["Code of Civil Procedure", "CPC"],
        "expected_min_sections": 158,
        "note": "Orders are not represented in the current schema.",
    },
    {
        "name": "Code of Criminal Procedure 1973",
        "patterns": ["Code of Criminal Procedure", "CrPC"],
        "expected_min_sections": 484,
        "note": "Legacy-code section count validation only.",
    },
    {
        "name": "Bharatiya Nyaya Sanhita 2023",
        "patterns": ["Bharatiya Nyaya Sanhita", "BNS"],
        "expected_min_sections": 358,
        "note": "New-code section count validation only.",
    },
    {
        "name": "Bharatiya Nagarik Suraksha Sanhita 2023",
        "patterns": ["Bharatiya Nagarik Suraksha Sanhita", "BNSS"],
        "expected_min_sections": 531,
        "note": "New-code section count validation only.",
    },
    {
        "name": "Bharatiya Sakshya Adhiniyam 2023",
        "patterns": ["Bharatiya Sakshya Adhiniyam", "BSA"],
        "expected_min_sections": 167,
        "note": "New-code section count validation only.",
    },
    {
        "name": "Constitution of India",
        "patterns": ["Constitution of India"],
        "expected_min_sections": 395,
        "note": "Article-level modeling is not normalized in the current schema.",
    },
    {
        "name": "Insolvency and Bankruptcy Code 2016",
        "patterns": ["Insolvency and Bankruptcy Code", "IBC"],
        "expected_min_sections": 255,
        "note": "Section count is validated only where the act is present in the corpus.",
    },
    {
        "name": "SEBI Act 1992",
        "patterns": ["SEBI Act", "Securities and Exchange Board of India Act"],
        "expected_min_sections": 33,
        "note": "Regulatory instrument coverage is not normalized in the current schema.",
    },
    {
        "name": "Transfer of Property Act 1882",
        "patterns": ["Transfer of Property Act"],
        "expected_min_sections": 137,
        "note": "Section count validation only.",
    },
]

def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the India Code slice in live_corpus.db.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--handles", type=Path, default=DEFAULT_HANDLES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    report = build_report(args.database, args.handles)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def build_report(database_path: Path, handles_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = _tables(conn)
        columns = {table: _columns(conn, table) for table in tables}

        handles = _load_handles(handles_path)
        handle_map = {str(item["handle"]): item for item in handles}
        handle_titles = [str(item.get("title", "")) for item in handles]

        acts = _india_code_acts(conn)
        section_counts = _india_code_section_counts(conn)
        act_lookup = {row["source_document_ref"]: row for row in acts if row["source_document_ref"]}
        db_handles = set(act_lookup)

        missing_handles = [
            {
                "handle": handle,
                "title": item.get("title"),
                "year": item.get("year"),
            }
            for handle, item in handle_map.items()
            if handle not in db_handles
        ]

        zero_section_acts = [
            {
                "act_id": row["act_id"],
                "act_name": row["act_name"],
                "handle": row["handle"],
            }
            for row in section_counts
            if row["section_count"] == 0
        ]

        low_section_acts = [
            {
                "act_id": row["act_id"],
                "act_name": row["act_name"],
                "handle": row["handle"],
                "section_count": row["section_count"],
            }
            for row in section_counts
            if 0 < row["section_count"] < 3
        ]

        duplicate_source_refs = _duplicate_rows(
            conn,
            """
            SELECT source_document_ref AS duplicate_key, COUNT(*) AS cnt
            FROM legal_documents
            WHERE source_system = 'india_code'
            GROUP BY source_document_ref
            HAVING COUNT(*) > 1
            ORDER BY cnt DESC, duplicate_key
            """,
        )
        duplicate_act_names = _duplicate_rows(
            conn,
            """
            SELECT sd.act_name AS duplicate_key, COUNT(*) AS cnt
            FROM statute_documents sd
            JOIN legal_documents ld ON ld.doc_id = sd.doc_id
            WHERE ld.source_system = 'india_code'
            GROUP BY sd.act_name
            HAVING COUNT(*) > 1
            ORDER BY cnt DESC, duplicate_key
            """,
        )

        null_metadata = {
            "legal_documents": {
                "act_name": 0,
                "source_url": _count(
                    conn,
                    """
                    SELECT COUNT(*)
                    FROM legal_documents
                    WHERE source_system = 'india_code'
                      AND (source_url IS NULL OR trim(source_url) = '')
                    """,
                ),
                "checksum": _count(
                    conn,
                    """
                    SELECT COUNT(*)
                    FROM legal_documents
                    WHERE source_system = 'india_code'
                      AND (checksum IS NULL OR trim(checksum) = '')
                    """,
                ),
                "source_document_ref": _count(
                    conn,
                    """
                    SELECT COUNT(*)
                    FROM legal_documents
                    WHERE source_system = 'india_code'
                      AND (source_document_ref IS NULL OR trim(source_document_ref) = '')
                    """,
                ),
            },
            "statute_documents": {
                "act_name": _count(
                    conn,
                    """
                    SELECT COUNT(*)
                    FROM statute_documents sd
                    JOIN legal_documents ld ON ld.doc_id = sd.doc_id
                    WHERE ld.source_system = 'india_code'
                      AND (sd.act_name IS NULL OR trim(sd.act_name) = '')
                    """,
                ),
                "short_title": _count(
                    conn,
                    """
                    SELECT COUNT(*)
                    FROM statute_documents sd
                    JOIN legal_documents ld ON ld.doc_id = sd.doc_id
                    WHERE ld.source_system = 'india_code'
                      AND (sd.short_title IS NULL OR trim(sd.short_title) = '')
                    """,
                ),
                "enforcement_date": _count(
                    conn,
                    """
                    SELECT COUNT(*)
                    FROM statute_documents sd
                    JOIN legal_documents ld ON ld.doc_id = sd.doc_id
                    WHERE ld.source_system = 'india_code'
                      AND sd.enforcement_date IS NULL
                    """,
                ),
            },
            "requested_but_unavailable": {
                "act_number": None,
                "year": None,
                "reason": (
                    "schema does not store act_number/year on statute_documents; "
                    "derive from act_name or source metadata if needed"
                ),
            },
        }

        key_act_section_counts = []
        for key_act in KEY_ACTS:
            matches = _find_key_act_matches(conn, key_act["patterns"])
            best = max(matches, key=lambda item: item["section_count"], default=None)
            actual = best["section_count"] if best else 0
            discovered_in_handle_index = any(
                pattern.lower() in title.lower()
                for pattern in key_act["patterns"]
                for title in handle_titles
            )
            if not matches and not discovered_in_handle_index:
                status = "NOT_IN_DISCOVERED_HANDLE_SET"
            else:
                status = _gap_status(actual, key_act["expected_min_sections"])
            key_act_section_counts.append(
                {
                    "act_name": key_act["name"],
                    "patterns": key_act["patterns"],
                    "sections_in_db": actual,
                    "sections_expected_min": key_act["expected_min_sections"],
                    "gap_percentage": _gap_percentage(actual, key_act["expected_min_sections"]),
                    "status": status,
                    "discovered_in_handle_index": discovered_in_handle_index,
                    "note": key_act["note"],
                    "matches": matches,
                }
            )

        amendment_history_rows = _count(
            conn,
            """
            SELECT COUNT(*)
            FROM statute_amendments
            """,
        )

        schedule_table_present = "schedules" in tables
        form_table_present = "forms" in tables

        total_expected_handles = len(handles)
        total_acts = len(acts)
        total_sections = _count(
            conn,
            """
            SELECT COUNT(*)
            FROM statute_sections ss
            JOIN statute_documents sd ON sd.doc_id = ss.statute_doc_id
            JOIN legal_documents ld ON ld.doc_id = sd.doc_id
            WHERE ld.source_system = 'india_code'
            """,
        )

        overall_completeness_percentage = (
            round((total_acts / total_expected_handles) * 100, 2)
            if total_expected_handles
            else 0.0
        )

        verdict = _verdict(
            missing_handles=missing_handles,
            key_act_section_counts=key_act_section_counts,
            null_metadata=null_metadata,
            amendment_history_rows=amendment_history_rows,
        )

        return {
            "database_path": str(database_path),
            "handles_path": str(handles_path),
            "report_date": _iso_now(),
            "expected_total_handles": total_expected_handles,
            "schema": {
                "tables_present": sorted(tables),
                "mismatches": _schema_mismatches(tables, columns),
            },
            "counts": {
                "acts_in_database": total_acts,
                "sections_in_database": total_sections,
                "acts_with_zero_sections": len(zero_section_acts),
                "acts_with_suspiciously_low_sections": len(low_section_acts),
                "duplicate_source_document_refs": len(duplicate_source_refs),
                "duplicate_act_names": len(duplicate_act_names),
            },
            "missing_acts": missing_handles,
            "acts_with_zero_sections": zero_section_acts,
            "acts_with_suspiciously_low_sections": low_section_acts,
            "duplicate_acts": {
                "by_source_document_ref": duplicate_source_refs,
                "by_act_name": duplicate_act_names,
            },
            "null_metadata": null_metadata,
            "amendment_history": {
                "rows_present": amendment_history_rows,
                "table_present": "statute_amendments" in tables,
            },
            "schedule_and_form_support": {
            "schedule_table_present": schedule_table_present,
            "form_table_present": form_table_present,
                "note": (
                    "Current schema does not normalize schedules/forms; "
                    "India Code schedules are not separately queryable today."
                ),
            },
            "key_act_section_counts": key_act_section_counts,
            "overall_completeness_percentage": overall_completeness_percentage,
            "verdict": verdict,
        }
    finally:
        conn.close()


def _tables(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in cur.fetchall()}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _load_handles(handles_path: Path) -> list[dict[str, Any]]:
    if not handles_path.exists():
        return []
    raw = json.loads(handles_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _india_code_acts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cur = conn.execute(
        """
        SELECT
            sd.doc_id AS act_id,
            sd.act_name,
            sd.short_title,
            ld.source_document_ref,
            COUNT(ss.id) AS section_count
        FROM statute_documents sd
        JOIN legal_documents ld ON ld.doc_id = sd.doc_id
        LEFT JOIN statute_sections ss ON ss.statute_doc_id = sd.doc_id
        WHERE ld.source_system = 'india_code'
        GROUP BY sd.doc_id, sd.act_name, sd.short_title, ld.source_document_ref
        ORDER BY ld.source_document_ref
        """
    )
    return cur.fetchall()


def _india_code_section_counts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        {
            "act_id": row["act_id"],
            "act_name": row["act_name"],
            "handle": row["source_document_ref"],
            "section_count": int(row["section_count"]),
        }
        for row in _india_code_acts(conn)
    ]


def _find_key_act_matches(conn: sqlite3.Connection, patterns: list[str]) -> list[dict[str, Any]]:
    matches_by_id: dict[str, dict[str, Any]] = {}
    for pattern in patterns:
        cur = conn.execute(
            """
            SELECT
                sd.doc_id AS act_id,
                sd.act_name,
                ld.source_document_ref,
                COUNT(ss.id) AS section_count
            FROM statute_documents sd
            JOIN legal_documents ld ON ld.doc_id = sd.doc_id
            LEFT JOIN statute_sections ss ON ss.statute_doc_id = sd.doc_id
            WHERE ld.source_system = 'india_code'
              AND sd.act_name LIKE ?
            GROUP BY sd.doc_id, sd.act_name, ld.source_document_ref
            ORDER BY COUNT(ss.id) DESC, sd.act_name
            """,
            (f"%{pattern}%",),
        )
        for row in cur.fetchall():
            match = {
                "act_id": row["act_id"],
                "act_name": row["act_name"],
                "handle": row["source_document_ref"],
                "section_count": int(row["section_count"]),
                "pattern": pattern,
            }
            matches_by_id.setdefault(match["act_id"], match)
    return list(matches_by_id.values())


def _duplicate_rows(conn: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    cur = conn.execute(query)
    return [
        {"duplicate_key": row[0], "count": int(row[1])}
        for row in cur.fetchall()
        if row[0] is not None
    ]


def _count(conn: sqlite3.Connection, query: str) -> int:
    cur = conn.execute(query)
    row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _schema_mismatches(tables: set[str], columns: dict[str, set[str]]) -> list[str]:
    mismatches: list[str] = []
    if "sections" not in tables:
        mismatches.append(
            "Requested validation queries mention a sections table, "
            "but the live schema uses statute_sections."
        )
    if "amendment_events" not in tables:
        mismatches.append(
            "Requested validation queries mention amendment_events, "
            "but the live schema uses statute_amendments."
        )
    if "schedules" not in tables:
        mismatches.append(
            "Requested schedule/form checks cannot run directly because "
            "schedules/forms are not normalized tables."
        )
    if "statute_documents" in tables:
        if "source" not in columns.get("statute_documents", set()):
            mismatches.append(
                "Requested source-scoped statute queries need "
                "legal_documents.source_system; statute_documents has "
                "no source column."
            )
        if "act_number" not in columns.get("statute_documents", set()):
            mismatches.append(
                "Requested duplicate checks by act_number/year cannot run "
                "directly because statute_documents has no act_number column."
            )
        if "year" not in columns.get("statute_documents", set()):
            mismatches.append(
                "Requested duplicate checks by act_number/year cannot run "
                "directly because statute_documents has no year column."
            )
        if "act_id" not in columns.get("statute_documents", set()):
            mismatches.append(
                "Requested section joins using act_id must instead use "
                "statute_documents.doc_id and statute_sections.statute_doc_id."
            )
    return mismatches


def _gap_status(actual: int, expected_min: int) -> str:
    if expected_min <= 0:
        return "UNKNOWN"
    ratio = actual / expected_min
    if ratio < 0.8:
        return "SECTION_GAP_CRITICAL"
    if ratio < 0.95:
        return "SECTION_GAP_MINOR"
    return "OK"


def _gap_percentage(actual: int, expected_min: int) -> float:
    if expected_min <= 0:
        return 0.0
    return round((1 - min(actual, expected_min) / expected_min) * 100, 2)


def _verdict(
    *,
    missing_handles: list[dict[str, Any]],
    key_act_section_counts: list[dict[str, Any]],
    null_metadata: dict[str, Any],
    amendment_history_rows: int,
) -> str:
    critical_gaps = [
        row for row in key_act_section_counts if row["status"] == "SECTION_GAP_CRITICAL"
    ]
    null_source_url = int(null_metadata["legal_documents"]["source_url"])
    null_checksum = int(null_metadata["legal_documents"]["checksum"])
    if (
        not missing_handles
        and not critical_gaps
        and null_source_url == 0
        and null_checksum == 0
        and amendment_history_rows > 0
    ):
        return "COMPLETE"
    return (
        f"INCOMPLETE - {len(missing_handles)} missing acts, "
        f"{len(critical_gaps)} critical key-act gaps, "
        f"{null_source_url} null source_url rows, "
        f"{null_checksum} null checksum rows, "
        f"{amendment_history_rows} amendment rows"
    )


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
