import sqlite3
import os

staging = '/home/mohanganesh/project002/data/collection/staging/'
files = [f for f in os.listdir(staging) if f.endswith('.db')]

print(f"Auditing {len(files)} databases...")
total = 0
for f in files:
    try:
        conn = sqlite3.connect(os.path.join(staging, f))
        cursor = conn.cursor()
        
        # Try both common table names
        count = 0
        for table in ['legal_documents', 'documents', 'judgments']:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                break
            except:
                continue
        
        if count > 0:
            print(f"{f}: {count}")
            total += count
        conn.close()
    except Exception:
        pass

print("-" * 30)
print(f"TOTAL_GLOBAL_CORPUS: {total:,}")
print(f"TARGET_CORPUS: 1,250,000")
print(f"PERCENT_COMPLETE: {(total/1250000)*100:.2f}%")
