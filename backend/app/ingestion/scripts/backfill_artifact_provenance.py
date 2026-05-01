from __future__ import annotations

import argparse
import json
import sqlite3
import time
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5


def _sqlite_path_from_url(database_url: str) -> str:
    # Supports: sqlite+pysqlite:////abs/path or sqlite+pysqlite:///relative/path
    # Also supports: sqlite:////abs/path or sqlite:///relative/path
    for prefix in ("sqlite+pysqlite://", "sqlite://"):
        if database_url.startswith(prefix):
            # Strip the scheme and leave the path portion.
            # Example: sqlite+pysqlite:////tmp/foo.db -> ////tmp/foo.db
            path = database_url[len(prefix) :]
            # SQLAlchemy-style URLs include an extra leading slash for absolute paths.
            # Normalize ////abs/path -> /abs/path
            if path.startswith("////"):
                return path[3:]
            if path.startswith("///"):
                return path[2:]
            return path
    raise ValueError(f"Unsupported database_url (expected sqlite): {database_url}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backfill_artifact_provenance",
        description=(
            "Backfill artifact_provenance rows for legal_documents that are missing provenance entries. "
            "Uses deterministic UUIDv5 IDs and INSERT OR IGNORE for idempotency."
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--database-path", help="Path to the SQLite DB (e.g. data/collection/live_corpus.db)")
    group.add_argument(
        "--database-url",
        help="SQLAlchemy database URL (sqlite+pysqlite:////abs/path).",
    )
    parser.add_argument(
        "--commit-every",
        type=int,
        default=5000,
        help="Commit after this many inserted rows (default: 5000).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write changes; only report what would be inserted.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    db_path = str(args.database_path) if args.database_path else _sqlite_path_from_url(str(args.database_url))
    commit_every = max(1, int(args.commit_every))

    started_at = datetime.now(UTC)
    t0 = time.perf_counter()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")

        baseline = int(conn.execute("SELECT COUNT(*) FROM artifact_provenance").fetchone()[0])

        select_sql = (
            "SELECT ld.doc_id, ld.source_system, ld.ingestion_run_id, "
            "       COALESCE(ld.artifact_url, ld.source_url) AS canonical_url, "
            "       ld.source_url, COALESCE(ld.provenance_tier, 'official') AS provenance_tier, "
            "       ld.checksum, ld.mime_type "
            "FROM legal_documents ld "
            "LEFT JOIN artifact_provenance ap ON ap.doc_id = ld.doc_id "
            "WHERE ap.doc_id IS NULL"
        )

        insert_sql = (
            "INSERT OR IGNORE INTO artifact_provenance ("
            "  id, doc_id, source_key, ingestion_run_id, canonical_url, mirror_url, retrieved_from, "
            "  provenance_tier, sha256, mime_type, http_status, fetched_at, promotion_state, payload"
            ") VALUES (?,?,?,?,?,NULL,?,?,?,?,NULL,NULL,?,NULL)"
        )

        scanned = 0
        inserted_est = 0
        pending: list[tuple[object, ...]] = []
        before_changes = conn.total_changes

        def flush() -> None:
            nonlocal inserted_est, before_changes
            if not pending:
                return
            if args.dry_run:
                pending.clear()
                return
            conn.executemany(insert_sql, pending)
            conn.commit()
            after_changes = conn.total_changes
            inserted_est += after_changes - before_changes
            before_changes = after_changes
            pending.clear()

        for row in conn.execute(select_sql):
            scanned += 1
            doc_id = row["doc_id"]
            canonical_url = row["canonical_url"]
            sha256 = row["checksum"]
            prov_id = str(uuid5(NAMESPACE_URL, f"artifact_provenance|{doc_id}|{canonical_url}|{sha256}"))

            pending.append(
                (
                    prov_id,
                    doc_id,
                    row["source_system"],
                    row["ingestion_run_id"],
                    canonical_url,
                    row["source_url"] or canonical_url,
                    row["provenance_tier"],
                    sha256,
                    row["mime_type"],
                    "official",  # promotion_state
                )
            )

            if len(pending) >= commit_every:
                flush()

        flush()

        final = int(conn.execute("SELECT COUNT(*) FROM artifact_provenance").fetchone()[0])

    finally:
        conn.close()

    completed_at = datetime.now(UTC)
    payload = {
        "database_path": db_path,
        "dry_run": bool(args.dry_run),
        "commit_every": commit_every,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": round(time.perf_counter() - t0, 2),
        "baseline_rows": baseline,
        "scanned_missing_docs": scanned,
        "rows_inserted_est": inserted_est,
        "final_rows": final,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
