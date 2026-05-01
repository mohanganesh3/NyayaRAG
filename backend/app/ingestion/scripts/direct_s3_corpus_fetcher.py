import os
import sys
import requests
import logging
from pathlib import Path

# Add backend to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("direct_s3_fetcher")

COURTS = [
    "Allahabad_High_Court", "Andhra_Pradesh_High_Court", "Bombay_High_Court",
    "Calcutta_High_Court", "Chhattisgarh_High_Court", "Delhi_High_Court",
    "Gauhati_High_Court", "Gujarat_High_Court", "Himachal_Pradesh_High_Court",
    "Jammu_Kashmir_High_Court", "Jharkhand_High_Court", "Karnataka_High_Court",
    "Kerala_High_Court", "Madhya_Pradesh_High_Court", "Madras_High_Court",
    "Manipur_High_Court", "Meghalaya_High_Court", "Orissa_High_Court",
    "Patna_High_Court", "Punjab_Haryana_High_Court", "Rajasthan_High_Court",
    "Sikkim_High_Court", "Telangana_High_Court", "Tripura_High_Court",
    "Uttarakhand_High_Court"
]

BASE_URL = "https://indian-high-court-judgments.s3.amazonaws.com/{court}/METADATA.parquet"

def download_court(court: str):
    url = BASE_URL.format(court=court)
    target_path = f"/tmp/hcd_{court}_metadata.parquet"
    
    logger.info(f"Attempting download for {court} from {url}...")
    try:
        resp = requests.get(url, timeout=300, stream=True)
        if resp.status_code == 200:
            with open(target_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024*1024):
                    f.write(chunk)
            file_size = os.path.getsize(target_path) / (1024*1024)
            logger.info(f"SUCCESS: {court} downloaded ({file_size:.2f} MB)")
            return target_path
        else:
            logger.error(f"FAILED: {court} returned {resp.status_code}")
    except Exception as e:
        logger.error(f"ERROR: {court} hit exception: {e}")
    return None

def main():
    os.makedirs("/tmp/hcd_bulk", exist_ok=True)
    for court in COURTS:
        download_court(court)

if __name__ == "__main__":
    main()
