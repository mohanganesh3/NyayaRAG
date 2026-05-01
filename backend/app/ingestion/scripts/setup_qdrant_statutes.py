from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

DB_PATH = Path("data/collection/live_corpus.db")
COLLECTION_NAME = "statutes"
VECTOR_SIZE = 1024


def main() -> int:
    client = QdrantClient(host="localhost", port=6333, check_compatibility=False)
    existing = {collection.name for collection in client.get_collections().collections}

    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        print(f"Created collection: {COLLECTION_NAME}")
    else:
        print(f"Collection already exists: {COLLECTION_NAME}")

    info = client.get_collection(COLLECTION_NAME)
    upsert_collection_metadata()
    print(f"Current vector count: {info.points_count}")
    return 0


def upsert_collection_metadata() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO vector_store_collections
            (name, backend, vector_size, distance_metric, indexed_payload_fields, description, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                COLLECTION_NAME,
                "qdrant",
                VECTOR_SIZE,
                "cosine",
                json.dumps([]),
                "India Code statute-section embeddings in Qdrant.",
                1,
            ),
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
