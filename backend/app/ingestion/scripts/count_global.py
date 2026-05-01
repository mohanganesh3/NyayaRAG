import sqlite3
import os

STAGING_DIR = "/home/mohanganesh/project002/data/collection/staging/"

def count_all():
    total = 0
    files = sorted([f for f in os.listdir(STAGING_DIR) if f.endswith('.db')])
    print("| Database | Record Count |")
    print("| :--- | :--- |")
    for f in files:
        path = os.path.join(STAGING_DIR, f)
        try:
            conn = sqlite3.connect(path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM legal_documents")
            count = cursor.fetchone()[0]
            print(f"| {f} | {count:,} |")
            total += count
            conn.close()
        except Exception:
            continue
    print(f"\n**GLOBAL TOTAL: {total:,}**")

if __name__ == "__main__":
    count_all()
