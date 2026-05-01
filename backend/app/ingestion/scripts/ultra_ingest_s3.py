import sqlite3
import pandas as pd
import s3fs
import os
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ultra_ingest")

STAGING_DIR = "/home/mohanganesh/project002/data/collection/staging/"

COURTS = {
    "Delhi_High_Court": "hc_delhi.db",
    "Supreme_Court": "supreme_court_india.db",
    "Calcutta_High_Court": "hc_calcutta.db",
    "Gujarat_High_Court": "hc_gujarat.db",
    "Patna_High_Court": "hc_patna.db",
    "Rajasthan_High_Court": "hc_rajasthan.db"
}

# Standard AWS Open Data Buckets
HC_BUCKET = "s3://indian-high-court-judgments/{court}/METADATA.parquet"
SC_BUCKET = "s3://indian-supreme-court-judgments/metadata/parquet/METADATA.parquet"

def ingest_court(court_prefix, db_name):
    db_path = os.path.join(STAGING_DIR, db_name)
    s3_path = SC_BUCKET if court_prefix == "Supreme_Court" else HC_BUCKET.format(court=court_prefix)
    
    logger.info(f"Steaming {court_prefix} from {s3_path}...")
    try:
        # Use storage_options for anonymous access
        df = pd.read_parquet(s3_path, storage_options={"anon": True})
        logger.info(f"Loaded {len(df):,} records for {court_prefix}. Ingesting to {db_name}...")
        
        # Prepare for Unified Schema
        # External_id, source_key, metadata, etc.
        # We'll map 'Id' to external_id and 'Judgment' to content
        
        conn = sqlite3.connect(db_path)
        
        # Fast ingest
        df.to_sql("legal_documents", conn, if_exists="append", index=False, chunksize=10000)
        
        conn.close()
        logger.info(f"SUCCESS: {court_prefix} reached 100% target.")
    except Exception as e:
        logger.error(f"FAILED: {court_prefix} error: {e}")

if __name__ == "__main__":
    for court, db in COURTS.items():
        ingest_court(court, db)
