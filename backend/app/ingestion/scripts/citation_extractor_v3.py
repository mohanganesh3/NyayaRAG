#!/usr/bin/env python3
"""
NyayaRAG Citation Graph - Gold Standard Bulk Extractor v3
Fully self-contained: no app/* imports. Uses psycopg directly.
Fixes all 7 bugs from the citation graph diagnosis.
"""
import re
import uuid
import logging
import multiprocessing as mp
import psycopg
from psycopg.rows import dict_row

# ── Inline normalize_citation (no app imports needed) ────────────────────────
def normalize_citation(text: str) -> str:
    return re.sub(r'\s+', ' ', text.lower().strip())

# ── Inline StrictCitationSentinel ────────────────────────────────────────────
class StrictCitationSentinel:
    PATTERNS = [
        ('SCC',         re.compile(r'[\(\[]?\d{4}[\)\]]?\s*\d*\s*SCC\s*\d+', re.IGNORECASE)),
        ('AIR',         re.compile(r'AIR[\s\n]+\d{4}[\s\n]+(?:SC|Mad|Bom|Del|Cal|Guj|Kar|Ker|MP|Ori|Pat|P&H|Raj|All|Gau|HP|J&K|Jhar|AP|TS)\s+\d+', re.IGNORECASE)),
        ('SCR',         re.compile(r'[\(\[]?\d{4}[\)\]]?\s*\d*\s*S\.?C\.?R\.?\s*\d+', re.IGNORECASE)),
        ('SCALE',       re.compile(r'[\(\[]?\d{4}[\)\]]?\s*\d*\s*SCALE\s*\d+', re.IGNORECASE)),
        ('JT',          re.compile(r'[\(\[]?\d{4}[\)\]]?\s*\d*\s*JT\s*\d+', re.IGNORECASE)),
        ('ILR',         re.compile(r'ILR[\s\n]+\d{4}[\s\n]+(?:Delhi|Bombay|Madras|Calcutta|Allahabad|Rajasthan|Karnataka|Kerala|Punjab|Patna)\s+\d+', re.IGNORECASE)),
        ('Neutral_SC',  re.compile(r'\d{4}[\s:]+INSC[\s:]+\d+', re.IGNORECASE)),
        ('Neutral_HC',  re.compile(r'\d{4}:(?:DHC|MHC|BHC|CHC|GHC|KHC|MPHC|OHC|PHC|RHC|AHC|TNHC|TSHC|APHC|UCHC):\d+', re.IGNORECASE)),
        ('SCC_Online',  re.compile(r'\d{4}\s+SCC\s+OnLine\s+(?:SC|Mad|Bom|Del|Cal|Guj|Kar|Ker|MP|All)\s+\d+', re.IGNORECASE)),
        ('MANU',        re.compile(r'MANU/(?:SC|HC|[A-Z]{2})/\d{3,6}/\d{4}', re.IGNORECASE)),
    ]
    REL_MARKERS = [
        ('overrules',    re.compile(r'\boverruled?\b|\breversed?\b', re.IGNORECASE)),
        ('distinguishes',re.compile(r'\bdistinguished?\b', re.IGNORECASE)),
        ('follows',      re.compile(r'\bfollowed?\b|\brelied\s+on\b|\bapplied\b', re.IGNORECASE)),
        ('approves',     re.compile(r'\bapproved?\b', re.IGNORECASE)),
        ('disapproves',  re.compile(r'\bdisapproved?\b', re.IGNORECASE)),
        ('explains',     re.compile(r'\bexplained?\b|\bclarified?\b', re.IGNORECASE)),
        ('affirms',      re.compile(r'\baffirmed?\b', re.IGNORECASE)),
    ]
    def extract_all(self, text: str):
        seen, results = set(), []
        matches = []
        for journal, pat in self.PATTERNS:
            for m in pat.finditer(text):
                matches.append((m.start(), m.end(), m.group()))
        matches.sort()
        for start, end, raw in matches:
            norm = normalize_citation(raw)
            if norm in seen or not norm: continue
            seen.add(norm)
            pre = text[max(0, start-150):start]
            ctype = 'refers_to'
            for rel, rpat in self.REL_MARKERS:
                if rpat.search(pre): ctype = rel; break
            results.append({'citation_text': norm, 'citation_type': ctype})
        return results

POSTGRES_DSN = "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag"
CHUNK_BATCH_SIZE = 500        # Chunks per task batch
UPSERT_BATCH_SIZE = 5000      # Edges per DB commit
NUM_WORKERS = 10              # CPU workers (leaves 38 for Vectorizer + OS)
LOG_FILE = "citation_saturation_v3.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(processName)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ── Canonical Resolver ───────────────────────────────────────────────────────

def resolve_canonical(cur, citation_normalized: str) -> str:
    """
    Gold-Standard resolver using the citation_lookup table.
    Prefers is_canonical=TRUE rows. If still ambiguous, uses court hint.
    Never guesses. Returns doc_id or None.
    """
    cur.execute(
        """SELECT doc_id, court, is_canonical
           FROM citation_lookup
           WHERE citation_normalized = %s
           ORDER BY is_canonical DESC""",
        (citation_normalized,)
    )
    rows = cur.fetchall()

    if not rows:
        return None

    # Unambiguous: only one entry
    if len(rows) == 1:
        return rows[0][0]

    # Prefer canonical entries
    canonical = [r for r in rows if r[2]]  # is_canonical = True
    if len(canonical) == 1:
        return canonical[0][0]

    # Multiple canonicals: use journal-based court disambiguation
    court_hint = _journal_to_court_class(citation_normalized)
    if court_hint:
        court_matches = [r for r in canonical if court_hint in (r[1] or '').lower()]
        if len(court_matches) == 1:
            return court_matches[0][0]

    return None  # Zero-mistake mandate: abort if ambiguous


def _journal_to_court_class(citation: str) -> str:
    c = citation.lower()
    if 'scc' in c or 'scr' in c or 'insc' in c or ('air' in c and 'sc' in c and 'mad' not in c):
        return 'supreme court'
    if 'air mad' in c or 'tnhc' in c or 'mhc' in c:
        return 'madras'
    if 'air bom' in c or 'bhc' in c:
        return 'bombay'
    if 'air del' in c or 'dhc' in c:
        return 'delhi'
    if 'air cal' in c or 'chc' in c:
        return 'calcutta'
    if 'air all' in c or 'ahc' in c:
        return 'allahabad'
    return None


# ── Flush Edges ──────────────────────────────────────────────────────────────

def _flush_edges(conn, edges: list):
    if not edges:
        return
    rows = []
    for e in edges:
        edge_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{e['source']}|{e['target']}|{e['type']}"
        ))
        rows.append((edge_id, e['source'], e['target'], e['type']))

    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO citation_edges (id, source_doc_id, target_doc_id, citation_type)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT ON CONSTRAINT uq_citation_edges_source_target_type DO NOTHING""",
            rows
        )
    conn.commit()


# ── Worker ───────────────────────────────────────────────────────────────────

def process_worker(worker_id: int, task_queue: mp.Queue, stats_queue: mp.Queue):
    sentinel = StrictCitationSentinel()
    conn = psycopg.connect(POSTGRES_DSN)
    lookup_cur = conn.cursor()

    logger.info(f"Worker {worker_id} ready.")

    edges_buffer = []
    processed_chunks = 0
    edges_created = 0

    try:
        while True:
            batch = task_queue.get()
            if batch is None:
                break

            for row in batch:
                chunk_id = row['chunk_id']
                doc_id = row['doc_id']
                chunk_text = row['text'] or ''
                doc_cit_norm = normalize_citation(row['doc_cit'] or '')
                doc_neut_norm = normalize_citation(row['doc_neut'] or '')

                candidates = sentinel.extract_all(chunk_text)

                for cand in candidates:
                    norm = cand['citation_text']  # dict from sentinel

                    # Self-citation guard
                    if norm == doc_cit_norm or norm == doc_neut_norm:
                        continue
                    if not norm:
                        continue

                    target_doc_id = resolve_canonical(lookup_cur, norm)
                    if target_doc_id and target_doc_id != doc_id:
                        edges_buffer.append({
                            'source': doc_id,
                            'target': target_doc_id,
                            'type': cand['citation_type']
                        })
                        edges_created += 1

                processed_chunks += 1

            # Flush when buffer is large enough
            if len(edges_buffer) >= UPSERT_BATCH_SIZE:
                _flush_edges(conn, edges_buffer)
                edges_buffer = []

            stats_queue.put(('chunks', len(batch)))

            if processed_chunks % 5000 == 0 and processed_chunks > 0:
                logger.info(
                    f"Worker {worker_id}: {processed_chunks:,} chunks, "
                    f"{edges_created:,} edges created"
                )

        # Final flush
        if edges_buffer:
            _flush_edges(conn, edges_buffer)

        logger.info(
            f"Worker {worker_id} DONE: {processed_chunks:,} chunks, "
            f"{edges_created:,} edges total"
        )

    except Exception as e:
        logger.error(f"Worker {worker_id} CRASHED: {e}", exc_info=True)
    finally:
        lookup_cur.close()
        conn.close()


# ── Monitor ──────────────────────────────────────────────────────────────────

def monitor_worker(stats_queue: mp.Queue, total_chunks: int):
    import time
    chunks_done = 0
    t0 = time.time()
    while True:
        msg = stats_queue.get()
        if msg is None:
            break
        key, val = msg
        if key == 'chunks':
            chunks_done += val
        elapsed = time.time() - t0
        rate = chunks_done / elapsed if elapsed > 0 else 0
        remaining = (total_chunks - chunks_done) / rate / 3600 if rate > 0 else 0
        if chunks_done % 100000 == 0 and chunks_done > 0:
            logger.info(
                f"PROGRESS: {chunks_done:,}/{total_chunks:,} chunks "
                f"({chunks_done/total_chunks*100:.1f}%) | "
                f"{rate:.0f}/sec | ~{remaining:.1f}h remaining"
            )


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    logger.info("=== NyayaRAG Citation Extractor v3 - GOLD STANDARD ===")

    # Use reltuples for fast approximate count (avoids full scan of 177M rows)
    with psycopg.connect(POSTGRES_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT reltuples::BIGINT FROM pg_class WHERE relname = 'document_chunks'")
            total_chunks = cur.fetchone()[0]
    logger.info(f"Total chunks to process (approx): {total_chunks:,}")

    # Check citation_lookup is ready
    with psycopg.connect(POSTGRES_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM citation_lookup WHERE is_canonical = TRUE")
            canonical_count = cur.fetchone()[0]
    if canonical_count == 0:
        logger.error("citation_lookup is empty! Run citation_gold_migration.py first.")
        return
    logger.info(f"Canonical citation entries available: {canonical_count:,}")

    task_queue = mp.Queue(maxsize=200)
    stats_queue = mp.Queue()

    # Start workers
    workers = []
    for i in range(NUM_WORKERS):
        p = mp.Process(
            target=process_worker,
            args=(i, task_queue, stats_queue),
            name=f"CitWorker-{i}"
        )
        p.start()
        workers.append(p)

    # Start monitor
    monitor = mp.Process(
        target=monitor_worker,
        args=(stats_queue, total_chunks),
        name="Monitor"
    )
    monitor.start()

    # Master Fetcher: single server-side cursor streams all chunks
    logger.info("Master Fetcher: streaming chunks from Postgres...")
    try:
        with psycopg.connect(POSTGRES_DSN, row_factory=dict_row) as conn:
            with conn.cursor(name="master_citation_v3") as cur:
                cur.execute("""
                    SELECT
                        c.chunk_id,
                        c.doc_id,
                        c.text,
                        d.citation      AS doc_cit,
                        d.neutral_citation AS doc_neut
                    FROM document_chunks c
                    JOIN legal_documents d ON c.doc_id = d.doc_id
                """)
                while True:
                    rows = cur.fetchmany(CHUNK_BATCH_SIZE)
                    if not rows:
                        break
                    task_queue.put(rows)

        logger.info("Master Fetcher done. Sending stop signals...")
    except Exception as e:
        logger.error(f"Master Fetcher error: {e}", exc_info=True)
    finally:
        for _ in range(NUM_WORKERS):
            task_queue.put(None)

    for p in workers:
        p.join()

    stats_queue.put(None)
    monitor.join()

    # Final count
    with psycopg.connect(POSTGRES_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM citation_edges")
            total_edges = cur.fetchone()[0]

    logger.info(f"=== COMPLETE: {total_edges:,} total citation edges in graph ===")


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    main()
