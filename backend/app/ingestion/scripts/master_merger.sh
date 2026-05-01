#!/bin/bash
STAGING_DIR="/home/mohanganesh/project002/data/collection/staging"
MASTER_DB="/home/mohanganesh/project002/data/collection/master_corpus.db"

# 1. Get Schema from first DB
FIRST_DB=$(ls $STAGING_DIR/*.db | head -n 1)
SCHEMA=$(sqlite3 $FIRST_DB ".schema legal_documents")

# 2. Reset Master with correct schema
rm -f $MASTER_DB
sqlite3 $MASTER_DB "$SCHEMA"
sqlite3 $MASTER_DB "PRAGMA journal_mode=OFF;"
sqlite3 $MASTER_DB "PRAGMA synchronous=OFF;"
sqlite3 $MASTER_DB "PRAGMA count_changes=OFF;"

echo "Starting Full-Schema Merge of 170 shards..."

for db in $STAGING_DIR/*.db; do
    echo "Merging $db..."
    sqlite3 $MASTER_DB "ATTACH '$db' AS s; INSERT OR REPLACE INTO legal_documents SELECT * FROM s.legal_documents; DETACH s;"
done

echo "Starting Unified Document Count..."
FINAL_COUNT=$(sqlite3 $MASTER_DB "SELECT count(*) FROM legal_documents")
echo "Consolidation Complete! Total Master Records: $FINAL_COUNT"
