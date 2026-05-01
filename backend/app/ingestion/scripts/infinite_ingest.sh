#!/bin/bash
# infinite_ingest.sh: Auto-restarts ingestion workers until 100% completion

echo "[$(date)] Starting NyayaRAG Resilience Orchestrator..."
PYTHON_BIN="/home/mohanganesh/project002/backend/.venv/bin/python3"
SCRIPT_DIR="/home/mohanganesh/project002/backend/app/ingestion/scripts"
export PYTHONPATH=$PYTHONPATH:/home/mohanganesh/project002/backend

while true; do
    # 1. SC Overdrive (Decade-level sharding)
    # We'll run 2 workers at a time to avoid 503s
    pgrep -f "sc_overdrive_sharder" > /dev/null || {
        echo "[$(date)] Restarting SC Overdrive..."
        nohup $PYTHON_BIN $SCRIPT_DIR/sc_overdrive_sharder.py > /tmp/sc_auto_restart.log 2>&1 &
    }

    # 2. High Court Hyper-Ingest (25 HCs, Parquet)
    pgrep -f "hyper_ingest_parquet" > /dev/null || {
        echo "[$(date)] Restarting High Court Hyper-Blitz..."
        nohup $PYTHON_BIN $SCRIPT_DIR/hyper_ingest_parquet.py > /tmp/hcd_hyper_auto.log 2>&1 &
    }

    # 3. SC Bulk static
    pgrep -f "bulk_ingest_sci_tars" > /dev/null || {
        echo "[$(date)] Restarting SC Bulk static..."
        nohup $PYTHON_BIN $SCRIPT_DIR/bulk_ingest_sci_tars.py > /tmp/sci_auto_restart.log 2>&1 &
    }

    echo "[$(date)] Workers active. Sleeping 120s..."
    sleep 120
done
