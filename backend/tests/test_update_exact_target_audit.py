from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from app.ingestion.scripts.update_exact_target_audit import main


def _create_case_law_staging_db(db_path: Path, *, docs: int) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE legal_documents (
                doc_id TEXT PRIMARY KEY,
                source_system TEXT,
                source_url TEXT,
                source_document_ref TEXT,
                checksum TEXT,
                parser_version TEXT,
                ingestion_run_id TEXT,
                collector_run_id TEXT,
                doc_type TEXT,
                date TEXT,
                date_text TEXT,
                court TEXT,
                title TEXT,
                citation TEXT,
                parties TEXT,
                bench TEXT,
                seed_url TEXT,
                detail_url TEXT,
                artifact_url TEXT,
                source_surface TEXT,
                provenance_tier TEXT
            )
            """.strip()
        )

        for i in range(docs):
            cur.execute(
                """
                INSERT INTO legal_documents (
                    doc_id, source_system, source_url, source_document_ref, checksum,
                    parser_version, ingestion_run_id, collector_run_id, doc_type, date, date_text,
                    court, title, citation, parties, bench, seed_url, detail_url,
                    artifact_url, source_surface, provenance_tier
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """.strip(),
                (
                    f"doc-{i}",
                    "cbic",
                    f"https://example.test/doc/{i}",
                    f"ref-{i}",
                    f"checksum-{i}",
                    "parser-v1",
                    "ingestion-run-1",
                    "run-1",
                    "judgment",
                    "2025-01-01",
                    "2025-01-01",
                    "Test Court",
                    f"Document {i}",
                    f"citation-{i}",
                    f'["Party {i} A", "Party {i} B"]',
                    f'["Bench {i}"]',
                    "https://example.test/listing",
                    f"https://example.test/detail/{i}",
                    f"https://example.test/doc/{i}",
                    "official_listing",
                    "official",
                ),
            )

        conn.commit()
    finally:
        conn.close()


def _create_minimal_staging_db(db_path: Path, *, docs: int) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE legal_documents (
                doc_id TEXT PRIMARY KEY,
                source_system TEXT
            )
            """.strip()
        )
        for i in range(docs):
            cur.execute(
                "INSERT INTO legal_documents (doc_id, source_system) VALUES (?, ?)",
                (f"doc-{i}", "minimal"),
            )
        conn.commit()
    finally:
        conn.close()


def _append_case_law_docs(db_path: Path, *, start: int, count: int) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        for i in range(start, start + count):
            cur.execute(
                """
                INSERT INTO legal_documents (
                    doc_id, source_system, source_url, source_document_ref, checksum,
                    parser_version, ingestion_run_id, collector_run_id, doc_type, date, date_text,
                    court, title, citation, parties, bench, seed_url, detail_url,
                    artifact_url, source_surface, provenance_tier
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """.strip(),
                (
                    f"doc-{i}",
                    "cbic",
                    f"https://example.test/doc/{i}",
                    f"ref-{i}",
                    f"checksum-{i}",
                    "parser-v1",
                    "ingestion-run-2",
                    "run-2",
                    "judgment",
                    "2025-01-01",
                    "2025-01-01",
                    "Test Court",
                    f"Document {i}",
                    f"citation-{i}",
                    f'["Party {i} A", "Party {i} B"]',
                    f'["Bench {i}"]',
                    "https://example.test/listing",
                    f"https://example.test/detail/{i}",
                    f"https://example.test/doc/{i}",
                    "official_listing",
                    "official",
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _write_targets(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def test_update_exact_target_audit_generates_all_outputs_and_health_states(tmp_path: Path) -> None:
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)

    db1 = staging_dir / "a.db"
    db2 = staging_dir / "b.db"
    _create_case_law_staging_db(db1, docs=10)
    _create_case_law_staging_db(db2, docs=8)

    targets_path = tmp_path / "exact_targets.json"
    _write_targets(
        targets_path,
        {
            "sources": {
                "cbic": {"display": "CBIC", "db": "a.db", "need": 20},
                "ca_debates": {"display": "CA Debates", "db": "b.db", "need": 10}
            }
        },
    )

    court_grade_targets = tmp_path / "court_grade_targets.json"
    _write_targets(
        court_grade_targets,
        {
            "families": {
                "regulators": {
                    "display": "Regulators",
                    "depends_on_exact": ["cbic"],
                    "depends_on_families": [],
                    "critical": True,
                    "layer": "regulation"
                },
                "history": {
                    "display": "History",
                    "depends_on_exact": ["ca_debates"],
                    "depends_on_families": [],
                    "critical": True,
                    "layer": "parliamentary_history"
                }
            }
        },
    )

    output_path = tmp_path / "EXACT_TARGET_AUDIT.md"
    rc = main(
        [
            "--staging-dir",
            str(staging_dir),
            "--output",
            str(output_path),
            "--targets",
            str(targets_path),
            "--court-grade-targets",
            str(court_grade_targets),
            "--sqlite-timeout-seconds",
            "0.1",
            "--busy-timeout-ms",
            "100",
        ]
    )

    assert rc == 0
    exact_text = output_path.read_text(encoding="utf-8")
    metadata_path = tmp_path / "METADATA_QUALITY_AUDIT.md"
    court_grade_path = tmp_path / "COURT_GRADE_COMPLETENESS_AUDIT.md"
    assert metadata_path.exists()
    assert court_grade_path.exists()
    assert output_path.with_suffix(".json").exists()
    assert metadata_path.with_suffix(".json").exists()
    assert court_grade_path.with_suffix(".json").exists()
    assert output_path.with_suffix(".md.snapshot.json").exists()

    assert "`a.db`" in exact_text
    assert "`b.db`" in exact_text
    assert "| CBIC | 10 | 20 | 50.0% | — | — | FAIL | PASS | PATCHING |" in exact_text
    assert "| CA Debates | 8 | 10 | 80.0% | — | — | FAIL | PASS | PATCHING |" in exact_text

    metadata_text = metadata_path.read_text(encoding="utf-8")
    assert "| CBIC | 10 |" in metadata_text
    assert "| CA Debates | 8 |" in metadata_text
    assert "PASS" in metadata_text

    court_grade_text = court_grade_path.read_text(encoding="utf-8")
    assert "| Regulators | regulation | 0/1 | 0/1 | PATCHING |" in court_grade_text
    assert "| History | parliamentary_history | 0/1 | 0/1 | PATCHING |" in court_grade_text

    _append_case_law_docs(db1, start=10, count=2)
    _append_case_law_docs(db2, start=8, count=1)
    time.sleep(0.05)

    rc2 = main(
        [
            "--staging-dir",
            str(staging_dir),
            "--output",
            str(output_path),
            "--targets",
            str(targets_path),
            "--court-grade-targets",
            str(court_grade_targets),
            "--sqlite-timeout-seconds",
            "0.1",
            "--busy-timeout-ms",
            "100",
        ]
    )
    assert rc2 == 0
    exact_text2 = output_path.read_text(encoding="utf-8")
    assert "| CBIC | 12 | 20 | 60.0% | +2 |" in exact_text2
    assert "| CA Debates | 9 | 10 | 90.0% | +1 |" in exact_text2
    assert "RUNNING_HEALTHY" in exact_text2


def test_update_exact_target_audit_have_only_when_no_targets(tmp_path: Path) -> None:
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)

    db1 = staging_dir / "a.db"
    _create_minimal_staging_db(db1, docs=2)

    output_path = tmp_path / "EXACT_TARGET_AUDIT.md"
    rc = main(
        [
            "--staging-dir",
            str(staging_dir),
            "--output",
            str(output_path),
            "--sqlite-timeout-seconds",
            "0.1",
            "--busy-timeout-ms",
            "100",
        ]
    )

    assert rc == 0
    text = output_path.read_text(encoding="utf-8")
    assert "## HAVE vs NEED (targets)" in text
    assert "No targets config found" in text
    assert (tmp_path / "METADATA_QUALITY_AUDIT.md").exists()


def test_update_exact_target_audit_reuses_last_known_count_for_locked_db(tmp_path: Path) -> None:
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)

    ok_db = staging_dir / "ok.db"
    locked_db = staging_dir / "locked.db"
    _create_case_law_staging_db(ok_db, docs=3)
    _create_case_law_staging_db(locked_db, docs=2)

    targets_path = tmp_path / "exact_targets.json"
    _write_targets(
        targets_path,
        {
            "sources": {
                "cbic": {"display": "CBIC", "db": "ok.db", "need": 10},
                "sebi": {"display": "SEBI", "db": "locked.db", "need": 10}
            }
        },
    )

    output_path = tmp_path / "EXACT_TARGET_AUDIT.md"
    rc = main(
        [
            "--staging-dir",
            str(staging_dir),
            "--output",
            str(output_path),
            "--targets",
            str(targets_path),
            "--sqlite-timeout-seconds",
            "0.1",
            "--busy-timeout-ms",
            "100",
        ]
    )
    assert rc == 0

    lock_conn = sqlite3.connect(locked_db)
    lock_cur = lock_conn.cursor()
    lock_cur.execute("BEGIN EXCLUSIVE")

    start = time.monotonic()
    try:
        rc2 = main(
            [
                "--staging-dir",
                str(staging_dir),
                "--output",
                str(output_path),
                "--targets",
                str(targets_path),
                "--sqlite-timeout-seconds",
                "0.1",
                "--busy-timeout-ms",
                "100",
                "--per-db-timeout-seconds",
                "0.5",
            ]
        )
    finally:
        lock_conn.rollback()
        lock_conn.close()

    elapsed = time.monotonic() - start
    assert rc2 == 0
    assert elapsed < 10.0

    text = output_path.read_text(encoding="utf-8")
    assert (
        "| `ok.db` | ok | 3 |" in text
        or "| `ok.db` | timeout_last_known | 3 |" in text
        or "| `ok.db` | locked_last_known | 3 |" in text
        or "| `ok.db` | operational_error_last_known | 3 |" in text
        or "| `ok.db` | error_last_known | 3 |" in text
    )
    assert (
        "| `locked.db` | locked_last_known | 2 |" in text
        or "| `locked.db` | timeout_last_known | 2 |" in text
        or "| `locked.db` | operational_error_last_known | 2 |" in text
        or "| `locked.db` | error_last_known | 2 |" in text
    )
    assert "Scanned documents (sum across readable or last-known DBs): **5**" in text


def test_update_exact_target_audit_count_done_but_metadata_pending(tmp_path: Path) -> None:
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)

    db1 = staging_dir / "a.db"
    _create_minimal_staging_db(db1, docs=2)

    targets_path = tmp_path / "exact_targets.json"
    _write_targets(
        targets_path,
        {
            "sources": {
                "cbic": {"display": "CBIC", "db": "a.db", "need": 2}
            }
        },
    )

    court_grade_targets = tmp_path / "court_grade_targets.json"
    _write_targets(
        court_grade_targets,
        {
            "families": {
                "regulators": {
                    "display": "Regulators",
                    "depends_on_exact": ["cbic"],
                    "depends_on_families": [],
                    "critical": True,
                    "layer": "regulation"
                }
            }
        },
    )

    output_path = tmp_path / "EXACT_TARGET_AUDIT.md"
    rc = main(
        [
            "--staging-dir",
            str(staging_dir),
            "--output",
            str(output_path),
            "--targets",
            str(targets_path),
            "--court-grade-targets",
            str(court_grade_targets),
            "--sqlite-timeout-seconds",
            "0.1",
            "--busy-timeout-ms",
            "100",
        ]
    )

    assert rc == 0
    exact_text = output_path.read_text(encoding="utf-8")
    metadata_text = (tmp_path / "METADATA_QUALITY_AUDIT.md").read_text(encoding="utf-8")
    court_grade_text = (tmp_path / "COURT_GRADE_COMPLETENESS_AUDIT.md").read_text(encoding="utf-8")

    assert "| CBIC | 2 | 2 | 100.0% | — | — | PASS | FAIL | COUNT_DONE_METADATA_PENDING |" in exact_text
    assert "| CBIC | 2 |" in metadata_text
    assert "FAIL" in metadata_text
    assert "| Regulators | regulation | 0/1 | 0/1 | COUNT_DONE_METADATA_PENDING |" in court_grade_text
