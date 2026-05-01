import sqlite3
import os
import uuid
import logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

STAGING_DIR = Path("/home/mohanganesh/project002/data/collection/staging")

def backfill_db(db_path):
    logger.info(f"Backfilling {db_path.name}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check if table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='legal_documents';")
    if not cursor.fetchone():
        logger.warning(f"Table 'legal_documents' not found in {db_path.name}")
        conn.close()
        return

    # Update collector_run_id if NULL (using ingestion_run_id as fallback)
    cursor.execute("""
        UPDATE legal_documents 
        SET collector_run_id = COALESCE(collector_run_id, ingestion_run_id, ?) 
        WHERE collector_run_id IS NULL OR collector_run_id = '';
    """, (str(uuid.uuid4()),))
    
    # Update artifact_url if NULL (using source_url as fallback)
    cursor.execute("""
        UPDATE legal_documents 
        SET artifact_url = COALESCE(artifact_url, source_url) 
        WHERE (artifact_url IS NULL OR artifact_url = '') AND source_url IS NOT NULL;
    """)
    
    # Update source_surface if NULL
    source_name = db_path.stem.replace("hc_", "").replace("_", " ").upper()
    cursor.execute("""
        UPDATE legal_documents 
        SET source_surface = 'official' 
        WHERE source_surface IS NULL OR source_surface = '';
    """)
    
    # Update provenance_tier if NULL
    cursor.execute("""
        UPDATE legal_documents 
        SET provenance_tier = 'official' 
        WHERE provenance_tier IS NULL OR provenance_tier = '';
    """)
    
    # Update date from date_text if date is NULL
    # This is a very simple parser, we might need something more robust like dateutil
    # But for now, let's try to copy decision_date if it exists
    cursor.execute("""
        UPDATE legal_documents 
        SET date = COALESCE(date, decision_date) 
        WHERE date IS NULL AND decision_date IS NOT NULL;
    """)

    # Update doc_id if NULL (shouldn't happen but just in case)
    cursor.execute("""
        UPDATE legal_documents 
        SET doc_id = ? 
        WHERE doc_id IS NULL OR doc_id = '';
    """, (str(uuid.uuid4()),))

    # Fix generic titles
    cursor.execute("""
        UPDATE legal_documents 
        SET title = doc_type || ' - ' || source_document_ref
        WHERE (title IS NULL OR title = '' OR title = 'JUDGMENT' OR title = 'ORDER') 
        AND doc_type IS NOT NULL AND source_document_ref IS NOT NULL;
    """)

    conn.commit()
    conn.close()
    logger.info(f"Done backfilling {db_path.name}")

def main():
    if not STAGING_DIR.exists():
        logger.error(f"Staging directory {STAGING_DIR} not found")
        return

    for db_file in STAGING_DIR.glob("*.db"):
        if db_file.name.startswith("_debug"):
            continue
        try:
            backfill_db(db_file)
        except Exception as e:
            logger.error(f"Failed to backfill {db_file.name}: {e}")

if __name__ == "__main__":
    main()
