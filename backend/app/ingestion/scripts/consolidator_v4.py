#!/usr/bin/env python3
import os
import json
import sqlite3
import logging
import argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from tqdm import tqdm
import psycopg
from psycopg.rows import dict_row

# --- Configuration ---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag")
PG_DSN = DATABASE_URL
STAGING_DIR = Path("/home/mohanganesh/project002/data/collection/staging")

# Schema definitions
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

CHUNK_COLUMNS = [
    "chunk_id", "doc_id", "chunk_index", "text", "text_normalized", "section_header", 
    "act_name", "section_number", "court", "citation", "date", "current_validity",
    "doc_type", "total_chunks", "needs_reembedding", "projection_stale",
    "jurisdiction_binding", "jurisdiction_persuasive", "is_in_force",
    "embedding_id", "embedding_model", "embedded_at", "practice_area"
]

JSON_COLUMNS = {
    "bench", "parties", "jurisdiction_binding", "jurisdiction_persuasive",
    "distinguished_by", "followed_by", "statutes_interpreted", "statutes_applied",
    "citations_made", "headnotes", "obiter_dicta", "practice_areas", "practice_area"
}

BOOLEAN_COLUMNS = {"is_ocr", "projection_stale", "needs_reembedding", "is_in_force"}
FK_NULL_COLUMNS = {"ingestion_run_id"}
TRUNCATE_255 = {"court", "citation", "neutral_citation", "source_document_ref", "date_text", "checksum"}

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
    "practice_area": "[]",
    "language": "en",
    "parser_version": "v1",
    "approval_status": "PENDING",
    "projection_stale": False,
    "needs_reembedding": False,
    "total_chunks": 0,
    "is_in_force": True,
    "text_normalized": ""
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("consolidator_v4")

def serialize_row(row, table="legal_documents"):
    d = dict(row)
    
    if table == "document_chunks":
        if "index" in d and "chunk_index" not in d:
            d["chunk_index"] = d["index"]
        if "text_normalized" not in d:
            d["text_normalized"] = d.get("text", "")

    # Clean NUL bytes and Truncate
    for key, val in d.items():
        if isinstance(val, str):
            clean_val = val.replace("\x00", "")
            if key in TRUNCATE_255:
                clean_val = clean_val[:255]
            d[key] = clean_val

    # Cast Boolean
    for col in BOOLEAN_COLUMNS:
        if col in d and d[col] is not None:
            d[col] = bool(d[col])

    # Handle JSON and Defaults
    target_cols = COLUMNS if table == "legal_documents" else CHUNK_COLUMNS
    for col in target_cols:
        val = d.get(col)
        
        if val is None and col in DEFAULT_VALUES:
            d[col] = DEFAULT_VALUES[col]
            val = d[col]

        if col in JSON_COLUMNS:
            if val is None:
                d[col] = DEFAULT_VALUES.get(col, "[]")
            elif isinstance(val, (list, dict)):
                d[col] = json.dumps(val)
            elif isinstance(val, str):
                try:
                    json.loads(val)
                except:
                    d[col] = json.dumps([val])

    if table == "legal_documents":
        for col in FK_NULL_COLUMNS:
            d[col] = None

    final_dict = {}
    for col in target_cols:
        final_dict[col] = d.get(col)
        
    return final_dict

def upsert_batch(cur, table, columns, batch):
    cols_str = ", ".join(columns)
    placeholders = ", ".join([f"%({c})s" for c in columns])
    pk = "doc_id" if table == "legal_documents" else "chunk_id"
    update_str = ", ".join([f"{c} = EXCLUDED.{c}" for c in columns if c != pk])
    
    sql = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) ON CONFLICT ({pk}) DO UPDATE SET {update_str}"
    cur.executemany(sql, batch)

def seed_source_registry(conn, source_key):
    if not source_key: return
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO source_registries (
                source_key, display_name, source_type, jurisdiction_scope, 
                is_public, is_active, approval_status, critical, created_at, updated_at
            )
            VALUES (%s, %s, 'judgment', '[]', true, true, 'APPROVED', false, NOW(), NOW())
            ON CONFLICT (source_key) DO NOTHING
            """,
            (source_key, source_key.replace("_", " ").title())
        )
    conn.commit()

def process_shard(shard_path):
    try:
        pg_conn = psycopg.connect(PG_DSN, row_factory=dict_row)
        # --- Turbo Mode: async commits (valid session param) ---
        with pg_conn.cursor() as cur:
            cur.execute("SET synchronous_commit = off")
        # ------------------
        src = sqlite3.connect(shard_path)
        src.row_factory = sqlite3.Row
        
        unique_sources = [r[0] for r in src.execute("SELECT DISTINCT source_system FROM legal_documents WHERE source_system IS NOT NULL").fetchall()]
        for s in unique_sources:
            seed_source_registry(pg_conn, s)
            
        with pg_conn.cursor() as cur:
            # 1. Documents
            cursor = src.execute("SELECT * FROM legal_documents")
            batch = []
            for row in cursor:
                batch.append(serialize_row(row, "legal_documents"))
                if len(batch) >= 500:
                    upsert_batch(cur, "legal_documents", COLUMNS, batch)
                    batch = []
            if batch: upsert_batch(cur, "legal_documents", COLUMNS, batch)
            
            # 2. Chunks
            cursor = src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='document_chunks'")
            if cursor.fetchone():
                cursor = src.execute("SELECT * FROM document_chunks")
                batch = []
                for row in cursor:
                    batch.append(serialize_row(row, "document_chunks"))
                    if len(batch) >= 500:
                        upsert_batch(cur, "document_chunks", CHUNK_COLUMNS, batch)
                        batch = []
                if batch: upsert_batch(cur, "document_chunks", CHUNK_COLUMNS, batch)
            
        pg_conn.commit()
        pg_conn.close()
        src.close()
        return 1
    except Exception as e:
        logger.error(f"Error processing {shard_path.name}: {e}")
        return 0

def main():
    shards = list(STAGING_DIR.glob("*.db"))
    logger.info(f"Consolidator v4.3 starting: {len(shards)} shards...")
    
    with ProcessPoolExecutor(max_workers=44) as executor:
        futures = [executor.submit(process_shard, s) for s in shards]
        for _ in tqdm(as_completed(futures), total=len(shards)):
            pass
            
    logger.info("Consolidation v4.3 complete.")

if __name__ == "__main__":
    main()
