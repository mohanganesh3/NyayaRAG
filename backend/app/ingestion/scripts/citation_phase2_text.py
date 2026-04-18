#!/usr/bin/env python3
"""
Phase 2: Text Case Number Extractor
Scans the first 3 chunks of every document that still has no citation_normalized
after Phase 1. Extracts the document's own case number from its header text.

Indian court judgment headers look like:
  IN THE HIGH COURT OF MADHYA PRADESH AT GWALIOR
  W.P. No. 12345 of 2020
  [or]
  CRIMINAL APPEAL NO. 456/2019
  [or]
  IN THE SUPREME COURT OF INDIA
  Civil Appeal No. 1234 of 2018
"""
import re
import uuid
import psycopg
import logging
import multiprocessing as mp
from psycopg.rows import dict_row

POSTGRES_DSN = "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag"
NUM_WORKERS = 10
BATCH_SIZE  = 200  # docs per task (we read 3 chunks each)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(processName)s: %(message)s",
    handlers=[
        logging.FileHandler("citation_phase2_text.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("phase2_text")


# ── Case Number Patterns ──────────────────────────────────────────────────────
# These are the case number formats used IN THE TEXT of Indian judgments.
# Ordered from most specific to least specific.

CASE_NUMBER_PATTERNS = [
    # Writ Petition variants: W.P., WP, W.P.(C), WP(C), WP(Crl), WPA, WPIL
    re.compile(
        r'W\.?P\.?\s*(?:No\.?|Number)?\s*\(?\s*(?:C|CRL?|PIL|A|MD|ST|Tax|FC|FCA|MT)?\s*\)?\s*'
        r'(\d{1,7})\s*(?:of|/)\s*(\d{4})',
        re.IGNORECASE
    ),
    # Criminal Appeal: Crl.A., Criminal Appeal, CRL.A.
    re.compile(
        r'(?:Crl?\.?\s*A(?:pp?)?(?:eal)?|Criminal\s+Appeal)\s*(?:No\.?)?\s*'
        r'(\d{1,7})\s*(?:of|/)\s*(\d{4})',
        re.IGNORECASE
    ),
    # Civil Appeal: C.A., Civil Appeal
    re.compile(
        r'(?:Civil\s+Appeal|C\.?\s*A\.?)\s*(?:No\.?)?\s*'
        r'(\d{1,7})\s*(?:of|/)\s*(\d{4})',
        re.IGNORECASE
    ),
    # Special Leave Petition: SLP, S.L.P.
    re.compile(
        r'S\.?L\.?P\.?\s*(?:No\.?)?\s*\(?\s*\w+\s*\)?\s*'
        r'(\d{1,7})\s*(?:of|/)\s*(\d{4})',
        re.IGNORECASE
    ),
    # First Appeal: F.A., RSA, RFA
    re.compile(
        r'(?:First\s+Appeal|F\.?A\.?|R\.?(?:S|F)\.?A\.?)\s*(?:No\.?)?\s*'
        r'(\d{1,7})\s*(?:of|/)\s*(\d{4})',
        re.IGNORECASE
    ),
    # Regular Second Appeal: RSA
    re.compile(
        r'R\.?S\.?A\.?\s*(?:No\.?)?\s*(\d{1,7})\s*(?:of|/)\s*(\d{4})',
        re.IGNORECASE
    ),
    # Tax/Income Tax Appeal
    re.compile(
        r'(?:I\.?T\.?A\.?|Income\s+Tax\s+Appeal|Tax\s+(?:Appeal|Case))\s*(?:No\.?)?\s*'
        r'(\d{1,7})\s*(?:of|/)\s*(\d{4})',
        re.IGNORECASE
    ),
    # Company Petition, Company Appeal
    re.compile(
        r'(?:Company\s+(?:Petition|Appeal)|C\.?P\.?)\s*(?:No\.?)?\s*'
        r'(\d{1,7})\s*(?:of|/)\s*(\d{4})',
        re.IGNORECASE
    ),
    # Contempt Petition
    re.compile(
        r'Cont(?:empt)?\.?\s*(?:Petition|Pet\.?|P\.?)?\s*(?:No\.?)?\s*\(?\w*\)?\s*'
        r'(\d{1,7})\s*(?:of|/)\s*(\d{4})',
        re.IGNORECASE
    ),
    # Execution Petition / Miscellaneous Application
    re.compile(
        r'(?:M\.?A\.?|Misc(?:ellaneous)?\.?\s*(?:App?(?:lication)?|Case|Pet(?:ition)?))\s*'
        r'(?:No\.?)?\s*(\d{1,7})\s*(?:of|/)\s*(\d{4})',
        re.IGNORECASE
    ),
    # Suit No.
    re.compile(
        r'(?:O\.?S\.?|Suit|CS)\s*(?:No\.?)?\s*(\d{1,7})\s*(?:of|/)\s*(\d{4})',
        re.IGNORECASE
    ),
    # Arbitration Petition
    re.compile(
        r'(?:Arb(?:itration)?\.?\s*Pet(?:ition)?\.?)\s*(?:No\.?)?\s*'
        r'(\d{1,7})\s*(?:of|/)\s*(\d{4})',
        re.IGNORECASE
    ),
]


def extract_case_number(text: str, court: str) -> str:
    """
    Tries all patterns on text. Returns normalized case number string or None.
    Format: <TYPE> <NUM>/<YEAR> (normalized)
    """
    if not text:
        return None

    # Search only the first 600 chars (header zone)
    header = text[:600]

    for pat in CASE_NUMBER_PATTERNS:
        m = pat.search(header)
        if m:
            # Normalize: extract matched string, collapse whitespace, lowercase
            raw = m.group(0).strip()
            norm = re.sub(r'\s+', ' ', raw.lower())
            # Append court snippet for uniqueness (prevents cross-court collision)
            court_slug = re.sub(r'\s+', '_', (court or 'unknown').lower())[:20]
            return f"{norm} [{court_slug}]"

    return None


def normalize(text: str) -> str:
    if not text:
        return None
    return re.sub(r'\s+', ' ', text.lower().strip())


# ── Worker ────────────────────────────────────────────────────────────────────

def worker(worker_id: int, task_q: mp.Queue, stats_q: mp.Queue):
    conn = psycopg.connect(POSTGRES_DSN, autocommit=True)
    cur = conn.cursor()
    logger.info(f"Worker {worker_id} ready.")

    processed = 0
    found = 0

    try:
        while True:
            batch = task_q.get()
            if batch is None:
                break

            lookup_rows = []
            update_rows = []

            for doc_id, court, doc_type in batch:
                # Fetch first 3 chunks
                cur.execute("""
                    SELECT text FROM document_chunks
                    WHERE doc_id = %s
                    ORDER BY chunk_index
                    LIMIT 3
                """, (doc_id,))
                chunks = cur.fetchall()
                combined_text = ' '.join(r[0] or '' for r in chunks)

                case_num = extract_case_number(combined_text, court)
                if case_num:
                    norm = normalize(case_num)
                    lookup_rows.append((norm, doc_id, court, doc_type, True, 'case_number_text'))
                    update_rows.append((norm, doc_id))
                    found += 1

                processed += 1

            # Bulk insert
            if lookup_rows:
                cur.executemany("""
                    INSERT INTO citation_lookup
                        (citation_normalized, doc_id, court, doc_type, is_canonical, id_type)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (citation_normalized, doc_id) DO NOTHING
                """, lookup_rows)

            if update_rows:
                cur.executemany("""
                    UPDATE legal_documents
                    SET citation_normalized = %s
                    WHERE doc_id = %s AND (citation_normalized IS NULL OR citation_normalized = '')
                """, update_rows)

            stats_q.put(len(batch))

            if processed % 10000 == 0:
                logger.info(f"Worker {worker_id}: {processed:,} docs, {found:,} case numbers found ({found/processed*100:.1f}%)")

    except Exception as e:
        logger.error(f"Worker {worker_id} CRASHED: {e}", exc_info=True)
    finally:
        logger.info(f"Worker {worker_id} DONE: {processed:,} docs, {found:,} found")
        cur.close()
        conn.close()


def monitor(stats_q: mp.Queue, total: int):
    import time
    done = 0
    t0 = time.time()
    while True:
        n = stats_q.get()
        if n is None:
            break
        done += n
        elapsed = time.time() - t0
        rate = done / elapsed if elapsed > 0 else 0
        remaining = (total - done) / rate / 3600 if rate > 0 else 0
        if done % 200000 == 0 and done > 0:
            logger.info(
                f"PROGRESS: {done:,}/{total:,} ({done/total*100:.1f}%) | "
                f"{rate:.0f}/sec | ~{remaining:.1f}h remaining"
            )


def main():
    logger.info("=== Phase 2: Text Case Number Extractor ===")

    conn = psycopg.connect(POSTGRES_DSN)
    cur = conn.cursor()

    # Docs still with no citation_normalized after Phase 1
    cur.execute("""
        SELECT count(*) FROM legal_documents
        WHERE citation_normalized IS NULL
          AND (citation IS NULL OR citation = '')
    """)
    total = cur.fetchone()[0]
    logger.info(f"Docs needing text extraction: {total:,}")

    if total == 0:
        logger.info("Nothing to do — all docs already have citation_normalized.")
        conn.close()
        return

    task_q = mp.Queue(maxsize=500)
    stats_q = mp.Queue()

    workers_list = []
    for i in range(NUM_WORKERS):
        p = mp.Process(target=worker, args=(i, task_q, stats_q), name=f"P2Worker-{i}")
        p.start()
        workers_list.append(p)

    mon = mp.Process(target=monitor, args=(stats_q, total), name="Monitor")
    mon.start()

    # Stream docs to workers
    with conn.cursor(name="p2_stream", row_factory=dict_row) as stream_cur:
        stream_cur.execute("""
            SELECT doc_id, court, doc_type::TEXT as doc_type
            FROM legal_documents
            WHERE citation_normalized IS NULL
              AND (citation IS NULL OR citation = '')
        """)
        batch = []
        for row in stream_cur:
            batch.append((row['doc_id'], row['court'], row['doc_type']))
            if len(batch) >= BATCH_SIZE:
                task_q.put(batch)
                batch = []
        if batch:
            task_q.put(batch)

    conn.close()

    for _ in range(NUM_WORKERS):
        task_q.put(None)
    for p in workers_list:
        p.join()
    stats_q.put(None)
    mon.join()

    # Final stats
    conn2 = psycopg.connect(POSTGRES_DSN)
    cur2 = conn2.cursor()
    cur2.execute("SELECT count(*) FROM citation_lookup")
    total_lookup = cur2.fetchone()[0]
    cur2.execute("SELECT count(*) FROM citation_lookup WHERE id_type = 'case_number_text'")
    text_entries = cur2.fetchone()[0]
    logger.info("=== PHASE 2 COMPLETE ===")
    logger.info(f"  citation_lookup total: {total_lookup:,}")
    logger.info(f"  Text case numbers found: {text_entries:,}")
    conn2.close()


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    main()
