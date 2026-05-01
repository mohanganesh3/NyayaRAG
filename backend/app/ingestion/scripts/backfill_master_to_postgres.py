#!/usr/bin/env python3
import os
import json
import sqlite3
import psycopg
from psycopg.rows import dict_row
import logging
from pathlib import Path
from tqdm import tqdm

# Configuration
POSTGRES_DSN = "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag"
MASTER_DB = "/home/mohanganesh/project002/data/collection/master_corpus.db"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("master_backfiller")

# FULL COURT-GRADE SCHEMA COLUMNS
COLUMNS = [
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
    "projection_stale", "stale_reason"
]

JSON_COLUMNS = {
    "bench", "parties", "jurisdiction_binding", "jurisdiction_persuasive",
    "distinguished_by", "followed_by", "statutes_interpreted", "statutes_applied",
    "citations_made", "headnotes", "obiter_dicta", "practice_areas"
}

def get_postgres_connection():
    try:
        return psycopg.connect(POSTGRES_DSN, row_factory=dict_row)
    except Exception as e:
        logger.error(f"Failed to connect to Postgres: {e}")
        raise

BOOLEAN_COLUMNS = {"is_ocr", "projection_stale"}
FK_COLUMNS = {"ingestion_run_id", "source_system"}
TRUNCATE_255 = {"court", "citation", "neutral_citation", "source_document_ref", "date_text", "checksum"}

def serialize_row(row):
    d = dict(row)
    for key, val in d.items():
        if isinstance(val, str):
            d[key] = val.replace("\x00", "")

    for col in JSON_COLUMNS:
        val = d.get(col)
        if val is None:
            d[col] = json.dumps([]) if col != "parties" else json.dumps({})
        elif isinstance(val, (list, dict)):
            d[col] = json.dumps(val)
        elif isinstance(val, str):
            clean_val = val.replace("\x00", "")
            try:
                json.loads(clean_val)
                d[col] = clean_val
            except:
                d[col] = json.dumps([clean_val])
    
    for col in BOOLEAN_COLUMNS:
        if col in d:
            if d[col] is not None:
                d[col] = bool(d[col])

    for col in FK_COLUMNS:
        d[col] = None

    for col in TRUNCATE_255:
        if d.get(col) and isinstance(d[col], str):
            d[col] = d[col][:255]

    for col in COLUMNS:
        if col not in d:
            d[col] = None
    return d

def upsert_batch(cur, batch):
    cols_str = ", ".join(COLUMNS)
    placeholders = ", ".join([f"%({c})s" for c in COLUMNS])
    update_str = ", ".join([f"{c} = EXCLUDED.{c}" for c in COLUMNS if c != "doc_id"])
    
    sql = f"""
        INSERT INTO legal_documents ({cols_str})
        VALUES ({placeholders})
        ON CONFLICT (doc_id) DO UPDATE SET {update_str}
    """
    cur.executemany(sql, batch)

def main():
    if not os.path.exists(MASTER_DB):
        logger.error(f"Master DB not found at {MASTER_DB}")
        return

    pg_conn = get_postgres_connection()
    source_conn = sqlite3.connect(MASTER_DB)
    source_conn.row_factory = sqlite3.Row
    
    # Get total count for progress bar
    total = source_conn.execute("SELECT count(*) FROM legal_documents").fetchone()[0]
    logger.info(f"Starting backfill of {total:,} records from Master SQLite to Postgres...")
    
    cursor = source_conn.execute("SELECT * FROM legal_documents")
    batch = []
    
    with pg_conn.cursor() as pg_cur:
        for row in tqdm(cursor, total=total):
            batch.append(serialize_row(row))
            if len(batch) >= 1000:
                upsert_batch(pg_cur, batch)
                pg_conn.commit()
                batch = []
        if batch:
            upsert_batch(pg_cur, batch)
            pg_conn.commit()

    logger.info("Master backfill complete.")
    source_conn.close()
    pg_conn.close()

if __name__ == "__main__":
    main()
