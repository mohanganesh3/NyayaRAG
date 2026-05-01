#!/usr/bin/env bash
set -euo pipefail

utc_ts() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

ROOT="/home/mohanganesh/project002"
VENV_PY="$ROOT/backend/.venv/bin/python"

LIVE_DB="${LIVE_DB:-$ROOT/data/collection/live_corpus.db}"
STAGING_DIR="${STAGING_DIR:-$ROOT/data/collection/staging}"
STATE_PATH="${STATE_PATH:-$ROOT/data/collection/logs/merge_staging.state.txt}"
LOG_DIR="${LOG_DIR:-$ROOT/data/collection/logs}"

DB_URL="${DB_URL:-sqlite+pysqlite:////home/mohanganesh/project002/data/collection/live_corpus.db}"

MERGE_SCRIPT="$ROOT/backend/app/ingestion/scripts/merge_staging_sqlite.py"
BACKFILL_PROV="$ROOT/backend/app/ingestion/scripts/backfill_artifact_provenance.py"
BACKFILL_CASE="$ROOT/backend/app/ingestion/scripts/backfill_case_identifiers.py"
BACKFILL_CITES="$ROOT/backend/app/ingestion/scripts/backfill_citation_edges.py"
UNRESOLVED_SCRIPT="$ROOT/backend/app/ingestion/scripts/export_unresolved_citations.py"

mkdir -p "$LOG_DIR"
RUN_ID="$(date -u +%Y%m%d_%H%M%S)"
RUN_LOG="$LOG_DIR/autopilot_pipeline_${RUN_ID}.log"

# Tee all output to a run log for auditability.
exec > >(tee -a "$RUN_LOG") 2>&1

echo "[$(utc_ts)] autopilot pipeline starting"
echo "[$(utc_ts)] live_db=$LIVE_DB"
echo "[$(utc_ts)] staging_dir=$STAGING_DIR"
echo "[$(utc_ts)] state_path=$STATE_PATH"
echo "[$(utc_ts)] db_url=$DB_URL"
echo "[$(utc_ts)] run_log=$RUN_LOG"

if [[ ! -x "$VENV_PY" ]]; then
  echo "[$(utc_ts)] ERROR: python venv not found/executable: $VENV_PY" >&2
  exit 2
fi

if [[ ! -f "$LIVE_DB" ]]; then
  echo "[$(utc_ts)] ERROR: live DB not found: $LIVE_DB" >&2
  exit 2
fi

if [[ ! -d "$STAGING_DIR" ]]; then
  echo "[$(utc_ts)] ERROR: staging dir not found: $STAGING_DIR" >&2
  exit 2
fi

echo "[$(utc_ts)] STEP 1/5: merge staging shards -> live DB (resumable)"
"$VENV_PY" -u "$MERGE_SCRIPT" \
  --live-db "$LIVE_DB" \
  --staging-dir "$STAGING_DIR" \
  --state-path "$STATE_PATH" \
  --checkpoint-every-db

echo "[$(utc_ts)] STEP 2/5: WAL checkpoint (TRUNCATE)"
"$VENV_PY" - <<PY
import sqlite3

conn = sqlite3.connect("$LIVE_DB")
try:
    rows = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    print({"wal_checkpoint_truncate": rows})
finally:
    conn.close()
PY

echo "[$(utc_ts)] STEP 3/5: backfill artifact_provenance (idempotent)"
"$VENV_PY" -u "$BACKFILL_PROV" \
  --database-path "$LIVE_DB" \
  --commit-every 5000

echo "[$(utc_ts)] STEP 4/5: backfill case identifiers (idempotent-ish)"
"$VENV_PY" -u "$BACKFILL_CASE" \
  --database-url "$DB_URL"

echo "[$(utc_ts)] STEP 5/5: backfill citation edges (pilot; idempotent)"
"$VENV_PY" -u "$BACKFILL_CITES" \
  --database-url "$DB_URL" \
  --commit-every 500

# Optional: export an unresolved citation backlog for targeted collection.
# Enable by setting EXPORT_UNRESOLVED=1 in the environment.
if [[ "${EXPORT_UNRESOLVED:-0}" == "1" ]]; then
  OUT_PATH="$LOG_DIR/unresolved_citations_${RUN_ID}.json"
  echo "[$(utc_ts)] EXTRA: exporting unresolved citation backlog -> $OUT_PATH"
  "$VENV_PY" -u "$UNRESOLVED_SCRIPT" \
    --database-url "$DB_URL" \
    --out "$OUT_PATH" \
    --top 1000
fi

echo "[$(utc_ts)] autopilot pipeline completed successfully"
