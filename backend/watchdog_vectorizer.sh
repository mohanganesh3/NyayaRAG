#!/bin/bash
# NyayaRAG Turbo Watchdog - Self-Healing Vectorizer
# Ensures the vectorizer stays alive 24/7.

SCRIPT_PATH="/home/mohanganesh/project002/backend/app/ingestion/scripts/vectorizer_hyper.py"
LOG_PATH="/home/mohanganesh/project002/backend/vectorizer_turbo.log"
PYTHON_BIN="/home/mohanganesh/miniconda3/envs/retail-k80/bin/python"

echo "Igniting Turbo Watchdog..."

while true; do
    # 1. Check if the main process is running
    if ! pgrep -f "vectorizer_hyper.py" > /dev/null; then
        echo "$(date): Vectorizer found DEAD. Relaunching..."
        nohup $PYTHON_BIN $SCRIPT_PATH >> $LOG_PATH 2>&1 &
    fi

    # 2. Check for OOM in the last 100 lines of the log
    if tail -n 100 $LOG_PATH 2>/dev/null | grep -i "OutOfMemory" > /dev/null; then
        echo "$(date): OOM detected in logs. Killing and restarting clean..."
        pkill -9 -f "vectorizer_hyper.py"
        sleep 5
        nohup $PYTHON_BIN $SCRIPT_PATH >> $LOG_PATH 2>&1 &
    fi

    # 3. Wait 60 seconds before next check
    sleep 60
done
