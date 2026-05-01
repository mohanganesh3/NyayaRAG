#!/usr/bin/env bash
# NyayaRAG 'Full Power' Master Orchestrator (v2.0)
# Maximizing CPU and GPU utilization simultaneously.

set -e

LOGS_DIR="infra/logs"
mkdir -p "$LOGS_DIR"

echo "======================================================"
echo "  NyayaRAG FULL POWER ORCHESTRATOR v2.0"
echo "======================================================"

# 1. Start Phase 1 (Ingestion) in background
echo "[Phase 1] Igniting Migration (12 Parallel Workers)..."
.venv/bin/python app/ingestion/scripts/consolidator_v4.py > "$LOGS_DIR/migration.log" 2>&1 &
MIGP_PID=$!

# 2. Short delay to allow Postgres buffers to fill
sleep 30
echo "  ✅ Ingestion buffer established."

# 3. Launch Phase 2 & 3 in parallel with Phase 1
echo "[Phase 2/3] Saturating GPUs and remaining CPUs..."

# Citation Graph (CPU Heavy)
.venv/bin/python app/ingestion/scripts/bulk_citation_graph_hydrator.py > "$LOGS_DIR/graph.log" 2>&1 &
GRAPH_PID=$!
echo "  🕸️ Citation Graph unit online (PID: $GRAPH_PID)"

# Multi-GPU Vectorizer (GPU Heavy)
.venv/bin/python app/ingestion/scripts/multi_gpu_vectorizer.py > "$LOGS_DIR/vectorizer.log" 2>&1 &
VECTOR_PID=$!
echo "  🔮 Multi-GPU Vectorizer unit online (PID: $VECTOR_PID)"

echo "------------------------------------------------------"
echo "  🔥 ALL ENGINES RUNNING AT 100% CAPACITY"
echo "  CPUs: Ingestion & Graph Projection"
echo "  GPUs: BGE-M3 Neural Embedding"
echo "------------------------------------------------------"
echo "Follow logs in $LOGS_DIR/ for real-time telemetry."
echo "======================================================"
