#!/usr/bin/env python3
"""
NyayaRAG Citation Graph - Batched Gold Standard Migration
Processes in small batches to avoid locking the DB during Vectorizer operation.
"""
import psycopg, logging, time, uuid

POSTGRES_DSN = "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag"
BATCH_SIZE = 50000  # rows per commit — avoids long-running transactions
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("citation_migration_v2")

def run():
    conn = psycopg.connect(POSTGRES_DSN, autocommit=True)
    cur = conn.cursor()

    # Step 1: Ensure normalized columns exist
    logger.info("Step 1: Ensuring normalized columns...")
    cur.execute("ALTER TABLE legal_documents ADD COLUMN IF NOT EXISTS citation_normalized TEXT")
    cur.execute("ALTER TABLE legal_documents ADD COLUMN IF NOT EXISTS neutral_citation_normalized TEXT")
    logger.info("  Done.")

    # Step 2: Batch normalize citations
    logger.info("Step 2: Batch normalizing citations (50k rows/commit)...")
    cur.execute("SELECT count(*) FROM legal_documents WHERE citation IS NOT NULL AND citation_normalized IS NULL")
    total = cur.fetchone()[0]
    logger.info(f"  {total:,} rows to normalize.")
    done = 0
    while True:
        cur.execute("""
            UPDATE legal_documents
            SET citation_normalized = LOWER(REGEXP_REPLACE(REGEXP_REPLACE(TRIM(citation), E'[\\n\\r]+', ' ', 'g'), '\\s+', ' ', 'g'))
            WHERE citation IS NOT NULL
              AND citation_normalized IS NULL
              AND ctid IN (
                SELECT ctid FROM legal_documents
                WHERE citation IS NOT NULL AND citation_normalized IS NULL
                LIMIT %s
              )
        """, (BATCH_SIZE,))
        rows = cur.rowcount
        if rows == 0:
            break
        done += rows
        logger.info(f"  citation_normalized: {done:,}/{total:,} done")

    # Step 3: Batch normalize neutral_citation
    cur.execute("SELECT count(*) FROM legal_documents WHERE neutral_citation IS NOT NULL AND neutral_citation_normalized IS NULL")
    total = cur.fetchone()[0]
    logger.info(f"  {total:,} neutral_citation rows to normalize.")
    done = 0
    while True:
        cur.execute("""
            UPDATE legal_documents
            SET neutral_citation_normalized = LOWER(REGEXP_REPLACE(REGEXP_REPLACE(TRIM(neutral_citation), E'[\\n\\r]+', ' ', 'g'), '\\s+', ' ', 'g'))
            WHERE neutral_citation IS NOT NULL
              AND neutral_citation_normalized IS NULL
              AND ctid IN (
                SELECT ctid FROM legal_documents
                WHERE neutral_citation IS NOT NULL AND neutral_citation_normalized IS NULL
                LIMIT %s
              )
        """, (BATCH_SIZE,))
        rows = cur.rowcount
        if rows == 0:
            break
        done += rows
        logger.info(f"  neutral_citation_normalized: {done:,}/{total:,} done")

    # Step 4: Create citation_lookup table
    logger.info("Step 3: Creating citation_lookup table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS citation_lookup (
            citation_normalized TEXT NOT NULL,
            doc_id              TEXT NOT NULL,
            court               TEXT,
            doc_type            TEXT,
            is_canonical        BOOLEAN DEFAULT FALSE,
            PRIMARY KEY (citation_normalized, doc_id)
        )
    """)

    # Populate from citation_normalized
    logger.info("  Populating from citation_normalized...")
    cur.execute("""
        INSERT INTO citation_lookup (citation_normalized, doc_id, court, doc_type)
        SELECT citation_normalized, doc_id, court, doc_type::TEXT
        FROM legal_documents
        WHERE citation_normalized IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
    logger.info(f"  Inserted {cur.rowcount:,} entries from citation.")

    # Populate from neutral_citation_normalized
    logger.info("  Populating from neutral_citation_normalized...")
    cur.execute("""
        INSERT INTO citation_lookup (citation_normalized, doc_id, court, doc_type)
        SELECT neutral_citation_normalized, doc_id, court, doc_type::TEXT
        FROM legal_documents
        WHERE neutral_citation_normalized IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
    logger.info(f"  Inserted {cur.rowcount:,} entries from neutral_citation.")

    # Step 5: Mark unambiguous canonical entries
    logger.info("Step 4: Marking canonical (unambiguous) citations...")
    # First pass: single-owner citations
    cur.execute("""
        UPDATE citation_lookup cl
        SET is_canonical = TRUE
        WHERE NOT EXISTS (
            SELECT 1 FROM citation_lookup cl2
            WHERE cl2.citation_normalized = cl.citation_normalized
              AND cl2.doc_id != cl.doc_id
        )
    """)
    logger.info(f"  Single-owner canonicals: {cur.rowcount:,}")

    # Second pass: SC citations whose only SC-court entry
    cur.execute("""
        UPDATE citation_lookup cl
        SET is_canonical = TRUE
        WHERE is_canonical = FALSE
          AND (
            cl.citation_normalized LIKE '%scc%'
            OR cl.citation_normalized LIKE '%insc%'
            OR cl.citation_normalized LIKE '% scr %'
          )
          AND LOWER(cl.court) LIKE '%supreme court%'
          AND (
            SELECT count(*) FROM citation_lookup cl2
            WHERE cl2.citation_normalized = cl.citation_normalized
              AND LOWER(cl2.court) LIKE '%supreme court%'
          ) = 1
    """)
    logger.info(f"  SC disambiguated canonicals: {cur.rowcount:,}")

    # Step 6: Create indexes
    logger.info("Step 5: Creating indexes...")
    indexes = [
        ("idx_cl_norm_canonical", "CREATE INDEX IF NOT EXISTS idx_cl_norm_canonical ON citation_lookup (citation_normalized) WHERE is_canonical = TRUE"),
        ("idx_cl_norm_all",       "CREATE INDEX IF NOT EXISTS idx_cl_norm_all ON citation_lookup (citation_normalized)"),
        ("idx_ld_cit_norm",       "CREATE INDEX IF NOT EXISTS idx_ld_cit_norm ON legal_documents (citation_normalized)"),
        ("idx_ld_neut_norm",      "CREATE INDEX IF NOT EXISTS idx_ld_neut_norm ON legal_documents (neutral_citation_normalized)"),
        ("idx_ce_source",         "CREATE INDEX IF NOT EXISTS idx_ce_source ON citation_edges (source_doc_id)"),
        ("idx_ce_target",         "CREATE INDEX IF NOT EXISTS idx_ce_target ON citation_edges (target_doc_id)"),
    ]
    for name, sql in indexes:
        t0 = time.time()
        cur.execute(sql)
        logger.info(f"  {name}: {time.time()-t0:.1f}s")

    cur.execute("SELECT count(*) FROM citation_lookup WHERE is_canonical = TRUE")
    canonical = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM citation_lookup")
    total = cur.fetchone()[0]

    logger.info("=== MIGRATION COMPLETE ===")
    logger.info(f"  Canonical entries: {canonical:,} / {total:,} ({canonical/max(total,1)*100:.1f}% resolvable)")
    cur.close()
    conn.close()

if __name__ == "__main__":
    run()
