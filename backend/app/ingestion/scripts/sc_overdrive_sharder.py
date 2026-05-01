import subprocess
import time
import os

# Decade-level sharding for Supreme Court (1950-2026)
DECADES = [
    ("1950", "1960"), ("1961", "1970"), ("1971", "1980"), ("1981", "1990"),
    ("1991", "2000"), ("2001", "2010"), ("2011", "2015"), ("2016", "2020"),
    ("2021", "2023"), ("2024", "2026")
]

def launch_overdrive():
    processes = []
    for start_year, end_year in DECADES:
        log_file = f"/tmp/sc_overdrive_{start_year}_{end_year}.log"
        db_path = "/home/mohanganesh/project002/data/collection/staging/supreme_court_india.db"
        cmd = [
            "/home/mohanganesh/project002/backend/.venv/bin/python3",
            "-m", "app.ingestion.scripts.collect_sci_official_judgements",
            "--start-date", f"{start_year}-01-01",
            "--end-date", f"{end_year}-12-31",
            "--database-url", f"sqlite+pysqlite:///{db_path}",
            "--window-days", "90"
        ]
        
        print(f"Launching SC Overdrive worker for {start_year}-{end_year}...")
        p = subprocess.Popen(cmd, stdout=open(log_file, "w"), stderr=subprocess.STDOUT)
        processes.append(p)
    
    print(f"Launched {len(processes)} parallel workers. Target: 100% TODAY.")
    return processes

if __name__ == "__main__":
    launch_overdrive()
