#!/usr/bin/env bash
# NyayaRAG Infrastructure Startup Script v2
# Starts PostgreSQL 16 (conda), Qdrant v1.9.7, and Neo4j 5.20.0 — NO sudo, NO Docker.
#
# Usage:  bash infra/start_services.sh
# Stop:   bash infra/stop_services.sh
# Status: bash infra/status.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$BACKEND_DIR/infra/data"
LOGS_DIR="$BACKEND_DIR/infra/logs"
PIDS_DIR="$BACKEND_DIR/infra/pids"
NEO4J_HOME="$BACKEND_DIR/infra/neo4j/neo4j-community-5.20.0"
QDRANT_BIN="$BACKEND_DIR/infra/bin/qdrant"
PG_BIN=/home/mohanganesh/miniconda3/bin

export JAVA_HOME=$(dirname $(dirname $(readlink -f /usr/bin/java)))

mkdir -p "$DATA_DIR/qdrant" "$DATA_DIR/postgres" "$DATA_DIR/neo4j" "$LOGS_DIR" "$PIDS_DIR"

echo "======================================================"
echo "  NyayaRAG Infrastructure Startup v2"
echo "  All three services: PostgreSQL | Qdrant | Neo4j"
echo "======================================================"

# ─── 1. PostgreSQL ────────────────────────────────────────
echo ""
echo "[1/3] PostgreSQL 16 (conda)"
if "$PG_BIN/pg_isready" -h localhost -p 5432 -q 2>/dev/null; then
    echo "  ✅ Already running on :5432"
else
    if [ ! -f "$DATA_DIR/postgres/PG_VERSION" ]; then
        echo "  Initializing cluster..."
        "$PG_BIN/initdb" -D "$DATA_DIR/postgres" --auth=trust --username=nyayarag --encoding=UTF8 --locale=C
        echo "host all all 127.0.0.1/32 trust" >> "$DATA_DIR/postgres/pg_hba.conf"
        echo "local all all trust" >> "$DATA_DIR/postgres/pg_hba.conf"
    fi
    "$PG_BIN/pg_ctl" -D "$DATA_DIR/postgres" -l "$LOGS_DIR/postgres.log" -o "-p 5432 -F" start
    sleep 5
    "$PG_BIN/createdb" -h localhost -p 5432 -U nyayarag nyayarag 2>/dev/null || true
    "$PG_BIN/psql" -h localhost -p 5432 -U nyayarag -d nyayarag -c \
        "CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS unaccent;" > /dev/null 2>&1 || true
    "$PG_BIN/pg_isready" -h localhost -p 5432 -q && echo "  ✅ PostgreSQL started" || echo "  ❌ Failed — check $LOGS_DIR/postgres.log"
fi

# ─── 2. Qdrant ────────────────────────────────────────────
echo ""
echo "[2/3] Qdrant v1.9.7"
if curl -s -o /dev/null -w "%{http_code}" http://localhost:6333/healthz 2>/dev/null | grep -q "200"; then
    echo "  ✅ Already running on :6333"
else
    if [ ! -f "$QDRANT_BIN" ]; then
        echo "  Downloading Qdrant binary..."
        mkdir -p "$BACKEND_DIR/infra/bin"
        curl -fsSL "https://github.com/qdrant/qdrant/releases/download/v1.9.7/qdrant-x86_64-unknown-linux-gnu.tar.gz" \
            -o /tmp/qdrant.tar.gz
        tar -xf /tmp/qdrant.tar.gz -C "$BACKEND_DIR/infra/bin/"
        chmod +x "$QDRANT_BIN"
        rm -f /tmp/qdrant.tar.gz
    fi
    QDRANT__STORAGE__STORAGE_PATH="$DATA_DIR/qdrant" \
    QDRANT__SERVICE__HTTP_PORT=6333 \
    QDRANT__SERVICE__GRPC_PORT=6334 \
        nohup "$QDRANT_BIN" > "$LOGS_DIR/qdrant.log" 2>&1 &
    echo $! > "$PIDS_DIR/qdrant.pid"
    sleep 5
    curl -s -o /dev/null -w "%{http_code}" http://localhost:6333/healthz 2>/dev/null | grep -q "200" \
        && echo "  ✅ Qdrant started (PID $(cat $PIDS_DIR/qdrant.pid))" \
        || echo "  ❌ Failed — check $LOGS_DIR/qdrant.log"
fi

# ─── 3. Neo4j ─────────────────────────────────────────────
echo ""
echo "[3/3] Neo4j Community 5.20.0 (tarball)"
if curl -s -o /dev/null -w "%{http_code}" http://localhost:7474 2>/dev/null | grep -q "200"; then
    echo "  ✅ Already running on :7474 / :7687"
else
    if [ ! -f "$NEO4J_HOME/bin/neo4j" ]; then
        echo "  Downloading Neo4j tarball..."
        mkdir -p "$BACKEND_DIR/infra/neo4j"
        curl -fL "https://dist.neo4j.org/neo4j-community-5.20.0-unix.tar.gz" \
            -o /tmp/neo4j.tar.gz --progress-bar
        tar -xzf /tmp/neo4j.tar.gz -C "$BACKEND_DIR/infra/neo4j/"
        rm -f /tmp/neo4j.tar.gz
        # Write config
        sed -i "s|#server.directories.data=data|server.directories.data=$DATA_DIR/neo4j|" "$NEO4J_HOME/conf/neo4j.conf"
        sed -i "s|#server.directories.logs=logs|server.directories.logs=$LOGS_DIR/neo4j|" "$NEO4J_HOME/conf/neo4j.conf"
        "$NEO4J_HOME/bin/neo4j-admin" dbms set-initial-password nyayarag_dev_password 2>/dev/null || true
    fi
    "$NEO4J_HOME/bin/neo4j" start
    echo "  Waiting for Neo4j to be ready..."
    for i in $(seq 1 30); do
        curl -s -o /dev/null -w "%{http_code}" http://localhost:7474 2>/dev/null | grep -q "200" && break || sleep 3
    done
    curl -s -o /dev/null -w "%{http_code}" http://localhost:7474 2>/dev/null | grep -q "200" \
        && echo "  ✅ Neo4j started" \
        || echo "  ❌ Failed — check $LOGS_DIR/neo4j/neo4j.log"
fi

# ─── Summary ──────────────────────────────────────────────
echo ""
echo "======================================================"
echo "  All Service Status"
echo "======================================================"
printf "  PostgreSQL :5432  → "
"$PG_BIN/pg_isready" -h localhost -p 5432 -q 2>/dev/null && echo "✅ ONLINE" || echo "❌ OFFLINE"
printf "  Qdrant     :6333  → "
curl -s -o /dev/null -w "%{http_code}" http://localhost:6333/healthz 2>/dev/null | grep -q "200" && echo "✅ ONLINE" || echo "❌ OFFLINE"
printf "  Neo4j      :7474  → "
curl -s -o /dev/null -w "%{http_code}" http://localhost:7474 2>/dev/null | grep -q "200" && echo "✅ ONLINE" || echo "❌ OFFLINE"
echo "======================================================"
