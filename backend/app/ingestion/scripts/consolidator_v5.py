#!/usr/bin/env python3
import sqlite3
import psycopg
from psycopg.rows import dict_row
import logging
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm
import json
from datetime import datetime

# Configuration
STAGING_DIR = Path("/home/mohanganesh/project002/data/collection/staging")
PG_DSN = "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag"
MAX_WORKERS = 44
BATCH_SIZE = 2500

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("consolidator_v5")

COLUMNS = [
    "doc_id", "doc_type", "court", "bench", "coram", "date", "citation",
    "neutral_citation", "parties", "jurisdiction_binding", "jurisdiction_persuasive",
    "current_validity", "overruled_by", "overruled_date", "distinguished_by",
    "followed_by", "statutes_interpreted", "statutes_applied", "citations_made",
    "headnotes", "ratio_decidendi", "obiter_dicta", "practice_areas", "language",
    "full_text", "source_system", "title", "date_text", "decision_date",
    "publication_date", "source_url", "source_document_ref", "collector_run_id",
    "seed_url", "detail_url", "parser_version", "approval_status", "projection_stale"
]

CHUNK_COLUMNS = ["chunk_id", "doc_id", "chunk_index", "text", "text_normalized", "section_header", "section_number"]

def serialize_row(row, table_name, cols):
    row_dict = dict(row)
    d = {}
    
    # Mapping for common name mismatches
    MAPPING = {
        "full_text": "text",
        "practice_areas": "practice_area"
    }

    # Ensure every target column exists in the dict, default to None if missing in SQLite
    for col in cols:
        # Check if we should map from a different sqlite column name
        sqlite_key = MAPPING.get(col, col)
        d[col] = row_dict.get(sqlite_key, None)

    if table_name == "legal_documents":
        # Handle JSON fields - ensure they are dumped to strings and NEVER null for constrained columns
        JSON_FIELDS = ["citations_made", "metadata", "jurisdiction_binding", "jurisdiction_persuasive", "practice_areas", "parties", "headnotes", "obiter_dicta", "statutes_interpreted", "statutes_applied", "bench"]
        for field in JSON_FIELDS:
            val = d.get(field)
            if val is not None:
                if isinstance(val, str):
                    try:
                        clean_val = val.replace('\x00', "")
                        parsed = json.loads(clean_val)
                        d[field] = json.dumps(parsed)
                    except:
                        d[field] = json.dumps([val.replace('\x00', "")])
                else:
                    d[field] = json.dumps(val)
            else:
                # MANDATORY: Satisfy NOT NULL constraints with empty defaults
                if field == "parties":
                    d[field] = json.dumps({})
                else:
                    d[field] = json.dumps([])
        
        # Mandatory System Defaults
        if d.get("language") is None: d["language"] = "en"
        if d.get("parser_version") is None: d["parser_version"] = "v1"
        if d.get("approval_status") is None: d["approval_status"] = "APPROVED"
        if d.get("projection_stale") is None: d["projection_stale"] = False
    
    # Scrub NUL bytes from all text to prevent Postgres encoding errors
    for k, v in d.items():
        if isinstance(v, str):
            d[k] = v.replace('\x00', "")
    return d

def upsert_batch(cur, table, cols, batch):
    col_names = ", ".join(cols)
    placeholders = ", ".join([f"%({c})s" for c in cols])
    updates = ", ".join([f"{c} = EXCLUDED.{c}" for c in cols if c != "doc_id" and c != "chunk_id"])
    
    conflict_key = "doc_id" if table == "legal_documents" else "chunk_id"
    
    query = f"""
    INSERT INTO {table} ({col_names})
    VALUES ({placeholders})
    ON CONFLICT ({conflict_key}) DO UPDATE SET {updates}
    """
    cur.executemany(query, batch)

def process_shard(shard_path):
    try:
        pg_conn = psycopg.connect(PG_DSN, row_factory=dict_row, autocommit=False)
        # Enable Async Commits for 5x performance boost
        with pg_conn.cursor() as cur:
            cur.execute("SET synchronous_commit = off")
        
        src = sqlite3.connect(shard_path)
        src.row_factory = sqlite3.Row
        
        # 1. Documents
        cursor = src.execute("SELECT * FROM legal_documents")
        batch = []
        for row in cursor:
            batch.append(serialize_row(row, "legal_documents", COLUMNS))
            if len(batch) >= BATCH_SIZE:
                with pg_conn.cursor() as cur:
                    upsert_batch(cur, "legal_documents", COLUMNS, batch)
                pg_conn.commit() # IMMEDIATE COMMIT
                batch = []
        if batch:
            with pg_conn.cursor() as cur:
                upsert_batch(cur, "legal_documents", COLUMNS, batch)
            pg_conn.commit()

        # 2. Chunks
        cursor = src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='document_chunks'")
        if cursor.fetchone():
            cursor = src.execute("SELECT * FROM document_chunks")
            batch = []
            for row in cursor:
                batch.append(serialize_row(row, "document_chunks", CHUNK_COLUMNS))
                if len(batch) >= BATCH_SIZE:
                    with pg_conn.cursor() as cur:
                        upsert_batch(cur, "document_chunks", CHUNK_COLUMNS, batch)
                    pg_conn.commit() # IMMEDIATE COMMIT
                    batch = []
            if batch:
                with pg_conn.cursor() as cur:
                    upsert_batch(cur, "document_chunks", CHUNK_COLUMNS, batch)
                pg_conn.commit()
                
        pg_conn.close()
        src.close()
        return 1
    except Exception as e:
        logger.error(f"Error processing {shard_path.name}: {e}")
        return 0

def main():
    shards = list(STAGING_DIR.glob("*.db"))
    logger.info(f"🚀 IGNITING CONSOLIDATOR v5.0 (Row-Level Commit Mode)")
    logger.info(f"Target: {len(shards)} shards | Workers: {MAX_WORKERS}")
    
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_shard, s): s for s in shards}
        for future in tqdm(as_completed(futures), total=len(shards), desc="Migrating Shards"):
            shard = futures[future]
            try:
                future.result()
            except Exception as e:
                logger.error(f"Shard {shard.name} failed: {e}")

if __name__ == "__main__":
    main()
