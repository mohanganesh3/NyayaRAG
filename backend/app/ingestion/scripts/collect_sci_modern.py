import argparse
import logging
import os
import re
import sys
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup
import ddddocr

# Add backend to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))

from app.db.session import build_engine
from app.ingestion.adapters import PdfLegalDocumentAdapter
from app.ingestion.contracts import IngestionJobContext
from app.ingestion.orchestrator import IngestionOrchestrator
from app.ingestion.collector_utils import (
    document_exists_by_source_url,
)
from sqlalchemy.orm import Session

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("collect_sci_modern")

BASE_URL = "https://main.sci.gov.in"
SEARCH_URL = f"{BASE_URL}/judgments"
CAPTCHA_URL = f"{BASE_URL}/captcha"

class SCIModeCollector:
    def __init__(self, session: Session, document_only: bool = True):
        self.session = session
        self.orchestrator = IngestionOrchestrator(document_only=document_only)
        self.adapter = PdfLegalDocumentAdapter()
        self.http = requests.Session()
        self.http.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": SEARCH_URL
        })
        self.http.verify = False
        self.ocr = ddddocr.DdddOcr(show_ad=False)

    def solve_captcha(self) -> str:
        resp = self.http.get(CAPTCHA_URL, timeout=10)
        resp.raise_for_status()
        # ddddocr can take bytes directly
        return self.ocr.classification(resp.content).strip()

    def collect_date_range(self, from_date: str, to_date: str):
        for attempt in range(5):
            try:
                # 1. Fetch CSRF token
                resp = self.http.get(SEARCH_URL, timeout=15)
                resp.raise_for_status()
                match = re.search(r'name="_token" value="([^"]+)"', resp.text)
                if not match:
                    logger.error("Failed to find CSRF token on SCI portal.")
                    return
                token = match.group(1)

                # 2. Solve Captcha
                captcha = self.solve_captcha()
                logger.info(f"Solved Captcha: {captcha}")

                # 3. POST Search
                payload = {
                    "_token": token,
                    "fromDate": from_date,
                    "toDate": to_date,
                    "ansValue": captcha,
                    "submit": "Search"
                }
                
                resp = self.http.post(SEARCH_URL, data=payload, timeout=30)
                resp.raise_for_status()
                
                self._process_results(resp.text)
                return # SUCCESS
            except Exception as e:
                logger.warning(f"SCI Search attempt {attempt+1} failed: {e}")
                time.sleep(5 ** attempt) # Longer wait for 503s

    def _process_results(self, html: str):
        soup = BeautifulSoup(html, "html.parser")
        # SCI results table often has 'href' to api.sci.gov.in
        links = soup.find_all("a", href=re.compile(r"api\.sci\.gov\.in/.*\.pdf"))
        logger.info(f"Found {len(links)} judgment PDFs.")

        count = 0
        for link in links:
            url = link["href"]
            if document_exists_by_source_url(self.session, "supreme_court_india", url):
                continue
            
            # Map metadata
            # Row structure: [S.No, Diary No, Case No, Judgment Date, Parties]
            row = link.find_parent("tr")
            tds = row.find_all("td") if row else []
            
            context = IngestionJobContext(
                source_key="supreme_court_india",
                source_url=url,
                parser_version="sci-modern-v1",
                external_id=Path(url).name,
                metadata={
                    "court_name": "Supreme Court of India",
                    "date_text": tds[3].get_text(strip=True) if len(tds) > 3 else "",
                    "parties": tds[4].get_text(strip=True) if len(tds) > 4 else "",
                    "source_surface": SEARCH_URL,
                    "collector_type": "modern_portal_collector"
                }
            )
            
            try:
                self.orchestrator.ingest(self.session, self.adapter, context)
                self.session.commit()
                count += 1
            except Exception as e:
                self.session.rollback()
                logger.error(f"Failed to ingest {url}: {e}")

        logger.info(f"Ingested {count} new SC judgments.")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--from-date", required=True, help="DD-MM-YYYY")
    parser.add_argument("--to-date", required=True, help="DD-MM-YYYY")
    args = parser.parse_args()

    engine = build_engine(f"sqlite:///{args.db}")
    with Session(engine) as session:
        collector = SCIModeCollector(session)
        collector.collect_date_range(args.from_date, args.to_date)

if __name__ == "__main__":
    main()
