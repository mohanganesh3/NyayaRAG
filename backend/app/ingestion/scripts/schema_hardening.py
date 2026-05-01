import sqlite3
import os
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

STAGING_DIR = Path("/home/mohanganesh/project002/data/collection/staging")

MANDATORY_COLUMNS = [
    ("collector_run_id", "VARCHAR(36)"),
    ("artifact_url", "VARCHAR(1000)"),
    ("source_surface", "VARCHAR(255)"),
    ("provenance_tier", "VARCHAR(100)"),
    ("date", "DATE"),
]

def harden_db(db_path):
    logger.info(f"Hardening schema for {db_path.name}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check if table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='legal_documents';")
    if not cursor.fetchone():
        logger.warning(f"Table 'legal_documents' not found in {db_path.name}")
        conn.close()
        return

    # Get existing columns
    cursor.execute("PRAGMA table_info(legal_documents);")
    existing_columns = {row[1] for row in cursor.fetchall()}

    # Add missing columns
    for col_name, col_type in MANDATORY_COLUMNS:
        if col_name not in existing_columns:
            logger.info(f"Adding column {col_name} to {db_path.name}")
            try:
                cursor.execute(f"ALTER TABLE legal_documents ADD COLUMN {col_name} {col_type};")
            except Exception as e:
                logger.error(f"Failed to add column {col_name} to {db_path.name}: {e}")

    conn.commit()
    conn.close()
    logger.info(f"Done hardening {db_path.name}")

def main():
    if not STAGING_DIR.exists():
        logger.error(f"Staging directory {STAGING_DIR} not found")
        return

    for db_file in STAGING_DIR.glob("*.db"):
        if db_file.name.startswith("_debug"):
            continue
        try:
            harden_db(db_file)
        except Exception as e:
            logger.error(f"Failed to harden {db_file.name}: {e}")

if __name__ == "__main__":
    main()
