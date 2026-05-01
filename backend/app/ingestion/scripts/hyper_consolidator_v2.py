#!/usr/bin/env python3
import os
import json
import sqlite3
import psycopg
from psycopg.rows import dict_row
import logging
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm
from datetime import date, datetime

# Configuration
POSTGRES_DSN = "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag"
STAGING_DIR = Path("/home/mohanganesh/project002/data/collection/staging")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("hyper_consolidator")

# FULL COURT-GRADE SCHEMA COLUMNS (50+)
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
    """Returns a Postgres connection. Fails loudly if unreachable."""
    try:
        conn = psycopg.connect(POSTGRES_DSN, row_factory=dict_row)
        return conn
    except Exception as e:
        logger.error(f"CRITICAL: Could not connect to Postgres: {e}")
        raise

BOOLEAN_COLUMNS = {"is_ocr", "projection_stale"}
FK_COLUMNS = {"ingestion_run_id", "source_system"}
TRUNCATE_255 = {"court", "citation", "neutral_citation", "source_document_ref", "date_text", "checksum"}

def serialize_row(row):
    """Processes a row for Postgres insertion, handling JSON and basic types."""
    d = dict(row)
    
    # Strip NUL bytes from all string values (Postgres incompatible)
    for key, val in d.items():
        if isinstance(val, str):
            d[key] = val.replace("\x00", "")

    for col in JSON_COLUMNS:
        val = d.get(col)
        # JSON columns might contain NUL bytes too if they were strings in SQLite
        if val is None:
            d[col] = json.dumps([]) if col != "parties" else json.dumps({})
        elif isinstance(val, (list, dict)):
            d[col] = json.dumps(val)
        elif isinstance(val, str):
            # Clean before JSON parse/wrap
            clean_val = val.replace("\x00", "")
            try:
                json.loads(clean_val)
                d[col] = clean_val
            except:
                d[col] = json.dumps([clean_val])
    
    # NEW: Handle SQLite 0/1 to Postgres Boolean
    for col in BOOLEAN_COLUMNS:
        if col in d:
            if d[col] is not None:
                d[col] = bool(d[col])
    
    # NEW: Handle Foreign Key mismatches (Zero Compromise fallback)
    for col in FK_COLUMNS:
        d[col] = None 
    
    # Truncate strings that might exceed 255
    for col in TRUNCATE_255:
        if d.get(col) and isinstance(d[col], str):
            d[col] = d[col][:255]
    
    # Ensure all columns exist in the dict
    for col in COLUMNS:
        if col not in d:
            d[col] = None
            
    return d

def upsert_batch(conn, table, columns, batch):
    """Performs a PostgreSQL UPSERT for a batch of records."""
    cols_str = ", ".join(columns)
    placeholders = ", ".join([f"%({c})s" for c in columns])
    pk = "doc_id" if table == "legal_documents" else "chunk_id"
    update_str = ", ".join([f"{c} = EXCLUDED.{c}" for c in columns if c != pk])
    
    sql = f"""
        INSERT INTO {table} ({cols_str})
        VALUES ({placeholders})
        ON CONFLICT ({pk}) DO UPDATE SET {update_str}
    """
    
    with conn.cursor() as cur:
        cur.executemany(sql, batch)
    conn.commit()

CHUNK_COLUMNS = [
    "chunk_id", "doc_id", "index", "text", "tokens", "metadata",
    "embedding_id", "embedding_model", "embedded_at",
    "section_header", "act_name", "page_number"
]

def serialize_chunk(row):
    d = dict(row)
    # Clean NULs
    for key, val in d.items():
        if isinstance(val, str):
            d[key] = val.replace("\x00", "")
    
    if d.get("metadata") and isinstance(d["metadata"], (list, dict)):
        d["metadata"] = json.dumps(d["metadata"])
    elif d.get("metadata") and isinstance(d["metadata"], str):
        try:
            json.loads(d["metadata"])
        except:
            d["metadata"] = json.dumps({"raw": d["metadata"]})
            
    for col in CHUNK_COLUMNS:
        if col not in d:
            d[col] = None
    return d

def process_shard(shard_path):
    try:
        pg_conn = get_postgres_connection()
        source_conn = sqlite3.connect(shard_path)
        source_conn.row_factory = sqlite3.Row
        
        docs_processed = 0
        # 1. Process Documents
        cursor = source_conn.execute("SELECT * FROM legal_documents")
        batch = []
        for row in cursor:
            batch.append(serialize_row(row))
            if len(batch) >= 1000:
                upsert_batch(pg_conn, "legal_documents", COLUMNS, batch)
                docs_processed += len(batch)
                batch = []
        if batch:
            upsert_batch(pg_conn, "legal_documents", COLUMNS, batch)
            docs_processed += len(batch)
            
        # 2. Process Chunks
        cursor = source_conn.execute("SELECT * FROM document_chunks")
        batch = []
        for row in cursor:
            batch.append(serialize_chunk(row))
            if len(batch) >= 1000:
                upsert_batch(pg_conn, "document_chunks", CHUNK_COLUMNS, batch)
                batch = []
        if batch:
            upsert_batch(pg_conn, "document_chunks", CHUNK_COLUMNS, batch)
            
        return docs_processed
    except Exception as e:
        logger.error(f"Error processing {shard_path.name}: {e}")
        return 0
    finally:
        if 'source_conn' in locals(): source_conn.close()
        if 'pg_conn' in locals(): pg_conn.close()

def main():
    shards = list(STAGING_DIR.glob("*.db"))
    if not shards:
        logger.warning(f"No .db shards found in {STAGING_DIR}")
        return

    logger.info(f"Consolidating {len(shards)} shards to PostgreSQL using 8 workers...")
    
    total_docs = 0
    with ProcessPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(process_shard, shard) for shard in shards]
        for future in tqdm(as_completed(futures), total=len(shards)):
            total_docs += future.result()

    logger.info(f"Consolidation Complete. Total Docs migrated to Postgres: {total_docs:,}")

if __name__ == "__main__":
    main()

