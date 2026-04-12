import argparse
import json
import logging
import re
import time
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

# Add backend to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))

from app.db.session import build_engine
from app.ingestion.adapters import PdfLegalDocumentAdapter
from app.ingestion.contracts import IngestionJobContext
from app.ingestion.orchestrator import IngestionOrchestrator
from app.ingestion.collector_utils import (
    document_exists_by_source_url,
    ensure_collection_control_schema,
    ensure_source_url_index,
)

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("collect_hcd_official")

BASE_URL = "https://delhihighcourt.nic.in/"
CAPTCHA_GEN_URL = "https://delhihighcourt.nic.in/app/generate-captcha"
SEARCH_URL = "https://delhihighcourt.nic.in/app/case-number"
PDF_BASE_URL = "https://delhihighcourt.nic.in/app/showFileJudgment/"

class HCDOfficialCollector:
    def __init__(self, session: Session, document_only: bool = True):
        self.session = session
        self.orchestrator = IngestionOrchestrator(document_only=document_only)
        self.adapter = PdfLegalDocumentAdapter()
        self.http = requests.Session()
        self.http.headers.update({
            "User-Agent": "curl/8.5.0",
            "Accept": "*/*",
        })
        self.http.verify = False # Bypass possible NIC.in SSL issues
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _get_captcha(self) -> tuple[str, str]:
        """Exploit the plaintext captcha vulnerability."""
        print(f"Fetching captcha from {CAPTCHA_GEN_URL}...", flush=True)
        resp = self.http.get(CAPTCHA_GEN_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        code = data.get("captcha_code", "")
        print(f"Bypassed captcha: {code}", flush=True)
        return code, data.get("randomid", "")

    def _get_csrf_token(self) -> str:
        print(f"Fetching CSRF from {SEARCH_URL}...", flush=True)
        resp = self.http.get(SEARCH_URL, timeout=10)
        resp.raise_for_status()
        print(f"CSRF Page Status: {resp.status_code}, Length: {len(resp.text)}", flush=True)
        print(f"HTML Snippet: {resp.text[:200]}", flush=True)
        try:
            match = re.search(r'name="_token" value="([^"]+)"', resp.text)
            token = match.group(1) if match else ""
            print(f"Extracted CSRF: {token[:8]}...", flush=True)
            return token
        except Exception as e:
            print(f"Regex error: {e}", flush=True)
            return ""

    def collect_range(self, case_type: str, year: int, start_num: int, end_num: int):
        token = self._get_csrf_token()
        for num in range(start_num, end_num + 1):
            captcha, randomid = self._get_captcha()
            payload = {
                "_token": token,
                "case_type": case_type,
                "case_number": str(num),
                "year": str(year),
                "captchaInput": captcha,
            }
            logger.info(f"Searching {case_type}/{num}/{year} with captcha {captcha}...")
            
            # Step 1: Validate Captcha via AJAX
            validate_url = "https://delhihighcourt.nic.in/app/validateCaptcha"
            validate_payload = {
                "_token": token,
                "captchaInput": captcha
            }
            print(f"Validating captcha via {validate_url}...", flush=True)
            v_resp = self.http.post(validate_url, data=validate_payload, timeout=20)
            v_data = v_resp.json()
            if not v_data.get("success"):
                logger.error(f"Captcha validation failed for {captcha}")
                print(f"Validation failed: {v_data}", flush=True)
                continue
            
            # Step 2: Perform ACTUAL search
            print(f"POSTing to {SEARCH_URL} for {num}/{year} with payload: {payload}", flush=True)
            try:
                resp = self.http.post(SEARCH_URL, data=payload, timeout=40)
                resp.raise_for_status()
                print(f"Response received ({len(resp.text)} bytes)", flush=True)
                # Check for "NO RECORDS FOUND"
                if "No Records Found" in resp.text:
                    logger.info(f"No records for {num}/{year}")
                    continue
                self._process_results(resp.text, case_type, year, num)
            except Exception as e:
                logger.error(f"Failed to search {num}: {e}")
                print(f"Search error: {e}", flush=True)
            time.sleep(0.5) # Politeness

    def _process_results(self, html: str, case_type: str, year: int, num: int):
        # Look for the showFileJudgment URLs
        links = re.findall(r'href="([^"]+showFileJudgment/[^"]+)"', html)
        if not links:
            logger.warning(f"No PDF links found in results for {num}/{year}")
            return
            
        for link in links:
            pdf_url = urljoin(BASE_URL, link)
            if document_exists_by_source_url(self.session, "hc_delhi", pdf_url):
                logger.info(f"Skipping existing: {pdf_url}")
                continue

            logger.info(f"Ingesting: {pdf_url}")
            context = IngestionJobContext(
                source_key="hc_delhi",
                source_url=pdf_url,
                parser_version="hcd-official-v1",
                external_id=f"hcd-{Path(pdf_url).stem}",
                metadata={
                    "court_name": "HC Delhi",
                    "case_type": case_type,
                    "case_year": year,
                    "case_no": num,
                    "collector_type": "official_scraper",
                    "provenance_tier": "official",
                }
            )
            try:
                self.orchestrator.ingest(self.session, self.adapter, context)
                self.session.commit()
            except Exception as e:
                self.session.rollback()
                logger.error(f"Ingestion failed for {pdf_url}: {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--case-type", default="CW") # W.P.(C)
    parser.add_argument("--year", type=int, default=2023)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=50) # Small batch first
    args = parser.parse_args()

    engine = build_engine(f"sqlite:///{args.db}")
    with Session(engine) as session:
        # ensure_collection_control_schema(session)
        # ensure_source_url_index(session)
        collector = HCDOfficialCollector(session)
        collector.collect_range(args.case_type, args.year, args.start, args.end)

if __name__ == "__main__":
    main()
