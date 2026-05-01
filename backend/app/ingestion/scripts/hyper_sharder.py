#!/usr/bin/env python3
import os
import subprocess
import time

# Hyper-Ingestion 3.4: Full System Saturation (Wave 6)
# Parallelizes AWS Bulk Ingestion across 25+ court-specific shards
# Saturation Goal: 200k - 500k documents per hour

ROOT_DIR = "/home/mohanganesh/project002"
BACKEND_DIR = f"{ROOT_DIR}/backend"
PYTHON = f"{BACKEND_DIR}/.venv/bin/python3"
STAGING_DIR = f"{ROOT_DIR}/data/collection/staging"
SCRIPT = f"{BACKEND_DIR}/app/ingestion/scripts/collect_aws_bulk_judgments.py"

COURT_CODES = [
    "9_13ect_cisdb_16012018en", # Allahabad
    "27_1", # Bombay
    "19_16", # Calcutta
    "18_6", # Gauhati
    "36_29", # Telangana
    "28_2", # Andhra Pradesh
    "22_18", # Chhattisgarh
    "7_26", # Delhi
    "24_17", # Gujarat
    "2_5", # Himachal Pradesh
    "1_12", # Jammu and Kashmir
    "20_7", # Jharkhand
    "29_3", # Karnataka
    "32_4", # Kerala
    "23_23", # Madhya Pradesh
    "14_25", # Manipur
    "17_21", # Meghalaya
    "3_22", # Punjab and Haryana
    "8_9", # Rajasthan
    "11_24", # Sikkim
    "16_20", # Tripura
    "5_15", # Uttarakhand
    "33_10", # Madras
    "21_11", # Orissa
    "10_8" # Patna
]

def run_nohup(cmd, log_name):
    """Launches a command using nohup and background."""
    log_file = f"/tmp/{log_name}.log"
    # Ensure PYTHONPATH is set for imports
    env = os.environ.copy()
    env["PYTHONPATH"] = BACKEND_DIR
    full_cmd = f"nohup {PYTHON} {' '.join(cmd)} > {log_file} 2>&1 &"
    os.system(full_cmd)
    time.sleep(0.05) # Parallel burst stagger

def main():
    print("=== HYPER-INGESTION 3.4: FULL SYSTEM SATURATION (WAVE 6) ===")
    
    # 1. Supreme Court 6-Way Parallel (Year Brackets)
    # 1950-1980, 1981-2000, 2001-2010, 2011-2018, 2019-2022, 2023-2025
    brackets = [
        (1950, 1980), (1981, 2000), (2001, 2010),
        (2011, 2018), (2019, 2022), (2023, 2025)
    ]
    for start, end in brackets:
        bracket_years = [str(y) for y in range(start, end + 1)]
        db_path = f"{STAGING_DIR}/sc_bulk_{start}_{end}.db"
        log_name = f"aws_sc_{start}"
        cmd = [
            SCRIPT,
            "--database-url", f"sqlite+pysqlite:///{db_path}",
            "collect-supreme-court",
            "--include-regional",
            "--years"
        ] + bracket_years
        run_nohup(cmd, log_name)

    # 2. High Court 25-Way Parallel (Court Code Shards)
    for code in COURT_CODES:
        safe_code = code.replace("_", "")
        db_path = f"{STAGING_DIR}/hc_bulk_{safe_code}.db"
        log_name = f"aws_hc_{safe_code}"
        cmd = [
            SCRIPT,
            "--database-url", f"sqlite+pysqlite:///{db_path}",
            "collect-high-courts",
            "--court-code", code
        ]
        run_nohup(cmd, log_name)

    print(f"\n[SUCCESS] Launched 31 Dedicated Bulk Workers.")
    print("Targeting 200k - 500k docs/hr.")

if __name__ == "__main__":
    main()
