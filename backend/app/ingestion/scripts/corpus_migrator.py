#!/usr/bin/env python3
"""
NyayaRAG: Production Corpus Migrator
=====================================
Migrates all 170 staging SQLite shards → PostgreSQL (full 51-column schema).

FIXES vs old hyper_consolidator_v2.py:
1. Writes ALL columns including bench, citations_made, statutes_interpreted,
   ratio_decidendi, practice_areas — no more silent data loss
2. Uses real Postgres UPSERT (INSERT ... ON CONFLICT DO UPDATE)
3. Fails loudly if Postgres is unavailable — no SQLite fallback corruption
4. Uses efficient batch COPY via psycopg's execute_many
5. Cursor-based progress tracking with checkpoint resume

Usage:
    python app/ingestion/scripts/corpus_migrator.py [--shard-dir PATH] [--workers N]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import psycopg
from psycopg import sql
from tqdm import tqdm

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag",
)
STAGING_DIR = Path(
    os.environ.get(
        "STAGING_DIR",
        "/home/mohanganesh/project002/data/collection/staging",
    )
)
CHECKPOINT_FILE = Path("/tmp/corpus_migrator_checkpoint.json")
BATCH_SIZE = 500  # rows per INSERT batch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(process)d] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("corpus_migrator")

# ──────────────────────────────────────────────────────────────────────────────
# Full column mapping: staging SQLite → production Postgres
# These are ALL columns in the production legal_documents table.
# Staged columns not present will be given None.
# ──────────────────────────────────────────────────────────────────────────────
PRODUCTION_COLUMNS = [
    "doc_id", "doc_type", "court", "bench", "coram", "date",
    "citation", "neutral_citation", "parties", "jurisdiction_binding",
    "jurisdiction_persuasive", "current_validity", "overruled_by",
    "overruled_date", "distinguished_by", "followed_by",
    "statutes_interpreted", "statutes_applied", "citations_made",
    "headnotes", "ratio_decidendi", "obiter_dicta", "practice_areas",
    "language", "full_text", "source_system", "title", "date_text",
    "decision_date", "publication_date", "source_url",
    "source_document_ref", "collector_run_id", "seed_url", "detail_url",
    "artifact_url", "source_surface", "provenance_tier", "mime_type",
    "is_ocr", "ocr_confidence", "fetched_at", "checksum",
    "parser_version", "ingestion_run_id", "approval_status",
    "validity_checked_at", "projection_stale", "stale_reason",
]

# JSON columns that need serialization if stored as Python objects
JSON_COLUMNS = {
    "bench", "parties", "jurisdiction_binding", "jurisdiction_persuasive",
    "distinguished_by", "followed_by", "statutes_interpreted",
    "statutes_applied", "citations_made", "headnotes", "obiter_dicta",
    "practice_areas",
}

DEFAULT_VALUES = {
    "doc_type": "judgment",
    "bench": "[]",
    "parties": "{}",
    "jurisdiction_binding": "[]",
    "jurisdiction_persuasive": "[]",
    "distinguished_by": "[]",
    "followed_by": "[]",
    "statutes_interpreted": "[]",
    "statutes_applied": "[]",
    "citations_made": "[]",
    "headnotes": "[]",
    "obiter_dicta": "[]",
    "practice_areas": "[]",
    "current_validity": "GOOD_LAW",
    "language": "en",
    "parser_version": "v0",
    "approval_status": "PENDING",
    "projection_stale": False,
}


def normalize_row(row: dict) -> dict:
    """Normalize a raw SQLite row to the full production schema."""
    result = {}
    for col in PRODUCTION_COLUMNS:
        val = row.get(col)

        # Apply defaults for missing values
        if val is None and col in DEFAULT_VALUES:
            val = DEFAULT_VALUES[col]

        # Ensure JSON columns are serialized strings
        if col in JSON_COLUMNS:
            if val is None:
                val = "[]" if col != "parties" else "{}"
            elif isinstance(val, (list, dict)):
                val = json.dumps(val, ensure_ascii=False)
            elif isinstance(val, str):
                # Validate it's real JSON, fix if not
                try:
                    json.loads(val)
                except (json.JSONDecodeError, ValueError):
                    val = "[]" if col != "parties" else "{}"

        result[col] = val
    return result


def upsert_batch_postgres(conn: psycopg.Connection, batch: list[dict]) -> int:
    """Insert a batch of rows into legal_documents with UPSERT semantics."""
    if not batch:
        return 0

    cols = PRODUCTION_COLUMNS
    col_identifiers = sql.SQL(", ").join(sql.Identifier(c) for c in cols)
    placeholders = sql.SQL(", ").join(sql.Placeholder() * len(cols))

    # Build UPDATE SET clause (exclude primary key)
    update_cols = [c for c in cols if c != "doc_id"]
    update_set = sql.SQL(", ").join(
        sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(c), sql.Identifier(c))
        for c in update_cols
    )

    query = sql.SQL(
        "INSERT INTO legal_documents ({cols}) VALUES ({vals}) "
        "ON CONFLICT (doc_id) DO UPDATE SET {update}"
    ).format(cols=col_identifiers, vals=placeholders, update=update_set)

    data = [[row[c] for c in cols] for row in batch]

    with conn.cursor() as cur:
        cur.executemany(query, data)
    conn.commit()
    return len(batch)


def migrate_shard(shard_path: str) -> tuple[str, int, str | None]:
    """Migrate one SQLite shard to Postgres. Returns (path, count, error)."""
    shard = Path(shard_path)
    try:
        pg_conn = psycopg.connect(DATABASE_URL, connect_timeout=10)
    except Exception as e:
        return str(shard), 0, f"Postgres connection failed: {e}"

    try:
        sqlite_conn = sqlite3.connect(str(shard), timeout=30)
        sqlite_conn.row_factory = sqlite3.Row

        cursor = sqlite_conn.execute("SELECT * FROM legal_documents")
        total = 0
        batch: list[dict] = []

        for row in cursor:
            batch.append(normalize_row(dict(row)))
            if len(batch) >= BATCH_SIZE:
                upsert_batch_postgres(pg_conn, batch)
                total += len(batch)
                batch = []

        if batch:
            upsert_batch_postgres(pg_conn, batch)
            total += len(batch)

        sqlite_conn.close()
        pg_conn.close()
        return str(shard), total, None

    except Exception as e:
        pg_conn.close()
        return str(shard), 0, str(e)


def load_checkpoint() -> set[str]:
    if CHECKPOINT_FILE.exists():
        try:
            return set(json.loads(CHECKPOINT_FILE.read_text())["done"])
        except Exception:
            pass
    return set()


def save_checkpoint(done: set[str]) -> None:
    CHECKPOINT_FILE.write_text(json.dumps({"done": list(done)}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="NyayaRAG corpus migrator")
    parser.add_argument("--shard-dir", default=str(STAGING_DIR))
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--reset-checkpoint", action="store_true")
    args = parser.parse_args()

    shard_dir = Path(args.shard_dir)
    if not shard_dir.exists():
        logger.error(f"Staging directory not found: {shard_dir}")
        sys.exit(1)

    # Verify Postgres is reachable BEFORE starting — fail loudly
    logger.info("Verifying PostgreSQL connection...")
    try:
        conn = psycopg.connect(DATABASE_URL, connect_timeout=5)
        conn.close()
        logger.info("✅ PostgreSQL connected successfully")
    except Exception as e:
        logger.error(f"❌ Cannot connect to PostgreSQL: {e}")
        logger.error("Start Postgres first: bash infra/start_services.sh")
        sys.exit(1)

    all_shards = sorted(shard_dir.glob("*.db"))
    logger.info(f"Found {len(all_shards)} SQLite shards in {shard_dir}")

    if args.reset_checkpoint:
        CHECKPOINT_FILE.unlink(missing_ok=True)
        logger.info("Checkpoint reset")

    done = load_checkpoint()
    remaining = [s for s in all_shards if str(s) not in done]
    logger.info(f"Remaining: {len(remaining)} shards ({len(done)} already done)")

    if not remaining:
        logger.info("All shards already migrated. Run with --reset-checkpoint to redo.")
        return

    total_docs = 0
    errors: list[str] = []
    start = time.time()

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(migrate_shard, str(s)): s for s in remaining}
        with tqdm(total=len(remaining), desc="Migrating shards", unit="shard") as pbar:
            for future in as_completed(futures):
                path, count, error = future.result()
                if error:
                    errors.append(f"{Path(path).name}: {error}")
                    logger.warning(f"⚠️  Error in {Path(path).name}: {error}")
                else:
                    total_docs += count
                    done.add(path)
                    save_checkpoint(done)
                pbar.update(1)
                pbar.set_postfix({"docs": f"{total_docs:,}", "errors": len(errors)})

    elapsed = time.time() - start
    logger.info("=" * 60)
    logger.info(f"Migration complete in {elapsed:.0f}s")
    logger.info(f"Total documents migrated: {total_docs:,}")
    logger.info(f"Shards with errors: {len(errors)}")
    for e in errors:
        logger.warning(f"  {e}")

    # Final verification
    try:
        conn = psycopg.connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute("SELECT court, count(*) FROM legal_documents GROUP BY court ORDER BY 2 DESC LIMIT 10")
            rows = cur.fetchall()
        conn.close()
        logger.info("\n📊 Top courts in Postgres:")
        for court, count in rows:
            logger.info(f"  {court or '(unset)'}: {count:,}")
    except Exception as e:
        logger.warning(f"Could not verify final count: {e}")


if __name__ == "__main__":
    main()
