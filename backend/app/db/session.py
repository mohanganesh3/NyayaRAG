from collections.abc import Iterator
from functools import lru_cache

from app.core.config import Settings, get_settings
from sqlalchemy import event
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker


def _sqlite_connect_args(database_url: str) -> dict[str, object]:
    """SQLite connect_args tuned for long-running ingestion.

    - check_same_thread=False: allow SQLAlchemy sessions across threads/tasks.
    - timeout: wait on transient locks instead of failing fast with "database is locked".
    """

    if database_url.startswith("sqlite"):
        return {
            "check_same_thread": False,
            # sqlite3 module timeout in seconds
            "timeout": 60.0,
        }
    return {}


def _configure_sqlite_connection(dbapi_connection) -> None:
    """Apply PRAGMAs that improve concurrency and integrity for SQLite."""

    cursor = dbapi_connection.cursor()
    try:
        # Enforce FK constraints.
        cursor.execute("PRAGMA foreign_keys=ON")
        # Prefer WAL for better read/write concurrency.
        cursor.execute("PRAGMA journal_mode=WAL")
        # Reasonable durability/perf tradeoff for ingestion.
        cursor.execute("PRAGMA synchronous=NORMAL")
        # Busy timeout in milliseconds (separate from sqlite3 connect timeout).
        cursor.execute("PRAGMA busy_timeout=60000")
    finally:
        cursor.close()


def build_engine(database_url: str) -> Engine:
    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args=_sqlite_connect_args(database_url),
    )

    if database_url.startswith("sqlite"):
        event.listen(engine, "connect", lambda dbapi_conn, _rec: _configure_sqlite_connection(dbapi_conn))

    return engine


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return build_engine(settings.database_url)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, future=True)


def reset_db_caches() -> None:
    get_engine.cache_clear()
    get_session_factory.cache_clear()


def get_db() -> Iterator[Session]:
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


def check_database_connection(settings: Settings | None = None) -> tuple[bool, str | None]:
    engine = build_engine(settings.database_url) if settings is not None else get_engine()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, None
    except SQLAlchemyError as exc:
        return False, str(exc.__class__.__name__)
    finally:
        if settings is not None:
            engine.dispose()
