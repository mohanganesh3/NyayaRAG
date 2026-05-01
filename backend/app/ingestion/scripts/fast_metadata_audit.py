import sqlite3
import json
from pathlib import Path

CORE_METADATA_FIELDS = [
    "doc_id", "source_system", "source_url", "source_document_ref", "checksum",
    "parser_version", "collector_run_id", "doc_type", "artifact_url",
    "source_surface", "provenance_tier", "date", "court", "title"
]

def check_db(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='legal_documents'")
        if not cursor.fetchone():
            return None
            
        columns = [row[1] for row in cursor.execute("PRAGMA table_info(legal_documents)").fetchall()]
        
        # Take a 1000 row sample
        cursor.execute("SELECT * FROM legal_documents LIMIT 1000")
        rows = cursor.fetchall()
        if not rows:
            return "empty"
            
        total = len(rows)
        stats = {}
        for field in CORE_METADATA_FIELDS:
            if field in columns:
                idx = columns.index(field)
                non_null = sum(1 for r in rows if r[idx] and str(r[idx]).strip() not in ['', 'null', 'None'])
                stats[field] = non_null / total
            else:
                stats[field] = 0.0
        return stats
    finally:
        conn.close()

staging_dir = Path("/home/mohanganesh/project002/data/collection/staging")
results = {}
for db in sorted(staging_dir.glob("*.db")):
    res = check_db(db)
    if res:
        results[db.name] = res

print(json.dumps(results, indent=2))
