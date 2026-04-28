from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from app.ingestion.scripts.update_staging_status import main


def _create_minimal_staging_db(db_path: Path, *, docs: int, chunks: int) -> None:
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
        cur.execute(
            """
            CREATE TABLE document_chunks (
                chunk_id TEXT PRIMARY KEY,
                doc_id TEXT
            )
            """.strip()
        )

        for i in range(docs):
            cur.execute(
                "INSERT INTO legal_documents (doc_id, source_system) VALUES (?, ?)\n",
                (f"doc-{i}", "aws" if i % 2 == 0 else "manual"),
            )
        for i in range(chunks):
            cur.execute(
                "INSERT INTO document_chunks (chunk_id, doc_id) VALUES (?, ?)\n",
                (f"chunk-{i}", f"doc-{i % max(docs, 1)}"),
            )

        conn.commit()
    finally:
        conn.close()


def test_update_staging_status_skips_locked_db(tmp_path: Path) -> None:
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)

    ok_db = staging_dir / "ok.db"
    locked_db = staging_dir / "locked.db"
    _create_minimal_staging_db(ok_db, docs=3, chunks=7)
    _create_minimal_staging_db(locked_db, docs=2, chunks=5)

    # Hold an exclusive lock on one DB to force the status script to fail fast.
    lock_conn = sqlite3.connect(locked_db)
    lock_cur = lock_conn.cursor()
    lock_cur.execute("BEGIN EXCLUSIVE")

    output_path = tmp_path / "STAGING_STATUS.md"

    start = time.monotonic()
    try:
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
    finally:
        lock_conn.rollback()
        lock_conn.close()

    elapsed = time.monotonic() - start

    assert rc == 0
    assert elapsed < 5.0

    text = output_path.read_text(encoding="utf-8")
    assert "`ok.db`" in text
    assert "| `ok.db` | ok | 3 | 7 |" in text

    # Locked DB should be reported and not block the whole run.
    assert "`locked.db`" in text
    assert "| `locked.db` | locked |" in text


def test_update_staging_status_marks_timeout(tmp_path: Path) -> None:
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)

    slow_db = staging_dir / "slow.db"
    _create_minimal_staging_db(slow_db, docs=10, chunks=10)

    output_path = tmp_path / "STAGING_STATUS.md"

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
            # 1ms budget should always force a timeout because process startup
            # overhead alone exceeds this.
            "--per-db-timeout-seconds",
            "0.001",
        ]
    )

    assert rc == 0
    text = output_path.read_text(encoding="utf-8")
    assert "`slow.db`" in text
    assert "| `slow.db` | timeout |" in text
