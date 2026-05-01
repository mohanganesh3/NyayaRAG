import pandas as pd
import sqlite3
import os
import requests
import logging
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("hyper_ingest")

STAGING_DIR = "/home/mohanganesh/project002/data/collection/staging/"
BASE_URL = "https://indian-high-court-judgments.s3.ap-south-1.amazonaws.com/metadata/parquet/"

# Court list from high_courts.csv
COURTS = [
    ("High Court of Delhi", "7_26", "dhcdb"),
    ("Allahabad High Court", "9_13", "cisdb_16012018"),
    ("Allahabad High Court", "9_13", "cishclko"),
    ("Bombay High Court", "27_1", "newos_spl"), 
    ("Bombay High Court", "27_1", "hcaurdb"),
    ("Bombay High Court", "27_1", "newos"),
    ("Calcutta High Court", "19_16", "calcutta_appellate_side"),
    ("Calcutta High Court", "19_16", "calcutta_original_side"),
    ("High Court of Gujarat", "24_17", "gujarathc"),
    ("Madras High Court", "33_10", "hc_cis_mas"),
    ("Madras High Court", "33_10", "mdubench"),
    ("Patna High Court", "10_8", "patnahcucisdb94"),
    ("High Court of Punjab and Haryana", "3_22", "phhc"),
    ("High Court of Rajasthan", "8_9", "rhcjodh240618"),
    ("High Court of Madhya Pradesh", "23_23", "mphc_db_jbp"),
    ("High Court of Karnataka", "29_3", "karnataka_bng_old"),
    ("High Court of Kerala", "32_4", "highcourtofkerala"),
    ("High Court of Andhra Pradesh", "28_2", "aphc"),
    ("High Court for State of Telangana", "36_29", "taphc")
]

def ingest_bench(court_name, court_code, bench_name):
    # Determine target DB
    db_name = "hc_" + court_name.lower().replace(" ", "_") + ".db"
    db_path = os.path.join(STAGING_DIR, db_name)
    
    total_added = 0
    # Years 2000-2026
    for year in range(2000, 2027):
        url = f"{BASE_URL}year={year}/court={court_code}/bench={bench_name}/metadata.parquet"
        try:
            # Check if exists (I'll just try to read)
            df = pd.read_parquet(url, storage_options={"anon": True})
            if len(df) > 0:
                logger.info(f"Streaming {len(df):,} records for {court_name} ({year})...")
                # Map to Unified (v1)
                if "Id" in df.columns:
                    df = df.rename(columns={"Id": "external_id", "Judgment": "content", "Court": "source_key"})
                    # Add missing columns
                    df["parser_version"] = "hyper-parquet-v1"
                    conn = sqlite3.connect(db_path)
                    df.to_sql("legal_documents", conn, if_exists="append", index=False)
                    conn.close()
                    total_added += len(df)
        except Exception:
            # Most years won't have data for every bench, fail silently
            continue
    
    if total_added > 0:
        logger.info(f"FINISHED: {court_name} ({bench_name}) added {total_added:,} records.")

def main():
    logger.info("Launching Mass Parquet Hyper-Ingestor...")
    with ThreadPoolExecutor(max_workers=5) as executor:
        for court_name, court_code, bench_name in COURTS:
            executor.submit(ingest_bench, court_name, court_code, bench_name)

if __name__ == "__main__":
    main()
