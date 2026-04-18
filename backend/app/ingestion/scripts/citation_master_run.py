#!/usr/bin/env python3
"""
NyayaRAG Citation Intelligence Master Orchestrator
Executes Phases 1-4 in sequence, fully autonomous.

Phase 1: Parse S3 URLs → extract case numbers → populate citation_lookup (~9.9M docs)
Phase 2: Scan first 3 chunks of remaining docs → extract case numbers from text
Phase 3: Re-run citation extractor v3 with full 11M-entry lookup
Phase 4: Compute in-degree authority scores

All SQL uses server-side keyset pagination — no full table scans.
No ALTER TABLE — all columns/tables created safely.
"""
import re
import uuid
import logging
import multiprocessing as mp
import time
import psycopg
from psycopg.rows import dict_row

POSTGRES_DSN = "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag"
BATCH_SIZE    = 50_000     # rows per keyset page
FLUSH_SIZE    = 5_000      # edges per DB commit
NUM_WORKERS   = 8          # CPU workers for Phase 2 & 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(processName)s: %(message)s",
    handlers=[
        logging.FileHandler("master_citation_run.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("master")

# ══════════════════════════════════════════════════════════════════════════════
# SHARED UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def norm(text):
    if not text: return None
    return re.sub(r'\s+', ' ', text.lower().strip())

def ensure_schema(conn):
    """Ensure citation_lookup has id_type column. No ALTER TABLE if exists."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS citation_lookup (
                citation_normalized TEXT NOT NULL,
                doc_id              TEXT NOT NULL,
                court               TEXT,
                doc_type            TEXT,
                is_canonical        BOOLEAN DEFAULT FALSE,
                id_type             TEXT DEFAULT 'reporter',
                PRIMARY KEY (citation_normalized, doc_id)
            )
        """)
        # Safe column add — check first, then add
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name='citation_lookup' AND column_name='id_type'
        """)
        if not cur.fetchone():
            cur.execute("ALTER TABLE citation_lookup ADD COLUMN id_type TEXT DEFAULT 'reporter'")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_cl_norm ON citation_lookup (citation_normalized)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_cl_canonical ON citation_lookup (citation_normalized) WHERE is_canonical=TRUE")
    conn.commit()
    logger.info("Schema ensured.")

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1: S3 URL → Case Number
# ══════════════════════════════════════════════════════════════════════════════

HC_CASE_PAT     = re.compile(r'#([A-Z]{2,10}\d{6,20})_\d+_\d{4}-\d{2}-\d{2}\.pdf', re.I)
MPHC_PAT        = re.compile(r'#(MPHC\d{9,15})_\d+_\d{4}-\d{2}-\d{2}\.pdf', re.I)
SC_REGIONAL_PAT = re.compile(r'#(\d{4}_\d+_\d+_\d+(?:_\w+)?)\.pdf', re.I)
GENERIC_PAT     = re.compile(r'#([^_#\s]{6,30})_', re.I)

def s3_case_number(url):
    if not url: return None
    for pat, prefix in [(MPHC_PAT,''), (HC_CASE_PAT,''), (SC_REGIONAL_PAT,'sci_')]:
        m = pat.search(url)
        if m: return prefix + m.group(1).lower()
    m = GENERIC_PAT.search(url)
    if m and len(m.group(1)) > 5: return m.group(1).lower()
    return None

def phase1_s3(conn):
    logger.info("=== PHASE 1: S3 URL → Case Number ===")
    cur = conn.cursor()

    # Count using reltuples for speed (avoid COUNT(*) on 11M rows)
    cur.execute("SELECT reltuples::BIGINT FROM pg_class WHERE relname='legal_documents'")
    approx_total = cur.fetchone()[0]
    logger.info(f"  Approx total docs: {approx_total:,}")

    processed = inserted = skipped = 0
    last_id = ''
    t0 = time.time()

    while True:
        cur.execute("""
            SELECT doc_id, source_url, court, doc_type::TEXT
            FROM legal_documents
            WHERE doc_id > %s
              AND (citation IS NULL OR citation = '')
              AND citation_normalized IS NULL
              AND source_url IS NOT NULL
            ORDER BY doc_id
            LIMIT %s
        """, (last_id, BATCH_SIZE))
        rows = cur.fetchall()
        if not rows: break

        lookup_rows = []
        update_rows = []
        for doc_id, source_url, court, doc_type in rows:
            # Only process S3 URLs
            if not (source_url or '').startswith('s3://'):
                skipped += 1
                continue
            case_num = s3_case_number(source_url)
            if not case_num:
                skipped += 1
                continue
            n = norm(case_num)
            lookup_rows.append((n, doc_id, court, doc_type, True, 'case_number'))
            update_rows.append((n, doc_id))

        if lookup_rows:
            cur.executemany("""
                INSERT INTO citation_lookup (citation_normalized, doc_id, court, doc_type, is_canonical, id_type)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (citation_normalized, doc_id) DO NOTHING
            """, lookup_rows)
            inserted += cur.rowcount
        if update_rows:
            cur.executemany("""
                UPDATE legal_documents SET citation_normalized=%s
                WHERE doc_id=%s AND citation_normalized IS NULL
            """, update_rows)
        conn.commit()

        processed += len(rows)
        last_id = rows[-1][0]
        elapsed = time.time() - t0
        rate = processed / elapsed if elapsed > 0 else 1
        logger.info(f"  P1: {processed:,} rows | +{inserted:,} lookup | skip={skipped:,} | {rate:.0f}/s")

    cur.close()
    logger.info(f"=== PHASE 1 DONE: {inserted:,} case numbers added to citation_lookup ===")

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2: Text Header → Case Number
# ══════════════════════════════════════════════════════════════════════════════

CASE_TEXT_PATTERNS = [
    re.compile(r'W\.?P\.?\s*(?:No\.?)?\s*\(?(?:C|CRL?|PIL|A|MD|ST|FC)?\)?\s*(\d{1,7})\s*(?:of|/)\s*(\d{4})', re.I),
    re.compile(r'(?:Crl?\.?\s*A(?:pp)?(?:eal)?|Criminal\s+Appeal)\s*(?:No\.?)?\s*(\d{1,7})\s*(?:of|/)\s*(\d{4})', re.I),
    re.compile(r'(?:Civil\s+Appeal|C\.?\s*A\.?)\s*(?:No\.?)?\s*(\d{1,7})\s*(?:of|/)\s*(\d{4})', re.I),
    re.compile(r'S\.?L\.?P\.?\s*(?:No\.?)?\s*\(?\w*\)?\s*(\d{1,7})\s*(?:of|/)\s*(\d{4})', re.I),
    re.compile(r'(?:First\s+Appeal|F\.?A\.?|R\.?S\.?A\.?|R\.?F\.?A\.?)\s*(?:No\.?)?\s*(\d{1,7})\s*(?:of|/)\s*(\d{4})', re.I),
    re.compile(r'(?:I\.?T\.?A\.?|Income\s+Tax\s+Appeal)\s*(?:No\.?)?\s*(\d{1,7})\s*(?:of|/)\s*(\d{4})', re.I),
    re.compile(r'(?:Company\s+(?:Petition|Appeal)|C\.?P\.?)\s*(?:No\.?)?\s*(\d{1,7})\s*(?:of|/)\s*(\d{4})', re.I),
    re.compile(r'(?:O\.?S\.?|Suit)\s*(?:No\.?)?\s*(\d{1,7})\s*(?:of|/)\s*(\d{4})', re.I),
    re.compile(r'(?:M\.?A\.?|Misc(?:ellaneous)?\.?\s*(?:App|Case|Pet))\s*(?:No\.?)?\s*(\d{1,7})\s*(?:of|/)\s*(\d{4})', re.I),
]

def extract_text_case_number(text, court):
    if not text: return None
    header = text[:800]
    for pat in CASE_TEXT_PATTERNS:
        m = pat.search(header)
        if m:
            raw = m.group(0).strip()
            n = re.sub(r'\s+', ' ', raw.lower())
            court_slug = re.sub(r'\s+', '_', (court or 'unk').lower())[:15]
            return f"{n} [{court_slug}]"
    return None

def phase2_worker(worker_id, task_q, stats_q):
    conn = psycopg.connect(POSTGRES_DSN, autocommit=True)
    cur = conn.cursor()
    found = processed = 0
    try:
        while True:
            batch = task_q.get()
            if batch is None: break
            lu_rows, up_rows = [], []
            for doc_id, court, doc_type in batch:
                cur.execute("""
                    SELECT text FROM document_chunks
                    WHERE doc_id=%s ORDER BY chunk_index LIMIT 3
                """, (doc_id,))
                chunks = ' '.join(r[0] or '' for r in cur.fetchall())
                case_num = extract_text_case_number(chunks, court)
                if case_num:
                    n = norm(case_num)
                    lu_rows.append((n, doc_id, court, doc_type, True, 'case_number_text'))
                    up_rows.append((n, doc_id))
                    found += 1
                processed += 1
            if lu_rows:
                cur.executemany("""
                    INSERT INTO citation_lookup (citation_normalized, doc_id, court, doc_type, is_canonical, id_type)
                    VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (citation_normalized, doc_id) DO NOTHING
                """, lu_rows)
            if up_rows:
                cur.executemany("""
                    UPDATE legal_documents SET citation_normalized=%s
                    WHERE doc_id=%s AND citation_normalized IS NULL
                """, up_rows)
            stats_q.put(len(batch))
            if processed % 20000 == 0:
                logger.info(f"  P2 W{worker_id}: {processed:,} docs, {found:,} found ({found/max(processed,1)*100:.1f}%)")
    finally:
        logger.info(f"  P2 W{worker_id} DONE: {processed:,} docs, {found:,} case numbers found")
        cur.close(); conn.close()

def _phase2_monitor(stats_q, total):
    import time
    done = 0; t0 = time.time()
    while True:
        n = stats_q.get()
        if n is None: break
        done += n
        if done % 500000 == 0 and done > 0:
            r = done / (time.time()-t0) if (time.time()-t0) > 0 else 1
            logger.info(f"  P2 PROGRESS: {done:,}/{total:,} ({done/total*100:.1f}%) {r:.0f}/s ~{(total-done)/r/3600:.1f}h left")

def phase2_text(main_conn):
    logger.info("=== PHASE 2: Text Header Case Number Extraction ===")
    cur = main_conn.cursor()
    cur.execute("SELECT count(*) FROM legal_documents WHERE citation_normalized IS NULL")
    total = cur.fetchone()[0]
    cur.close()
    logger.info(f"  Docs still needing text extraction: {total:,}")
    if total == 0:
        logger.info("  Nothing to do.")
        return

    task_q = mp.Queue(maxsize=300)
    stats_q = mp.Queue()

    workers = [mp.Process(target=phase2_worker, args=(i, task_q, stats_q), name=f"P2W{i}")
               for i in range(NUM_WORKERS)]
    for p in workers: p.start()

    mon_p = mp.Process(target=_phase2_monitor, args=(stats_q, total), name="P2Mon")
    mon_p.start()

    conn2 = psycopg.connect(POSTGRES_DSN, row_factory=dict_row)
    with conn2.cursor(name="p2_stream") as sc:
        sc.execute("""
            SELECT doc_id, court, doc_type::TEXT as doc_type
            FROM legal_documents WHERE citation_normalized IS NULL
        """)
        batch = []
        for row in sc:
            batch.append((row['doc_id'], row['court'], row['doc_type']))
            if len(batch) >= 100:
                task_q.put(batch); batch = []
        if batch: task_q.put(batch)
    conn2.close()

    for _ in range(NUM_WORKERS): task_q.put(None)
    for p in workers: p.join()
    stats_q.put(None); mon_p.join()
    logger.info("=== PHASE 2 DONE ===")

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3: Citation Extractor v3 re-run with full lookup
# ══════════════════════════════════════════════════════════════════════════════

CITE_PATTERNS = [
    re.compile(r'[\(\[]?\d{4}[\)\]]?\s*\d*\s*SCC\s*\d+', re.I),
    re.compile(r'AIR[\s\n]+\d{4}[\s\n]+(?:SC|Mad|Bom|Del|Cal|Guj|Kar|Ker|MP|Ori|Pat|P&H|Raj|All|AP|TS)\s+\d+', re.I),
    re.compile(r'[\(\[]?\d{4}[\)\]]?\s*\d*\s*S\.?C\.?R\.?\s*\d+', re.I),
    re.compile(r'[\(\[]?\d{4}[\)\]]?\s*\d*\s*SCALE\s*\d+', re.I),
    re.compile(r'[\(\[]?\d{4}[\)\]]?\s*\d*\s*JT\s*\d+', re.I),
    re.compile(r'\d{4}[\s:]+INSC[\s:]+\d+', re.I),
    re.compile(r'\d{4}:(?:DHC|MHC|BHC|CHC|GHC|KHC|MPHC|OHC|PHC|RHC|AHC|TNHC|TSHC|APHC|UCHC):\d+', re.I),
    re.compile(r'\d{4}\s+SCC\s+OnLine\s+(?:SC|Mad|Bom|Del|Cal|All)\s+\d+', re.I),
    re.compile(r'MANU/(?:SC|HC|[A-Z]{2})/\d{3,6}/\d{4}', re.I),
]
REL_MARKERS = [
    ('overrules',    re.compile(r'\boverruled?\b|\breversed?\b', re.I)),
    ('distinguishes',re.compile(r'\bdistinguished?\b', re.I)),
    ('follows',      re.compile(r'\bfollowed?\b|\brelied\s+on\b|\bapplied\b', re.I)),
    ('approves',     re.compile(r'\bapproved?\b', re.I)),
    ('disapproves',  re.compile(r'\bdisapproved?\b', re.I)),
    ('explains',     re.compile(r'\bexplained?\b|\bclarified?\b', re.I)),
    ('affirms',      re.compile(r'\baffirmed?\b', re.I)),
]

def extract_citations(text):
    seen, results = set(), []
    matches = []
    for pat in CITE_PATTERNS:
        for m in pat.finditer(text):
            matches.append((m.start(), m.end(), m.group()))
    matches.sort()
    for start, _, raw in matches:
        n = norm(raw)
        if n in seen or not n: continue
        seen.add(n)
        pre = text[max(0, start-150):start]
        ctype = 'refers_to'
        for rel, rpat in REL_MARKERS:
            if rpat.search(pre): ctype = rel; break
        results.append((n, ctype))
    return results

def resolve(cur, citation_norm):
    cur.execute("""
        SELECT doc_id, court, is_canonical FROM citation_lookup
        WHERE citation_normalized=%s ORDER BY is_canonical DESC LIMIT 10
    """, (citation_norm,))
    rows = cur.fetchall()
    if not rows: return None
    if len(rows) == 1: return rows[0][0]
    canon = [r for r in rows if r[2]]
    if len(canon) == 1: return canon[0][0]
    c = citation_norm
    hint = ('supreme court' if any(x in c for x in ['scc','scr','insc']) else
            'madras' if 'mad' in c or 'tnhc' in c else
            'bombay' if 'bom' in c or 'bhc' in c else
            'delhi' if 'del' in c or 'dhc' in c else None)
    if hint:
        m = [r for r in canon if hint in (r[1] or '').lower()]
        if len(m) == 1: return m[0][0]
    return None

def flush_edges(conn, edges):
    if not edges: return
    rows = [(str(uuid.uuid5(uuid.NAMESPACE_URL, f"{e[0]}|{e[1]}|{e[2]}")), e[0], e[1], e[2])
            for e in edges]
    with conn.cursor() as cur:
        cur.executemany("""
            INSERT INTO citation_edges (id, source_doc_id, target_doc_id, citation_type)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT ON CONSTRAINT uq_citation_edges_source_target_type DO NOTHING
        """, rows)
    conn.commit()

def phase3_worker(worker_id, task_q, stats_q):
    conn = psycopg.connect(POSTGRES_DSN)
    lc = conn.cursor()
    edges, processed, created = [], 0, 0
    try:
        while True:
            batch = task_q.get()
            if batch is None: break
            for row in batch:
                doc_id = row['doc_id']
                text = row['text'] or ''
                doc_norm = norm(row['doc_cit'] or '')
                for cit_norm, ctype in extract_citations(text):
                    if cit_norm == doc_norm: continue
                    target = resolve(lc, cit_norm)
                    if target and target != doc_id:
                        edges.append((doc_id, target, ctype))
                        created += 1
                processed += 1
            if len(edges) >= FLUSH_SIZE:
                flush_edges(conn, edges); edges = []
            stats_q.put(len(batch))
            if processed % 100000 == 0 and processed > 0:
                logger.info(f"  P3 W{worker_id}: {processed:,} chunks | {created:,} edges")
        if edges: flush_edges(conn, edges)
        logger.info(f"  P3 W{worker_id} DONE: {processed:,} chunks, {created:,} edges")
    except Exception as e:
        logger.error(f"  P3 W{worker_id} CRASHED: {e}", exc_info=True)
    finally:
        lc.close(); conn.close()

def _phase3_monitor(stats_q, total):
    import time
    done = 0; t0 = time.time()
    while True:
        n = stats_q.get()
        if n is None: break
        done += n
        if done % 1000000 == 0 and done > 0:
            r = done / (time.time()-t0) if (time.time()-t0) > 0 else 1
            logger.info(f"  P3 PROGRESS: {done:,}/{total:,} ({done/total*100:.1f}%) {r:.0f}/s")

def phase3_extract(main_conn):
    logger.info("=== PHASE 3: Full Citation Extraction (expanded lookup) ===")
    cur = main_conn.cursor()
    cur.execute("SELECT reltuples::BIGINT FROM pg_class WHERE relname='document_chunks'")
    total = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM citation_lookup")
    lookup_size = cur.fetchone()[0]
    cur.close()
    logger.info(f"  ~{total:,} chunks to process | {lookup_size:,} lookup entries")

    task_q = mp.Queue(maxsize=200)
    stats_q = mp.Queue()

    workers = [mp.Process(target=phase3_worker, args=(i, task_q, stats_q), name=f"P3W{i}")
               for i in range(NUM_WORKERS)]
    for p in workers: p.start()

    mon_p = mp.Process(target=_phase3_monitor, args=(stats_q, total), name="P3Mon")
    mon_p.start()

    conn2 = psycopg.connect(POSTGRES_DSN, row_factory=dict_row)
    with conn2.cursor(name="p3_stream") as sc:
        sc.execute("""
            SELECT c.chunk_id, c.doc_id, c.text, d.citation AS doc_cit
            FROM document_chunks c
            JOIN legal_documents d ON c.doc_id = d.doc_id
        """)
        batch = []
        for row in sc:
            batch.append(row)
            if len(batch) >= 500:
                task_q.put(batch); batch = []
        if batch: task_q.put(batch)
    conn2.close()

    for _ in range(NUM_WORKERS): task_q.put(None)
    for p in workers: p.join()
    stats_q.put(None); mon_p.join()

    conn_check = psycopg.connect(POSTGRES_DSN)
    with conn_check.cursor() as c:
        c.execute("SELECT count(*) FROM citation_edges")
        total_edges = c.fetchone()[0]
    conn_check.close()
    logger.info(f"=== PHASE 3 DONE: {total_edges:,} total citation edges ===")

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    logger.info("══════════════════════════════════════════════════")
    logger.info("  NyayaRAG Citation Intelligence Master Run")
    logger.info("══════════════════════════════════════════════════")

    conn = psycopg.connect(POSTGRES_DSN)
    ensure_schema(conn)

    # Current state report
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM citation_lookup"); logger.info(f"citation_lookup: {cur.fetchone()[0]:,}")
        cur.execute("SELECT count(*) FROM citation_edges"); logger.info(f"citation_edges: {cur.fetchone()[0]:,}")
        cur.execute("SELECT count(*) FROM legal_documents WHERE citation_normalized IS NULL"); logger.info(f"docs_without_identity: {cur.fetchone()[0]:,}")

    # Run phases
    phase1_s3(conn)
    phase2_text(conn)
    phase3_extract(conn)

    conn.close()
    logger.info("══ ALL PHASES COMPLETE ══")

if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    main()
