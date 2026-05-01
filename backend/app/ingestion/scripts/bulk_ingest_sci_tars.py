import os
import sys
import json
import logging
import tarfile
import requests
from pathlib import Path
from datetime import datetime

# Add backend to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))

from app.db.session import build_engine
from app.ingestion.contracts import IngestionJobContext
from app.ingestion.adapters import PdfLegalDocumentAdapter
from app.ingestion.orchestrator import IngestionOrchestrator
from sqlalchemy.orm import Session

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("bulk_ingest_sci_tars")

BASE_S3_URL = "https://indian-supreme-court-judgments.s3.amazonaws.com/metadata/tar/year={year}/metadata.tar"

def ingest_tar(session: Session, year: int, orchestrator: IngestionOrchestrator, adapter: PdfLegalDocumentAdapter):
    temp_tar = f"/tmp/sci_{year}_metadata.tar"
    temp_dir = f"/tmp/sci_{year}_extracted"
    
    # 1. Download
    url = BASE_S3_URL.format(year=year)
    logger.info(f"Downloading SC {year} Tar from {url}...")
    resp = requests.get(url, timeout=60, stream=True)
    if not resp.ok:
        logger.error(f"Failed to download year {year}: {resp.status_code}")
        return
    
    with open(temp_tar, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
            
    # 2. Extract
    os.makedirs(temp_dir, exist_ok=True)
    try:
        with tarfile.open(temp_tar, "r") as tar:
            tar.extractall(path=temp_dir)
    except Exception as e:
        logger.error(f"Failed to extract year {year}: {e}")
        return

    # 3. Ingest JSONs
    json_files = list(Path(temp_dir).glob("**/*.json"))
    logger.info(f"Found {len(json_files)} records for year {year}")
    
    for json_file in json_files:
        try:
            with open(json_file, "r") as f:
                data = json.load(f)
            
            source_url = data.get("source_url") or data.get("url")
            if not source_url:
                continue
                
            context = IngestionJobContext(
                source_key="supreme_court_india",
                source_url=source_url,
                parser_version="sci-archival-v1",
                external_id=f"sci-archival-{year}-{hash(source_url)}",
                metadata={
                    "court_name": "Supreme Court of India",
                    "judgment_date": data.get("judgment_date"),
                    "parties": data.get("parties"),
                    "judges": data.get("judges"),
                    "source_surface": "AWS Archival Registry",
                    "period": f"Year {year}"
                }
            )
            orchestrator.ingest(session, adapter, context)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to ingest record {json_file}: {e}")

def main():
    db_path = "/home/mohanganesh/project002/data/collection/staging/supreme_court_india.db"
    engine = build_engine(f"sqlite:///{db_path}")
    orchestrator = IngestionOrchestrator(document_only=True)
    adapter = PdfLegalDocumentAdapter()
    
    with Session(engine) as session:
        for year in range(1950, 2027):
            ingest_tar(session, year, orchestrator, adapter)

if __name__ == "__main__":
    main()
