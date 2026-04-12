import argparse
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from PIL import Image
from sqlalchemy.orm import Session

try:
    import pytesseract
except ImportError:
    pytesseract = None

# Add backend to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))

from app.db.session import build_engine
from app.ingestion.adapters import PdfLegalDocumentAdapter
from app.ingestion.contracts import IngestionJobContext
from app.ingestion.orchestrator import IngestionOrchestrator
from app.ingestion.collector_utils import (
    document_exists_by_source_url,
    ensure_collection_control_schema,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("collect_hcd_edhcr")

BASE_URL = "https://edhcr.nic.in/"
MAIN_URL = "https://edhcr.nic.in/main.php"
CAPTCHA_URL = "https://edhcr.nic.in/get_captcha.php"
SEARCH_URL = "https://edhcr.nic.in/search_db.php"

class HCDEdhcrCollector:
    def __init__(self, session: Session, document_only: bool = True):
        self.session = session
        self.orchestrator = IngestionOrchestrator(document_only=document_only)
        self.adapter = PdfLegalDocumentAdapter()
        self.http = requests.Session()
        self.http.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": MAIN_URL
        })
        self.http.verify = False

    def solve_captcha(self) -> str:
        resp = self.http.get(CAPTCHA_URL, timeout=10)
        resp.raise_for_status()
        with open("/tmp/hcd_captcha.png", "wb") as f:
            f.write(resp.content)
        
        if pytesseract:
            text = pytesseract.image_to_string(Image.open("/tmp/hcd_captcha.png")).strip()
            # Basic cleanup for common OCR errors
            text = re.sub(r'[^a-zA-Z0-9]', '', text)
            logger.info(f"OCR solved captcha: {text}")
            return text
        return ""

    def collect_date_range(self, from_date: str, to_date: str):
        # EDHCR format DD-MM-YYYY
        captcha = self.solve_captcha()
        payload = {
            "selBench": "0",
            "selJudge": "0",
            "selCaseGroup": "0",
            "txtFromDate": from_date,
            "txtToDate": to_date,
            "txtCaptcha": captcha,
            "cmdSearch": "Search"
        }
        logger.info(f"Searching date range {from_date} to {to_date}...")
        resp = self.http.post(SEARCH_URL, data=payload, timeout=30)
        resp.raise_for_status()
        
        if "Invalid Captcha" in resp.text:
            logger.warning("Captcha failed, retrying...")
            return self.collect_date_range(from_date, to_date)
            
        self._process_results(resp.text, from_date, to_date)

    def _process_results(self, html: str, from_date: str, to_date: str):
        # Look for PDF links. EDHCR usually has links like href="view_judgment.php?id=..."
        # or direct PDFs. We search for any .php?id= or .pdf
        links = re.findall(r'href="([^"]+\.pdf|[^"]+view_judgment\.php\?id=[^"]+)"', html)
        logger.info(f"Found {len(links)} links for range {from_date}-{to_date}")
        
        for link in links:
            url = urljoin(BASE_URL, link)
            if document_exists_by_source_url(self.session, "hc_delhi", url):
                continue
                
            logger.info(f"Ingesting: {url}")
            context = IngestionJobContext(
                source_key="hc_delhi",
                source_url=url,
                parser_version="hcd-edhcr-v1",
                external_id=f"hcd-edhcr-{hash(url)}",
                metadata={
                    "court_name": "HC Delhi",
                    "source_surface": "EDHCR",
                    "collector_type": "edhcr_scraper",
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
    parser.add_argument("--from-date", default="01-01-1966")
    parser.add_argument("--to-date", default="01-04-2026")
    args = parser.parse_args()

    engine = build_engine(f"sqlite:///{args.db}")
    with Session(engine) as session:
        # ensure_collection_control_schema(session)
        collector = HCDEdhcrCollector(session)
        # Process in month-long chunks to avoid timeouts
        start_dt = datetime.strptime(args.from_date, "%d-%m-%Y")
        end_dt = datetime.strptime(args.to_date, "%d-%m-%Y")
        curr = start_dt
        while curr < end_dt:
            chunk_end = min(curr + timedelta(days=30), end_dt)
            collector.collect_date_range(curr.strftime("%d-%m-%Y"), chunk_end.strftime("%d-%m-%Y"))
            curr = chunk_end + timedelta(days=1)
            time.sleep(1)

if __name__ == "__main__":
    main()
