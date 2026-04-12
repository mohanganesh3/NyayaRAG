import argparse
import logging
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
import ddddocr
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
logger = logging.getLogger("collect_hcd_judis")

BASE_URL = "https://delhihighcourt.nic.in/"
# Using the active portal URL found via curl
QUERY_URL = "https://delhihighcourt.nic.in/judis/delhi/order_search.asp"
CAPTCHA_URL = "https://delhihighcourt.nic.in/captcha.asp"
SEARCH_URL = "https://delhihighcourt.nic.in/judis/delhi/order_date_query_list.asp"

class HCDJudisCollector:
    def __init__(self, session: Session, document_only: bool = True):
        self.session = session
        self.orchestrator = IngestionOrchestrator(document_only=document_only)
        self.adapter = PdfLegalDocumentAdapter()
        self.http = requests.Session()
        self.http.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": QUERY_URL
        })
        self.http.verify = False
        self.ocr = ddddocr.DdddOcr(show_ad=False)

    def solve_captcha(self) -> str:
        # Initial landing page fetch to establish session/cookies
        self.http.get(SEARCH_URL, timeout=10) 
        
        for attempt in range(5):
            try:
                headers = self.http.headers.copy()
                headers["Referer"] = QUERY_URL
                resp = self.http.get(CAPTCHA_URL, headers=headers, timeout=15)
                resp.raise_for_status()
                return self.ocr.classification(resp.content).strip()
            except Exception as e:
                logger.warning(f"Captcha fetch attempt {attempt+1} failed: {e}")
                time.sleep(2 ** attempt)
        return ""

    def collect_date_range(self, from_date: str, to_date: str):
        # Format: DD/MM/YYYY
        captcha = self.solve_captcha()
        payload = {
            "from_date": from_date,
            "to_date": to_date,
            "txtCaptcha": captcha,
            "Submit": "Search"
        }
        logger.info(f"Searching JUDIS date range {from_date} to {to_date}...")
        resp = self.http.post(SEARCH_URL, data=payload, timeout=30)
        resp.raise_for_status()
        
        if "Invalid Captcha" in resp.text:
            logger.warning("Captcha failed, retrying...")
            return self.collect_date_range(from_date, to_date)
            
        self._process_results(resp.text, from_date, to_date)

    def _process_results(self, html: str, from_date: str, to_date: str):
        # Pattern: href="view_judgement.asp?id=123456&pdf_file=WPC12023_122641.pdf"
        matches = re.findall(r'pdf_file=([^"&]+)', html, re.IGNORECASE)
        logger.info(f"Found {len(matches)} judgment PDFs for range {from_date}-{to_date}")
        
        for pdf_file in matches:
            # Final direct URL pattern: https://delhihighcourt.nic.in/judgement/{pdf_file}
            url = f"https://delhihighcourt.nic.in/judgement/{pdf_file}"
            if document_exists_by_source_url(self.session, "hc_delhi", url):
                continue
                
            logger.info(f"Ingesting: {url}")
            context = IngestionJobContext(
                source_key="hc_delhi",
                source_url=url,
                parser_version="hcd-judis-v1",
                external_id=f"hcd-judis-{hash(url)}",
                metadata={
                    "court_name": "HC Delhi",
                    "source_surface": "JUDIS",
                    "collector_type": "judis_scraper",
                    "provenance_tier": "official",
                    "period": f"{from_date} to {to_date}"
                }
            )
            try:
                self.orchestrator.ingest(self.session, self.adapter, context)
                self.session.commit()
            except Exception as e:
                self.session.rollback()
                logger.error(f"Failed to ingest {url}: {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--from-date", default="01/01/2023")
    parser.add_argument("--to-date", default="31/01/2023")
    args = parser.parse_args()

    engine = build_engine(f"sqlite:///{args.db}")
    with Session(engine) as session:
        collector = HCDJudisCollector(session)
        collector.collect_date_range(args.from_date, args.to_date)

if __name__ == "__main__":
    main()
