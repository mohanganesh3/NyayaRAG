from __future__ import annotations

import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from sentence_transformers import SentenceTransformer
import torch

DB_PATH = Path("data/collection/live_corpus.db")
COLLECTION_NAME = "statutes"
EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_VERSION = "sentence-transformers"
CPU_BATCH_SIZE = 128
MPS_BATCH_SIZE = 256
TEXT_LIMIT = 1800


def main() -> int:
    device = choose_device()
    batch_size = MPS_BATCH_SIZE if device == "mps" else CPU_BATCH_SIZE
    model = SentenceTransformer(EMBEDDING_MODEL, device=device)
    vector_size = model.get_sentence_embedding_dimension()
    client = QdrantClient(host="localhost", port=6333, check_compatibility=False)

    conn = sqlite3.connect(DB_PATH, timeout=120.0)
    try:
        configure_sqlite(conn)
        conn.row_factory = sqlite3.Row
        rows = fetch_pending_rows(conn)
        total = len(rows)
        print(
            f"Chunks to embed: {total} | device={device} | batch_size={batch_size}",
            flush=True,
        )
        if total == 0:
            return 0

        embedded_total = 0
        next_report = min(batch_size, total)
        started_at = time.perf_counter()
        for batch_start in range(0, total, batch_size):
            batch = rows[batch_start : batch_start + batch_size]
            texts = [build_embed_text(row) for row in batch]
            vectors = model.encode(
                texts,
                batch_size=len(batch),
                normalize_embeddings=True,
                show_progress_bar=False,
            )

            timestamp = datetime.now(UTC).isoformat()
            points: list[PointStruct] = []
            point_rows: list[tuple[object, ...]] = []
            chunk_rows: list[tuple[object, ...]] = []

            for index, row in enumerate(batch):
                point_id = row["chunk_id"]
                payload = {
                    "doc_type": "statute_section",
                    "source": "india_code",
                    "doc_id": row["doc_id"],
                    "chunk_id": row["chunk_id"],
                    "act_name": row["act_name"] or "",
                    "section_number": row["section_number"] or "",
                    "section_header": row["section_header"] or "",
                    "jurisdiction": row["jurisdiction"] or "Central",
                    "current_validity": bool(row["current_validity"]),
                    "text_preview": (row["text"] or "")[:300],
                    "source_url": row["source_url"] or "",
                }
                vector = vectors[index].tolist()
                points.append(
                    PointStruct(
                        id=point_id,
                        vector=vector,
                        payload=payload,
                    )
                )
                point_rows.append(
                    (
                        point_id,
                        row["chunk_id"],
                        row["doc_id"],
                        "qdrant",
                        COLLECTION_NAME,
                        EMBEDDING_MODEL,
                        EMBEDDING_VERSION,
                        vector_size,
                        json.dumps(vector, separators=(",", ":")),
                        json.dumps(payload, separators=(",", ":")),
                        timestamp,
                        1,
                    )
                )
                chunk_rows.append(
                    (
                        point_id,
                        EMBEDDING_MODEL,
                        EMBEDDING_VERSION,
                        COLLECTION_NAME,
                        timestamp,
                        0,
                        0,
                        None,
                        row["chunk_id"],
                    )
                )

            client.upsert(collection_name=COLLECTION_NAME, points=points, wait=True)
            persist_batch(conn, point_rows=point_rows, chunk_rows=chunk_rows)
            embedded_total += len(batch)

            if embedded_total >= next_report or embedded_total == total:
                info = client.get_collection(COLLECTION_NAME)
                elapsed = max(time.perf_counter() - started_at, 0.001)
                rate = embedded_total / elapsed
                print(
                    "Embedded "
                    f"{embedded_total}/{total} chunks — "
                    f"Qdrant count: {info.points_count} — "
                    f"rate: {rate:.1f} chunks/sec",
                    flush=True,
                )
                next_report = min(next_report + 1024, total)
    finally:
        conn.close()

    return 0


def choose_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def configure_sqlite(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA temp_store=MEMORY")
    cur.execute("PRAGMA busy_timeout=120000")


def fetch_pending_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
          dc.chunk_id,
          dc.doc_id,
          dc.section_header,
          dc.text,
          dc.section_number,
          dc.act_name,
          dc.embedding_id,
          dc.embedding_model,
          dc.vector_collection,
          ld.source_url,
          sd.jurisdiction,
          sd.current_validity
        FROM document_chunks dc
        JOIN legal_documents ld ON ld.doc_id = dc.doc_id
        JOIN statute_documents sd ON sd.doc_id = dc.doc_id
        WHERE ld.source_system = 'india_code'
          AND dc.text IS NOT NULL
          AND trim(dc.text) <> ''
          AND (
            dc.embedding_id IS NULL
            OR dc.embedding_model IS NULL
            OR dc.embedding_model <> ?
            OR dc.vector_collection IS NULL
            OR dc.vector_collection <> ?
          )
        ORDER BY dc.chunk_index, dc.chunk_id
        """,
        (EMBEDDING_MODEL, COLLECTION_NAME),
    )
    return cur.fetchall()


def build_embed_text(row: sqlite3.Row) -> str:
    act_name = row["act_name"] or "Unknown Act"
    section_number = row["section_number"] or ""
    section_header = row["section_header"] or ""
    text = row["text"] or ""

    prefix = f"{act_name}"
    if section_number:
        prefix += f" Section {section_number}"
    if section_header:
        prefix += f" — {section_header}"
    return f"{prefix}\n\n{text[:TEXT_LIMIT]}".strip()


def persist_batch(
    conn: sqlite3.Connection,
    *,
    point_rows: list[tuple[object, ...]],
    chunk_rows: list[tuple[object, ...]],
) -> None:
    cur = conn.cursor()
    cur.executemany(
        """
        INSERT OR REPLACE INTO vector_store_points
        (point_id, chunk_id, doc_id, backend, collection_name, embedding_model, embedding_version,
         vector_dimension, vector, payload, projected_at, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        point_rows,
    )
    cur.executemany(
        """
        UPDATE document_chunks
        SET embedding_id = ?,
            embedding_model = ?,
            embedding_version = ?,
            vector_collection = ?,
            embedded_at = ?,
            needs_reembedding = ?,
            projection_stale = ?,
            stale_reason = ?
        WHERE chunk_id = ?
        """,
        chunk_rows,
    )
    conn.commit()


if __name__ == "__main__":
    raise SystemExit(main())
