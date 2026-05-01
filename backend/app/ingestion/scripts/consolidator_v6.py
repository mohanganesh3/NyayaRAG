#!/usr/bin/env python3
import sqlite3
import psycopg
from psycopg.rows import dict_row
import logging
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm
import json
from datetime import datetime, timezone
import uuid

# Configuration
STAGING_DIR = Path("/home/mohanganesh/project002/data/collection/staging")
PG_DSN = "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag"
MAX_WORKERS = 44
BATCH_SIZE = 2500

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("consolidator_v6")

DOC_COLUMNS = [
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
    "chunk_id", "doc_id", "doc_type", "text", "text_normalized", "chunk_index",
    "total_chunks", "section_header", "court", "date", "citation",
    "jurisdiction_binding", "jurisdiction_persuasive", "current_validity",
    "practice_area", "act_name", "section_number", "is_in_force", "amendment_date",
    "embedding_id", "embedding_model", "embedding_version", "vector_collection",
    "embedded_at", "last_validated_at", "needs_reembedding", "projection_stale", "stale_reason"
]

BOOL_FIELDS = ["projection_stale", "is_ocr", "needs_reembedding", "is_in_force"]

MAX_LENGTHS = {
    # 1000 chars
    "title": 1000, "source_url": 1000, "seed_url": 1000, "detail_url": 1000, "artifact_url": 1000, "stale_reason": 1000,
    # 500 chars
    "section_header": 500,
    # 255 chars
    "court": 255, "citation": 255, "neutral_citation": 255, "date_text": 255, "source_document_ref": 255,
    "source_surface": 255, "mime_type": 255, "checksum": 255, "act_name": 255, "embedding_id": 255,
    "source_system": 255,
    # 100 chars
    "provenance_tier": 100, "embedding_model": 100, "embedding_version": 100, "vector_collection": 100,
    # 50 chars
    "parser_version": 50, "section_number": 50,
    # 36 chars
    "doc_id": 36, "chunk_id": 36, "overruled_by": 36, "collector_run_id": 36, "ingestion_run_id": 36,
    # 20 chars
    "language": 20
}

DOC_JSON = ["bench", "parties", "jurisdiction_binding", "jurisdiction_persuasive", "distinguished_by", "followed_by", "statutes_interpreted", "statutes_applied", "citations_made", "headnotes", "obiter_dicta", "practice_areas"]
CHUNK_JSON = ["jurisdiction_binding", "jurisdiction_persuasive", "practice_area"]

def serialize_row(row, table_name, cols):
    row_dict = dict(row)
    d = {}
    MAPPING = {"full_text": "text", "practice_areas": "practice_area"}

    for col in cols:
        sqlite_key = MAPPING.get(col, col)
        val = row_dict.get(sqlite_key, None)
        if col in BOOL_FIELDS and val is not None: d[col] = bool(val)
        elif col == "coram":
            try: d[col] = int(val) if val else None
            except: d[col] = None
        elif isinstance(val, str):
            clean_str = val.replace('\x00', "")
            if col in MAX_LENGTHS: d[col] = clean_str[:MAX_LENGTHS[col]]
            else: d[col] = clean_str
        else: d[col] = val

    now = datetime.now(timezone.utc)

    if table_name == "legal_documents":
        if not d.get("doc_id"): d["doc_id"] = str(uuid.uuid4())
        for field in DOC_JSON:
            val = d.get(field)
            if val is None or val == "": d[field] = json.dumps({} if field == "parties" else [])
            elif isinstance(val, str):
                try: d[field] = json.dumps(json.loads(val))
                except: d[field] = json.dumps([val])
            else: d[field] = json.dumps(val)
        
        if not d.get("doc_type"): d["doc_type"] = "JUDGMENT"
        if not d.get("current_validity"): d["current_validity"] = "GOOD_LAW"
        if not d.get("language"): d["language"] = "en"
        if not d.get("parser_version"): d["parser_version"] = "v1"
        if not d.get("approval_status"): d["approval_status"] = "APPROVED"
        if d.get("projection_stale") is None: d["projection_stale"] = False
        if d.get("is_ocr") is None: d["is_ocr"] = False
        if d.get("ocr_confidence") is None: d["ocr_confidence"] = 0.0
        if d.get("fetched_at") is None: d["fetched_at"] = now
        
        if isinstance(d.get("doc_type"), str): d["doc_type"] = d["doc_type"][:50]
        if isinstance(d.get("current_validity"), str): d["current_validity"] = d["current_validity"][:50]
        if isinstance(d.get("approval_status"), str): d["approval_status"] = d["approval_status"][:50]

    elif table_name == "document_chunks":
        if not d.get("chunk_id"): d["chunk_id"] = str(uuid.uuid4())
        for field in CHUNK_JSON:
            val = d.get(field)
            if val is None or val == "": d[field] = json.dumps([])
            elif isinstance(val, str):
                try: d[field] = json.dumps(json.loads(val))
                except: d[field] = json.dumps([val])
            else: d[field] = json.dumps(val)

        if not d.get("doc_type"): d["doc_type"] = "JUDGMENT"
        if not d.get("current_validity"): d["current_validity"] = "GOOD_LAW"
        if d.get("chunk_index") is None: d["chunk_index"] = 0
        if d.get("total_chunks") is None: d["total_chunks"] = 1
        if d.get("needs_reembedding") is None: d["needs_reembedding"] = False
        if d.get("projection_stale") is None: d["projection_stale"] = False
        if not d.get("text"): d["text"] = d.get("text_normalized", "ERROR_EMPTY_TEXT")
        
        if isinstance(d.get("doc_type"), str): d["doc_type"] = d["doc_type"][:50]
        if isinstance(d.get("current_validity"), str): d["current_validity"] = d["current_validity"][:50]

    return d

def upsert_batch(cur, table, cols, batch):
    col_names = ", ".join(cols)
    placeholders = ", ".join([f"%({c})s" for c in cols])
    updates = ", ".join([f"{c} = EXCLUDED.{c}" for c in cols if c not in ["doc_id", "chunk_id", "chunk_index"]])
    
    # Composite key for chunks to handle resumes correctly
    conflict_target = "doc_id" if table == "legal_documents" else "doc_id, chunk_index"
    query = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) ON CONFLICT ({conflict_target}) DO UPDATE SET {updates}"
    cur.executemany(query, batch)

def process_shard(shard_path):
    try:
        pg_conn = psycopg.connect(PG_DSN, row_factory=dict_row, autocommit=False)
        with pg_conn.cursor() as cur: cur.execute("SET synchronous_commit = off")
        src = sqlite3.connect(shard_path); src.row_factory = sqlite3.Row
        tables = [t[0] for t in src.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        
        for table in ["legal_documents", "document_chunks"]:
            if table in tables:
                cursor = src.execute(f"SELECT * FROM {table}")
                batch = []
                cols = DOC_COLUMNS if table == "legal_documents" else CHUNK_COLUMNS
                for row in cursor:
                    batch.append(serialize_row(row, table, cols))
                    if len(batch) >= BATCH_SIZE:
                        with pg_conn.cursor() as cur: upsert_batch(cur, table, cols, batch)
                        pg_conn.commit(); batch = []
                if batch:
                    with pg_conn.cursor() as cur: upsert_batch(cur, table, cols, batch)
                    pg_conn.commit()
        pg_conn.close(); src.close(); return 1
    except Exception as e:
        logger.error(f"Error processing {shard_path.name}: {e}"); return 0

def main():
    shards = list(STAGING_DIR.glob("*.db"))
    logger.info(f"🚀 IGNITING CONSOLIDATOR v6.6 (Resume-Safe Engine)")
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_shard, s): s for s in shards}
        for future in tqdm(as_completed(futures), total=len(shards), desc="Migrating"):
            try: future.result()
            except Exception as e: logger.error(f"Shard failed: {e}")

if __name__ == "__main__": main()
