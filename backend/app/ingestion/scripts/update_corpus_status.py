from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import build_engine
from app.models import LegalDocument, StatuteAmendment, StatuteDocument, StatuteSection


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="update_corpus_status",
        description="Refresh data/collection/CORPUS_STATUS.md from the live database.",
    )
    db_group = parser.add_mutually_exclusive_group(required=True)
    db_group.add_argument(
        "--database-url",
        help=(
            "SQLAlchemy database URL. For an absolute SQLite path, prefer --database-path "
            "or use sqlite+pysqlite:////absolute/path.db"
        ),
    )
    db_group.add_argument(
        "--database-path",
        type=Path,
        help="Path to a SQLite database file.",
    )
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
    return parser


def _count(session: Session, stmt) -> int:
    return int(session.scalar(stmt) or 0)


def _build_sqlite_engine(database_url: str, *, sqlite_timeout_seconds: float, busy_timeout_ms: int):
    # Prefer fail-fast behavior for status reporting; ingestion uses longer timeouts.
    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={
            "check_same_thread": False,
            "timeout": float(sqlite_timeout_seconds),
        },
    )

    from sqlalchemy import event

    def _configure(dbapi_connection, _rec):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
        finally:
            cursor.close()

    event.listen(engine, "connect", _configure)
    return engine


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database_url = args.database_url
    if database_url is None:
        db_path: Path = args.database_path
        # Note: `sqlite+pysqlite:///{abs_path}` becomes `sqlite+pysqlite:////abs_path`
        # because `abs_path` begins with a leading slash.
        database_url = f"sqlite+pysqlite:///{db_path.resolve()}"

    sqlite_timeout_seconds: float = args.sqlite_timeout_seconds
    busy_timeout_ms: int = args.busy_timeout_ms

    engine = (
        _build_sqlite_engine(
            database_url,
            sqlite_timeout_seconds=sqlite_timeout_seconds,
            busy_timeout_ms=busy_timeout_ms,
        )
        if database_url.startswith("sqlite")
        else build_engine(database_url)
    )

    status_note: str | None = None
    supreme_court = 0
    high_courts = 0
    statutes = 0
    sections = 0
    amendments = 0
    try:
        with Session(engine) as session:
            supreme_court = _count(
                session,
                select(func.count()).select_from(LegalDocument).where(
                    LegalDocument.source_system == "supreme_court_aws_bulk"
                ),
            )
            high_courts = _count(
                session,
                select(func.count()).select_from(LegalDocument).where(
                    LegalDocument.source_system == "high_court_aws_bulk"
                ),
            )
            statutes = _count(session, select(func.count()).select_from(StatuteDocument))
            sections = _count(session, select(func.count()).select_from(StatuteSection))
            amendments = _count(session, select(func.count()).select_from(StatuteAmendment))
    except OperationalError as exc:
        message = str(exc).lower()
        if "database is locked" in message:
            status_note = "Live DB is locked; counts may be stale/unavailable."
        else:
            status_note = f"OperationalError while reading live DB: {type(exc).__name__}"
    except SQLAlchemyError as exc:
        status_note = f"Database error while reading live DB: {type(exc).__name__}"
    finally:
        engine.dispose()

    content = "\n".join(
        [
            "# NyayaRAG Corpus Status",
            f"Last updated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            *( [f"\n**Note:** {status_note}"] if status_note else [] ),
            "",
            "## Document Counts",
            f"Supreme Court judgments (AWS bulk): {supreme_court}",
            f"High Court judgments (AWS bulk): {high_courts}",
            "",
            "## Statute Counts",
            f"Central acts: {statutes}",
            f"Total sections: {sections}",
            f"Amendment events: {amendments}",
            "",
            "## Sources Completed",
            f"[{'x' if supreme_court >= 35000 else ' '}] Supreme Court AWS bulk",
            f"[{'x' if high_courts >= 500000 else ' '}] High Courts AWS bulk",
        ]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
