#!/usr/bin/env python3
"""
Phase 1: S3 URL Identity Extractor
Parses S3 source_url filenames to extract court case numbers for all
high_court_aws_bulk and supreme_court_aws_bulk documents that have
no citation field. Populates citation_normalized + citation_lookup.

S3 URL format:
  s3://indian-high-court-judgments/data/tar/year=2020/court=19_16/bench=calcutta_appellate_side/data.tar#WBCHCA0184392020_2_2020-09-08.pdf
  → Case number: WBCHCA0184392020

  s3://indian-supreme-court-judgments/data/tar/year=2014/regional/regional.tar#2014_3_298_321_HIN.pdf
  → Encoded year/vol/page — used as-is

  s3://.../bench=mphc_db_gwl/data.tar#MPHC030091182020_1_2020-06-09.pdf
  → Case number: MPHC030091182020
"""
import re
import psycopg
import logging
import time

POSTGRES_DSN = "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag"
BATCH_SIZE = 100_000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("citation_phase1_s3.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("phase1_s3")

# ── S3 Case Number Extraction ─────────────────────────────────────────────────

# Pattern 1: Standard HC format  WBCHCA0184392020_2_2020-09-08.pdf
# Captures: WBCHCA0184392020
HC_CASE_PATTERN = re.compile(
    r'#([A-Z]{2,10}\d{6,20})_\d+_\d{4}-\d{2}-\d{2}\.pdf$',
    re.IGNORECASE
)

# Pattern 2: SC regional format  2014_3_298_321_HIN.pdf
# These are year_vol_startpage_endpage_lang — use as SCI year/vol/page
SC_REGIONAL_PATTERN = re.compile(
    r'#(\d{4}_\d+_\d+_\d+(?:_\w+)?)\.pdf$',
    re.IGNORECASE
)

# Pattern 3: MPHC format  MPHC030091182020_1_2020-06-09.pdf
MPHC_PATTERN = re.compile(
    r'#(MPHC\d{9,15})_\d+_\d{4}-\d{2}-\d{2}\.pdf$',
    re.IGNORECASE
)

# Pattern 4: Generic — anything after # before first underscore
GENERIC_PATTERN = re.compile(r'#([^_#\s]+)_', re.IGNORECASE)


def extract_case_number_from_url(url: str) -> str:
    """
    Extract the court case number from an S3 source URL.
    Returns None if no pattern matches.
    """
    if not url:
        return None

    # Try MPHC first (more specific)
    m = MPHC_PATTERN.search(url)
    if m:
        return m.group(1).lower()

    # Try standard HC case number
    m = HC_CASE_PATTERN.search(url)
    if m:
        return m.group(1).lower()

    # Try SC regional
    m = SC_REGIONAL_PATTERN.search(url)
    if m:
        return f"sci_{m.group(1).lower()}"

    # Generic fallback
    m = GENERIC_PATTERN.search(url)
    if m and len(m.group(1)) > 5:
        return m.group(1).lower()

    return None


def normalize(text: str) -> str:
    if not text:
        return None
    return re.sub(r'\s+', ' ', text.lower().strip())


def run():
    conn = psycopg.connect(POSTGRES_DSN, autocommit=True)
    cur = conn.cursor()

    # Count work to do
    cur.execute("""
        SELECT count(*) FROM legal_documents
        WHERE (citation IS NULL OR citation = '')
          AND source_url IS NOT NULL
          AND source_url LIKE 's3:' || '//%'
    """)
    total = cur.fetchone()[0]
    logger.info(f"Phase 1: {total:,} docs with S3 URL and no citation to process")

    # Ensure citation_lookup table exists
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

    # Add id_type column if it doesn't exist (migration safety)
    try:
        cur.execute("ALTER TABLE citation_lookup ADD COLUMN IF NOT EXISTS id_type TEXT DEFAULT 'reporter'")
    except Exception:
        pass

    # Process in batches using keyset pagination
    processed = 0
    inserted_lookup = 0
    updated_docs = 0
    skipped = 0
    last_doc_id = ''
    t0 = time.time()

    while True:
        cur.execute("""
            SELECT doc_id, source_url, court, doc_type::TEXT
            FROM legal_documents
            WHERE (citation IS NULL OR citation = '')
              AND source_url IS NOT NULL
              AND source_url LIKE 's3:' || '//%'
              AND doc_id > %s
            ORDER BY doc_id
            LIMIT %s
        """, (last_doc_id, BATCH_SIZE))
        rows = cur.fetchall()
        if not rows:
            break

        # Build batch inserts
        lookup_rows = []
        update_rows = []

        for doc_id, source_url, court, doc_type in rows:
            case_num = extract_case_number_from_url(source_url)
            if not case_num:
                skipped += 1
                continue

            norm = normalize(case_num)
            lookup_rows.append((norm, doc_id, court, doc_type, True, 'case_number'))
            update_rows.append((norm, doc_id))

        # Bulk insert into citation_lookup
        if lookup_rows:
            cur.executemany("""
                INSERT INTO citation_lookup
                    (citation_normalized, doc_id, court, doc_type, is_canonical, id_type)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (citation_normalized, doc_id) DO NOTHING
            """, lookup_rows)
            inserted_lookup += cur.rowcount

        # Update legal_documents.citation_normalized for these docs
        if update_rows:
            cur.executemany("""
                UPDATE legal_documents
                SET citation_normalized = %s
                WHERE doc_id = %s AND (citation_normalized IS NULL OR citation_normalized = '')
            """, update_rows)
            updated_docs += cur.rowcount

        processed += len(rows)
        last_doc_id = rows[-1][0]

        elapsed = time.time() - t0
        rate = processed / elapsed if elapsed > 0 else 0
        remaining_hrs = (total - processed) / rate / 3600 if rate > 0 else 0
        logger.info(
            f"  {processed:,}/{total:,} ({processed/total*100:.1f}%) | "
            f"{rate:.0f}/sec | ~{remaining_hrs:.1f}h remaining | "
            f"lookup+{inserted_lookup:,} | docs_updated+{updated_docs:,} | skipped={skipped:,}"
        )

    # Final report
    cur.execute("SELECT count(*) FROM citation_lookup")
    total_lookup = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM citation_lookup WHERE is_canonical = TRUE")
    canonical = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM citation_lookup WHERE id_type = 'case_number'")
    case_num_entries = cur.fetchone()[0]

    logger.info("=== PHASE 1 COMPLETE ===")
    logger.info(f"  S3 URLs processed:    {processed:,}")
    logger.info(f"  Skipped (no match):   {skipped:,}")
    logger.info(f"  citation_lookup now:  {total_lookup:,} total, {canonical:,} canonical")
    logger.info(f"  Case number entries:  {case_num_entries:,}")
    logger.info(f"  Docs updated:         {updated_docs:,}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    run()
