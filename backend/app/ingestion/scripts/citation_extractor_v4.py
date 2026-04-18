#!/usr/bin/env python3
"""
NyayaRAG Citation Extractor v4 - Hyper Scale (Memory Optimized)
==============================================================
"""
import os, re, hashlib, json, time, logging, multiprocessing as mp
import psycopg
from psycopg.rows import dict_row

# ── Config ────────────────────────────────────────────────────────────────────
DB_DSN = "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag"
WORKERS = 48 # Increased for 2026 CPU power
BATCH_SIZE = 1000

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(processName)s] %(message)s")
logger = logging.getLogger("sentinel_v4")

REPORTER_PATTERNS = [
    re.compile(r'(\d{4})\s*(?:\(\d\)\s*)?([A-Z]{2,})\s*(\d+)'),
    re.compile(r'([A-Z]{2,})\s*(\d{4})\s*(?:SC|HC)?\s*(\d+)'),
    re.compile(r'\((\d{4})\)\s*(\d+)\s*([A-Z]{2,})\s*(\d+)'),
]

CASE_NUMBER_PATTERNS = [
    re.compile(r'(?:W\.?P\.?|CRL\.?\s*A|C\.?A\.?|S\.?L\.?P\.?)\s*(?:No\.?)?\s*\d+\s*(?:of\s*)?\d{4}', re.IGNORECASE),
    re.compile(r'(?:MPHC|WBCH)[A-Z0-9]+', re.IGNORECASE),
]

def normalize_citation(cit: str) -> str:
    return re.sub(r'[\s\.\(\)/,]', '', cit).upper()

# ── Shared Lookup ─────────────────────────────────────────────────────────────
LOOKUP = {}

def init_worker(shared_lookup):
    global LOOKUP
    LOOKUP = shared_lookup

def worker_task(chunk_batch):
    edges = []
    for row in chunk_batch:
        text = row['text'] or ""
        found = set()
        
        # Combined regex for speed
        for p in REPORTER_PATTERNS + CASE_NUMBER_PATTERNS:
            for match in p.finditer(text):
                norm = normalize_citation(match.group(0))
                if norm in LOOKUP:
                    found.add(LOOKUP[norm])
                    
        for target_id in found:
            if target_id != row['doc_id']:
                edges.append((row['doc_id'], target_id, 'cites'))
    return edges

# ── Main ──────────────────────────────────────────────────────────────────────

def main_orchestrator():
    logger.info("Loading Citation Lookup into memory...")
    pg = psycopg.connect(DB_DSN)
    cur = pg.cursor()
    cur.execute("SELECT citation_normalized, doc_id FROM citation_lookup")
    lookup = {row[0]: row[1] for row in cur.fetchall()}
    cur.close(); pg.close()
    logger.info(f"Loaded {len(lookup):,} identifiers.")

    # Using Manager().dict() or just passing it to initializer
    # For large read-only dicts, initializer is best
    pool = mp.Pool(processes=WORKERS, initializer=init_worker, initargs=(lookup,))
    logger.info(f"Initialized {WORKERS} workers with shared lookup.")

    pg = psycopg.connect(DB_DSN, row_factory=dict_row)
    cur = pg.cursor()
    cur.execute("SELECT chunk_id, doc_id, text FROM document_chunks ORDER BY chunk_id")
    
    insert_pg = psycopg.connect(DB_DSN)
    ins_cur = insert_pg.cursor()
    
    total_edges = 0
    processed_docs = 0
    t0 = time.time()
    
    while True:
        rows = cur.fetchmany(20000)
        if not rows: break
        
        # Batch items for workers
        sub_batches = [rows[i:i+500] for i in range(0, len(rows), 500)]
        results = pool.map(worker_task, sub_batches)
        
        edge_batch = [edge for sublist in results for edge in sublist]
        if edge_batch:
            ins_cur.executemany(
                "INSERT INTO citation_edges (source_doc_id, target_doc_id, citation_type) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                edge_batch
            )
            insert_pg.commit()
            total_edges += len(edge_batch)
            
        processed_docs += len(rows)
        elapsed = time.time() - t0
        rate = total_edges / elapsed if elapsed > 0 else 0
        doc_rate = processed_docs / elapsed if elapsed > 0 else 0
        print(f"Docs: {processed_docs:,} | Edges: {total_edges:,} | Rate: {doc_rate:.1f} docs/s | Elapsed: {elapsed/60:.1f}m", flush=True)

if __name__ == "__main__":
    main_orchestrator()
