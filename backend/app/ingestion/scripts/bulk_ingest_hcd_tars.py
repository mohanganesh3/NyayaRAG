import os
import tarfile
import sqlite3
import pandas as pd
import requests
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("bulk_ingest_hcd")

STAGING_DIR = "/home/mohanganesh/project002/data/collection/staging/"
DB_PATH = os.path.join(STAGING_DIR, "hc_delhi.db")
# Direct link to Delhi Archival Tar
HCD_TAR_URL = "https://indian-high-court-judgments.s3.amazonaws.com/Delhi_High_Court/metadata.tar"

def download_and_ingest():
    local_tar = "/tmp/hcd_metadata.tar"
    logger.info(f"Downloading Delhi Bulk Tar from {HCD_TAR_URL}...")
    
    try:
        resp = requests.get(HCD_TAR_URL, stream=True, timeout=600)
        if resp.status_code == 200:
            with open(local_tar, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024*1024):
                    f.write(chunk)
            logger.info("Download Complete. Extracting and Ingesting...")
            
            # Extract and process
            with tarfile.open(local_tar, "r") as tar:
                # Delhi HCD tars usually contain year-wise CSVs or Parquets
                # We'll extract to tmp and iterate
                extract_path = "/tmp/hcd_bulk_extract"
                os.makedirs(extract_path, exist_ok=True)
                tar.extractall(path=extract_path)
                
                conn = sqlite3.connect(DB_PATH)
                total_added = 0
                for root, dirs, files in os.walk(extract_path):
                    for file in files:
                        if file.endswith(".parquet") or file.endswith(".csv"):
                            file_path = os.path.join(root, file)
                            try:
                                df = pd.read_parquet(file_path) if file.endswith(".parquet") else pd.read_csv(file_path)
                                # Map to Unified Schema
                                # Assuming columns: Id, Judgment, Court, Date
                                if "Id" in df.columns:
                                    df = df.rename(columns={"Id": "external_id", "Judgment": "content", "Court": "source_key"})
                                    df["parser_version"] = "hcd-archival-v1"
                                    df.to_sql("legal_documents", conn, if_exists="append", index=False)
                                    total_added += len(df)
                            except Exception as e:
                                logger.error(f"Error processing {file}: {e}")
                
                conn.close()
                logger.info(f"SUCCESS: Added {total_added:,} records to Delhi High Court.")
        else:
            logger.error(f"Failed to download tar: {resp.status_code}")
    except Exception as e:
        logger.error(f"Bulk ingestion failed: {e}")

if __name__ == "__main__":
    download_and_ingest()
