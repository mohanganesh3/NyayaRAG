import argparse
import logging
import os
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

# Add backend to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))

from app.db.session import build_engine
from app.ingestion.adapters import PdfLegalDocumentAdapter
from app.ingestion.contracts import IngestionJobContext
from app.ingestion.orchestrator import IngestionOrchestrator
from app.ingestion.collector_utils import (
    document_exists_by_source_url,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ingest_sci_aws")

class SCIAwsIngestor:
    def __init__(self, session: Session, document_only: bool = True):
        self.session = session
        self.orchestrator = IngestionOrchestrator(document_only=document_only)
        self.adapter = PdfLegalDocumentAdapter()

    def ingest_parquet(self, parquet_path: str, limit: int = None):
        logger.info(f"Loading metadata from {parquet_path}...")
        df = pd.read_parquet(parquet_path)
        if limit:
            df = df.head(limit)
            
        logger.info(f"Processing {len(df)} records for Supreme Court...")
        
        count = 0
        new_count = 0
        for idx, row in df.iterrows():
            official_url = row.get("url")
            case_id = row.get("case_id")
            case_year = row.get("case_year")
            if not official_url or not case_id or not case_year:
                continue
                
            # Construct S3 Mirror URL
            # Pattern: https://indian-high-court-judgments.s3.amazonaws.com/Supreme_Court/{year}/{case_id}.pdf
            # Note: Verify prefix format from earlier 'ls'
            source_url = f"https://indian-high-court-judgments.s3.amazonaws.com/Supreme_Court/{case_year}/{case_id}.pdf"
            
            # Check if exists
            if document_exists_by_source_url(self.session, "supreme_court_india", source_url):
                count += 1
                continue
                
            # Map metadata
            context = IngestionJobContext(
                source_key="supreme_court_india",
                source_url=source_url,
                parser_version="sci-aws-registry-v1",
                external_id=f"sci-aws-{case_id}",
                metadata={
                    "court_name": "Supreme Court of India",
                    "case_type": str(row.get("case_type", "")),
                    "case_no": str(row.get("case_no", "")),
                    "case_year": str(case_year),
                    "date_of_judgment": str(row.get("date_of_judgment", "")),
                    "judge": str(row.get("judge", "")),
                    "petitioner": str(row.get("petitioner", "")),
                    "respondent": str(row.get("respondent", "")),
                    "official_source_url": official_url,
                    "source_surface": "AWS Open Data Registry",
                    "collector_type": "bulk_registry_importer",
                    "provenance_tier": "official_mirror"
                }
            )
            
            try:
                self.orchestrator.ingest(self.session, self.adapter, context)
                self.session.commit()
                new_count += 1
            except Exception as e:
                self.session.rollback()
                logger.error(f"Failed to ingest {source_url}: {e}")
                
            if (count + new_count) % 100 == 0:
                logger.info(f"Progress: {count + new_count} processed ({new_count} new)")

        logger.info(f"Completed. {new_count} new documents added to supreme_court_india.db.")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--parquet", required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    engine = build_engine(f"sqlite:///{args.db}")
    with Session(engine) as session:
        ingestor = SCIAwsIngestor(session)
        ingestor.ingest_parquet(args.parquet, args.limit)

if __name__ == "__main__":
    main()
