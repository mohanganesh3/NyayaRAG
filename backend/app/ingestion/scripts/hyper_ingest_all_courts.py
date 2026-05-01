import pandas as pd
import sqlite3
import os
import logging
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("blitz")

STAGING_DIR = "/home/mohanganesh/project002/data/collection/staging/"
BASE_URL = "https://indian-high-court-judgments.s3.ap-south-1.amazonaws.com/metadata/parquet/"

# Court list from CSV (Full 45 benches)
COURTS_CSV = "https://raw.githubusercontent.com/vanga/indian-high-court-judgments/main/opendata/docs/high_courts.csv"

def insert_on_conflict(table, conn, keys, data_iter):
    from sqlite3 import IntegrityError
    lst = list(data_iter)
    column_names = ", ".join(keys)
    placeholders = ", ".join(["?"] * len(keys))
    sql = f"INSERT OR IGNORE INTO {table.name} ({column_names}) VALUES ({placeholders})"
    conn.executemany(sql, lst)

def ingest_bench(court_name, court_code, bench_name):
    db_name = "hc_" + court_name.lower().replace(" ", "_").replace("high_court_for_state_of_", "") + ".db"
    db_path = os.path.join(STAGING_DIR, db_name)
    total_added = 0
    
    for year in range(1950, 2027):
        url = f"{BASE_URL}year={year}/court={court_code}/bench={bench_name}/metadata.parquet"
        try:
            df = pd.read_parquet(url, storage_options={"anon": True})
            if len(df) > 0:
                logger.info(f"BLITZ: {court_name} ({year}) -> Streaming {len(df):,}")
                if "Id" in df.columns:
                    df = df.rename(columns={"Id": "external_id", "Judgment": "content", "Court": "source_key"})
                    df["parser_version"] = "hyper-parquet-v1"
                    conn = sqlite3.connect(db_path)
                    df.to_sql("legal_documents", conn, if_exists="append", index=False, method=insert_on_conflict)
                    conn.close()
                    total_added += len(df)
        except Exception:
            continue
    return total_added

def main():
    logger.info("NYAYARAG: Starting 100% Bench Blitz...")
    df_courts = pd.read_csv(COURTS_CSV)
    
    # Process all benches in parallel
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for _, row in df_courts.iterrows():
            futures.append(executor.submit(ingest_bench, row['court_name'], row['court_code'], row['bench_name']))
        
        results = [f.result() for f in futures]
    
    logger.info(f"NYAYARAG: Blitz Complete. Total added: {sum(results):,} across all High Courts.")

if __name__ == "__main__":
    main()
