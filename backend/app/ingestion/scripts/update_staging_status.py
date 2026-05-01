from __future__ import annotations

import argparse
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
import sqlite3
import multiprocessing as mp
import time


def _classify_sqlite_operational_error(exc: sqlite3.OperationalError) -> str:
    message = str(exc).lower()
    if "interrupted" in message:
        return "timeout"
    if "database is locked" in message or "database table is locked" in message:
        return "locked"
    if "no such table" in message:
        return "no_schema"
    return "operational_error"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="update_staging_status",
        description="Summarize staging SQLite corpus DBs into a Markdown status file.",
    )
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--sqlite-timeout-seconds",
        type=float,
        default=2.0,
        help="SQLite connection timeout (seconds). Lower values avoid hanging on locked DBs.",
    )
    parser.add_argument(
        "--busy-timeout-ms",
        type=int,
        default=2000,
        help="SQLite PRAGMA busy_timeout (milliseconds).",
    )
    parser.add_argument(
        "--per-db-timeout-seconds",
        type=float,
        default=5.0,
        help=(
            "Maximum time budget per DB (seconds). "
            "If exceeded, that DB is marked as 'timeout' and the script continues. "
            "This keeps status generation from hanging on huge/slow COUNT(*) scans."
        ),
    )
    return parser


def _open_sqlite_readonly(
    db_path: Path,
    *,
    sqlite_timeout_seconds: float,
    busy_timeout_ms: int,
) -> sqlite3.Connection:
    """Open a SQLite DB in read-only mode with bounded lock wait.

    Why sqlite3 instead of SQLAlchemy here?
    - This script is a *status reporter* and must never hang.
    - SQLAlchemy engine "connect" hooks (and PRAGMAs like journal_mode=WAL)
      can end up waiting for locks. Read-only sqlite3 avoids that.
    """

    # Use URI mode so we can force read-only.
    # NOTE: We intentionally do *not* set PRAGMA journal_mode or synchronous here;
    # those can require write locks and defeat the "fail fast" goal.
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(
        uri,
        uri=True,
        timeout=float(sqlite_timeout_seconds),
        check_same_thread=False,
    )
    with closing(conn.cursor()) as cursor:
        cursor.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
        cursor.execute("PRAGMA query_only=ON")
    return conn


def _scan_db(
    db_path: Path,
    *,
    sqlite_timeout_seconds: float,
    busy_timeout_ms: int,
    per_db_timeout_seconds: float,
) -> tuple[int, int, dict[str, int]]:
    """Return (total_docs, total_chunks, by_source_system) for a single DB."""

    # Keep a progress handler as a best-effort query abort mechanism, but do not
    # rely on it for correctness/termination. The caller enforces a hard timeout
    # by running this function in a separate process.
    with closing(
        _open_sqlite_readonly(
            db_path,
            sqlite_timeout_seconds=sqlite_timeout_seconds,
            busy_timeout_ms=busy_timeout_ms,
        )
    ) as conn:
        start = time.monotonic()

        def _progress_handler() -> int:
            if time.monotonic() - start > float(per_db_timeout_seconds):
                return 1
            return 0

        conn.set_progress_handler(_progress_handler, 10_000)
        try:
            with closing(conn.cursor()) as cursor:
                total_docs = int(cursor.execute("SELECT COUNT(*) FROM legal_documents").fetchone()[0])
                total_chunks = int(cursor.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0])

                by_source: dict[str, int] = {}
                for source_key, count in cursor.execute(
                    """
                    SELECT source_system, COUNT(*)
                    FROM legal_documents
                    GROUP BY source_system
                    ORDER BY COUNT(*) DESC
                    """.strip()
                ):
                    by_source[str(source_key)] = int(count)
        finally:
            conn.set_progress_handler(None, 0)

    return total_docs, total_chunks, by_source


def _scan_db_worker(
    db_path_str: str,
    sqlite_timeout_seconds: float,
    busy_timeout_ms: int,
    per_db_timeout_seconds: float,
    conn,
) -> None:
    db_path = Path(db_path_str)
    try:
        docs, chunks, by_source = _scan_db(
            db_path,
            sqlite_timeout_seconds=sqlite_timeout_seconds,
            busy_timeout_ms=busy_timeout_ms,
            per_db_timeout_seconds=per_db_timeout_seconds,
        )
        conn.send(("ok", docs, chunks, by_source))
    except sqlite3.OperationalError as exc:
        conn.send((_classify_sqlite_operational_error(exc), None, None, None))
    except Exception:
        conn.send(("error", None, None, None))
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _scan_db_with_timeout(
    db_path: Path,
    *,
    sqlite_timeout_seconds: float,
    busy_timeout_ms: int,
    per_db_timeout_seconds: float,
) -> tuple[str, int | None, int | None, dict[str, int] | None]:
    if per_db_timeout_seconds is None or float(per_db_timeout_seconds) <= 0:
        try:
            docs, chunks, by_source = _scan_db(
                db_path,
                sqlite_timeout_seconds=sqlite_timeout_seconds,
                busy_timeout_ms=busy_timeout_ms,
                per_db_timeout_seconds=5.0,
            )
            return "ok", docs, chunks, by_source
        except sqlite3.OperationalError as exc:
            return _classify_sqlite_operational_error(exc), None, None, None
        except Exception:
            return "error", None, None, None

    # Use "spawn" to avoid inheriting SQLite/POSIX locks from the parent process,
    # which would defeat the locked-DB detection and can cause surprising hangs.
    ctx = mp.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_scan_db_worker,
        args=(
            str(db_path),
            float(sqlite_timeout_seconds),
            int(busy_timeout_ms),
            float(per_db_timeout_seconds),
            child_conn,
        ),
        daemon=True,
    )
    proc.start()
    try:
        proc.join(timeout=float(per_db_timeout_seconds))
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=1.0)
            return "timeout", None, None, None

        if parent_conn.poll(0.1):
            status, docs, chunks, by_source = parent_conn.recv()
            return status, docs, chunks, by_source
        return "error", None, None, None
    finally:
        try:
            parent_conn.close()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    staging_dir: Path = args.staging_dir
    sqlite_timeout_seconds: float = args.sqlite_timeout_seconds
    busy_timeout_ms: int = args.busy_timeout_ms
    per_db_timeout_seconds: float = args.per_db_timeout_seconds

    rows: list[tuple[str, str, int | None, int | None, dict[str, int] | None]] = []
    for db_path in sorted(staging_dir.glob("*.db")):
        status, docs, chunks, by_source = _scan_db_with_timeout(
            db_path,
            sqlite_timeout_seconds=sqlite_timeout_seconds,
            busy_timeout_ms=busy_timeout_ms,
            per_db_timeout_seconds=per_db_timeout_seconds,
        )
        rows.append((db_path.name, status, docs, chunks, by_source))

    lines: list[str] = []
    lines.append("# NyayaRAG Staging DB Status")
    lines.append(f"Last updated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("")
    if not rows:
        lines.append("No staging DBs found.")
    else:
        lines.append("| staging db | status | documents | chunks | by source_system |")
        lines.append("|---|---|---:|---:|---|")
        for name, status, docs, chunks, by_source in rows:
            doc_text = f"{docs:,}" if docs is not None else "—"
            chunk_text = f"{chunks:,}" if chunks is not None else "—"
            source_summary = (
                ", ".join(f"{k}: {v}" for k, v in (by_source or {}).items())
                if by_source
                else ""
            )
            lines.append(f"| `{name}` | {status} | {doc_text} | {chunk_text} | {source_summary} |")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
