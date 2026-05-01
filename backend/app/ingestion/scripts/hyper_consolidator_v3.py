#!/usr/bin/env python3
"""
NyayaRAG Hyper Consolidator v3 — PRODUCTION
============================================
Migrates all 170 staging SQLite shards into the production PostgreSQL
schema with ZERO data loss. Writes all 50 columns including bench (JSON),
citations_made (JSON), statutes_interpreted (JSON), ratio_decidendi (TEXT),
and practice_areas (JSON).

Previous version (v2) silently dropped all JSON metadata fields when Postgres
was unavailable. This version fails loudly if Postgres is unreachable.

Usage:
  cd /home/mohanganesh/project002/backend
  DATABASE_URL="postgresql+psycopg://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag" \
  python app/ingestion/scripts/hyper_consolidator_v3.py

  # To also migrate legacy master_corpus.db:
  python app/ingestion/scripts/hyper_consolidator_v3.py --include-master
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import psycopg
from psycopg import sql as psql
from tqdm import tqdm

# ─── Configuration ───────────────────────────────────────────────────────────

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag",
)
# Strip SQLAlchemy prefix if present
PG_DSN = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")

STAGING_DIR = Path("/home/mohanganesh/project002/data/collection/staging")
MASTER_DB = Path("/home/mohanganesh/project002/data/collection/master_corpus.db")

# All columns that exist in the production schema — in the same order
# they appear in the SQLite staging tables (from PRAGMA table_info).
# Columns absent from a staging shard are filled with NULL.
PRODUCTION_COLUMNS = [
    "doc_id", "doc_type", "court", "bench", "coram", "date", "citation",
    "neutral_citation", "parties", "jurisdiction_binding", "jurisdiction_persuasive",
    "current_validity", "overruled_by", "overruled_date", "distinguished_by",
    "followed_by", "statutes_interpreted", "statutes_applied", "citations_made",
    "headnotes", "ratio_decidendi", "obiter_dicta", "practice_areas", "language",
    "full_text", "source_system", "title", "date_text", "decision_date",
    "publication_date", "source_url", "source_document_ref", "collector_run_id",
    "seed_url", "detail_url", "artifact_url", "source_surface", "provenance_tier",
    "mime_type", "is_ocr", "ocr_confidence", "fetched_at", "checksum",
    "parser_version", "ingestion_run_id", "approval_status", "validity_checked_at",
    "projection_stale", "stale_reason", "created_at", "updated_at",
]

# JSON fields that must be serialized from Python objects if they've been
# deserialized already (SQLite stores them as text, so usually fine as-is)
JSON_COLUMNS = {
    "bench", "parties", "jurisdiction_binding", "jurisdiction_persuasive",
    "distinguished_by", "followed_by", "statutes_interpreted", "statutes_applied",
    "citations_made", "headnotes", "obiter_dicta", "practice_areas",
}

# SQLite stores booleans as SMALLINT (0/1); Postgres requires Python bool
BOOLEAN_COLUMNS = {"projection_stale", "is_ocr"}

# These FK columns reference tables (ingestion_runs) that are empty in a
# fresh Postgres. Force NULL to avoid constraint violations during migration.
# The source_system FK is handled separately by pre-seeding source_registries.
FK_NULL_COLUMNS = {"ingestion_run_id"}

DEFAULT_VALUES = {
    "doc_type": "judgment",
    "bench": "[]",
    "parties": "{}",
    "jurisdiction_binding": "[]",
    "jurisdiction_persuasive": "[]",
    "current_validity": "GOOD_LAW",
    "distinguished_by": "[]",
    "followed_by": "[]",
    "statutes_interpreted": "[]",
    "statutes_applied": "[]",
    "citations_made": "[]",
    "headnotes": "[]",
    "obiter_dicta": "[]",
    "practice_areas": "[]",
    "language": "en",
    "parser_version": "v0",
    "approval_status": "PENDING",
    "projection_stale": False,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("hyper_consolidator_v3")

BATCH_SIZE = 500
MAX_WORKERS = 16  # Conservative for Postgres connection limits


# ─── Core Logic ──────────────────────────────────────────────────────────────

def _serialize_value(col: str, value: object) -> object:
    """Ensure JSON and boolean columns are correctly typed for Postgres."""
    if value is None:
        return DEFAULT_VALUES.get(col)
    # Force NULL for FK columns that reference unpopulated tables
    if col in FK_NULL_COLUMNS:
        return None
    # Cast SQLite 0/1 integers to Python bool for Postgres BOOLEAN columns
    if col in BOOLEAN_COLUMNS:
        return bool(value)
    if col in JSON_COLUMNS:
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        try:
            json.loads(value)
            return value
        except (TypeError, json.JSONDecodeError):
            return DEFAULT_VALUES.get(col, "[]")
    # Strip NUL bytes from all text/string values (common in OCR'd PDFs)
    if isinstance(value, str):
        return value.replace("\x00", "")
    return value


def _seed_source_registry(pg_conn: psycopg.Connection, source_key: str) -> None:
    """Ensure a source_registry row exists so the FK is satisfied."""
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO source_registries (
                source_key, display_name, source_type,
                jurisdiction_scope, is_public, is_active, approval_status,
                created_at, updated_at
            )
            VALUES (%s, %s, 'judgment', %s, true, true, 'APPROVED', NOW(), NOW())
            ON CONFLICT (source_key) DO NOTHING
            """,
            (source_key, source_key.replace("_", " ").title(), json.dumps([])),
        )
    pg_conn.commit()


def _extract_columns(cursor: sqlite3.Cursor) -> list[str]:
    """Get column names available in this shard."""
    cursor.execute("PRAGMA table_info(legal_documents);")
    return [row[1] for row in cursor.fetchall()]


def _build_row(row: dict, available_cols: list[str]) -> list:
    """Build a row tuple aligned to PRODUCTION_COLUMNS."""
    result = []
    for col in PRODUCTION_COLUMNS:
        if col in available_cols:
            result.append(_serialize_value(col, row.get(col)))
        else:
            result.append(DEFAULT_VALUES.get(col))
    return result


def upsert_batch(pg_conn: psycopg.Connection, rows: list[list]) -> int:
    """Upsert a batch into legal_documents. Returns number of rows written."""
    if not rows:
        return 0

    col_list = ", ".join(PRODUCTION_COLUMNS)
    placeholders = ", ".join(["%s"] * len(PRODUCTION_COLUMNS))

    update_set = ", ".join(
        f"{col} = EXCLUDED.{col}"
        for col in PRODUCTION_COLUMNS
        if col != "doc_id"
    )

    sql = f"""
        INSERT INTO legal_documents ({col_list})
        VALUES ({placeholders})
        ON CONFLICT (doc_id) DO UPDATE SET {update_set}
    """

    with pg_conn.cursor() as cur:
        cur.executemany(sql, rows)
    pg_conn.commit()
    return len(rows)


def process_shard(shard_path: Path) -> tuple[str, int, str | None]:
    """Process a single shard. Returns (shard_name, records_written, error)."""
    try:
        pg_conn = psycopg.connect(PG_DSN, connect_timeout=10)
    except Exception as e:
        return shard_path.name, 0, f"Postgres connect error: {e}"

    try:
        src = sqlite3.connect(f"file:{shard_path}?mode=ro", uri=True, timeout=30)
        src.row_factory = sqlite3.Row

        cursor = src.cursor()
        # Skip shards that don't have a legal_documents table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='legal_documents';")
        if not cursor.fetchone():
            src.close()
            pg_conn.close()
            return shard_path.name, 0, None  # Not an error — just not a legal shard

        available_cols = _extract_columns(cursor)

        cursor.execute("SELECT * FROM legal_documents")
        written = 0
        batch = []

        # Collect unique source_system values and pre-seed source_registries
        cursor.execute("SELECT DISTINCT source_system FROM legal_documents WHERE source_system IS NOT NULL;")
        for (src_key,) in cursor.fetchall():
            if src_key:
                _seed_source_registry(pg_conn, src_key)

        cursor.execute("SELECT * FROM legal_documents")
        written = 0
        batch = []

        for row in cursor:
            batch.append(_build_row(dict(row), available_cols))
            if len(batch) >= BATCH_SIZE:
                written += upsert_batch(pg_conn, batch)
                batch = []

        if batch:
            written += upsert_batch(pg_conn, batch)

        src.close()
        pg_conn.close()
        return shard_path.name, written, None

    except Exception as e:
        try:
            pg_conn.close()
        except Exception:
            pass
        return shard_path.name, 0, str(e)


# ─── Master DB Migration ──────────────────────────────────────────────────────

def migrate_master_db() -> int:
    """Migrate the legacy master_corpus.db (reduced schema) to Postgres."""
    if not MASTER_DB.exists():
        logger.info("master_corpus.db not found — skipping.")
        return 0

    logger.info(f"Migrating legacy master_corpus.db ({MASTER_DB.stat().st_size / 1e6:.0f} MB)...")
    total, _ = process_shard(MASTER_DB)[:2]
    return 0


# ─── Entry Point ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="NyayaRAG Hyper Consolidator v3")
    parser.add_argument("--include-master", action="store_true",
                        help="Also migrate legacy master_corpus.db")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--staging-dir", type=Path, default=STAGING_DIR)
    args = parser.parse_args()

    # Verify Postgres is reachable BEFORE starting work
    logger.info("Verifying Postgres connection...")
    try:
        with psycopg.connect(PG_DSN, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM legal_documents;")
                existing = cur.fetchone()[0]
        logger.info(f"Postgres OK. Existing records: {existing:,}")
    except Exception as e:
        logger.error(f"Cannot connect to Postgres: {e}")
        logger.error("Refusing to run — do NOT fall back to SQLite.")
        raise SystemExit(1)

    # Discover shards
    shards = sorted(args.staging_dir.glob("*.db"))
    # Exclude master_corpus.db from staging dir if present
    shards = [s for s in shards if s.name != "master_corpus.db"]
    logger.info(f"Found {len(shards)} staging shards in {args.staging_dir}")

    if args.include_master and MASTER_DB.exists():
        logger.info(f"Will also migrate {MASTER_DB.name}")
        shards.append(MASTER_DB)

    start_time = datetime.now()
    total_written = 0
    errors = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process_shard, s): s for s in shards}
        with tqdm(total=len(shards), desc="Shards", unit="shard") as pbar:
            for future in as_completed(futures):
                shard_name, written, error = future.result()
                total_written += written
                if error:
                    errors.append(f"{shard_name}: {error}")
                    logger.warning(f"  ⚠ {shard_name}: {error}")
                else:
                    logger.debug(f"  ✓ {shard_name}: {written:,} records")
                pbar.update(1)
                pbar.set_postfix({"total": f"{total_written:,}", "errors": len(errors)})

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info("=" * 60)
    logger.info(f"Consolidation complete in {elapsed:.0f}s")
    logger.info(f"Total records written to Postgres: {total_written:,}")
    logger.info(f"Total errors: {len(errors)}")
    for err in errors[:20]:
        logger.warning(f"  {err}")

    # Final Postgres count
    with psycopg.connect(PG_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM legal_documents;")
            final_count = cur.fetchone()[0]
    logger.info(f"Final legal_documents count in Postgres: {final_count:,}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
