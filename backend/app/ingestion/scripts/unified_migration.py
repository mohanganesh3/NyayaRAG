import sqlite3
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("unified_migration")

DB_PATHS = [
    "/home/mohanganesh/project002/data/collection/staging/hc_delhi.db",
    "/home/mohanganesh/project002/data/collection/staging/supreme_court_india.db"
]

def migrate_db(db_path: str):
    logger.info(f"Migrating {db_path}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Modern columns: source_key, parser_version, external_id, metadata (JSON)
    columns_to_add = [
        ("source_key", "TEXT"),
        ("parser_version", "TEXT"),
        ("external_id", "TEXT"),
        ("metadata", "JSON")
    ]
    
    # Check current columns
    cursor.execute("PRAGMA table_info(legal_documents);")
    existing_columns = [row[1] for row in cursor.fetchall()]
    
    for col_name, col_type in columns_to_add:
        if col_name not in existing_columns:
            logger.info(f"Adding column {col_name} to {db_path}...")
            cursor.execute(f"ALTER TABLE legal_documents ADD COLUMN {col_name} {col_type};")
    
    # Optional: Backfill source_key if missing
    cursor.execute(f"UPDATE legal_documents SET source_key = 'hc_delhi' WHERE source_key IS NULL AND '{db_path}'.find('hc_delhi') != -1;")
    cursor.execute(f"UPDATE legal_documents SET source_key = 'supreme_court_india' WHERE source_key IS NULL AND '{db_path}'.find('supreme_court') != -1;")
    
    conn.commit()
    conn.close()
    logger.info(f"Successfully migrated {db_path}")

def main():
    for path in DB_PATHS:
        try:
            migrate_db(path)
        except Exception as e:
            logger.error(f"Failed to migrate {path}: {e}")

if __name__ == "__main__":
    main()
