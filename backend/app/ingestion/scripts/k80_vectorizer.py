#!/usr/bin/env python3
"""
K80-Optimized Multi-GPU Vectorizer for NyayaRAG.
Embeds 177M+ document chunks using BGE-M3 across 4× Tesla K80 GPUs.

Hardware-Aware Optimizations:
- batch_size=32 (K80 has 11GB VRAM, BGE-M3 is ~2.2GB in FP32)
- max_seq_length=512 (covers 95%+ of legal chunks, saves VRAM)
- Pre-fetch pipeline (GPU never idles waiting for data)
- Resume-safe (skips already-embedded chunks)
- nohup-compatible logging
"""
import logging
import multiprocessing as mp
import os
import time
from datetime import datetime, timezone

import psycopg
import torch
from psycopg.rows import dict_row
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from sentence_transformers import SentenceTransformer

# ═══════════════════════════════════════════════════
# CONFIGURATION — K80 HARDWARE-AWARE SETTINGS
# ═══════════════════════════════════════════════════
POSTGRES_DSN = "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag"
EMBEDDING_MODEL = "BAAI/bge-m3"
COLLECTION_NAME = "nyayarag_documents"
QDRANT_HOST = "localhost"
QDRANT_GRPC_PORT = 6334

# K80 Critical Settings
BATCH_SIZE = 16          # Reduced to 16 to prevent OOM
MAX_SEQ_LENGTH = 256     # Reduced to 256 to prevent OOM
GPU_COUNT = min(torch.cuda.device_count(), 4) if torch.cuda.is_available() else 0
QUEUE_DEPTH = 50         # Pre-fetch buffer: keeps GPUs saturated

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(processName)s: %(message)s",
    handlers=[
        logging.FileHandler("/home/mohanganesh/project002/backend/vectorizer.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("k80_vectorizer")


def gpu_worker(gpu_id: int, task_queue: mp.Queue, stats_queue: mp.Queue):
    """Worker process bound to a specific K80 GPU."""
    device = f"cuda:{gpu_id}"
    logger.info(f"GPU Worker {gpu_id} initializing on {device}...")

    try:
        # Load model onto this specific GPU
        model = SentenceTransformer(EMBEDDING_MODEL, device=device)
        model.max_seq_length = MAX_SEQ_LENGTH
        logger.info(f"GPU Worker {gpu_id}: Model loaded. max_seq_length={MAX_SEQ_LENGTH}")

        # Qdrant client (REST for stability against version mismatches)
        qdrant = QdrantClient(host=QDRANT_HOST)

        # Postgres connection for marking chunks as embedded
        pg = psycopg.connect(POSTGRES_DSN, row_factory=dict_row, autocommit=False)

        processed = 0
        while True:
            batch = task_queue.get()
            if batch is None:
                break

            try:
                # Build text for embedding
                texts = []
                for chunk in batch:
                    header = chunk.get("section_header") or ""
                    act = chunk.get("act_name") or ""
                    body = chunk.get("text") or ""
                    texts.append(f"{act} | {header}\n{body}".strip()[:1024])

                # Encode on GPU
                vectors = model.encode(
                    texts,
                    batch_size=len(batch),
                    normalize_embeddings=True,
                    show_progress_bar=False
                )

                # Build Qdrant points
                points = []
                for j, chunk in enumerate(batch):
                    points.append(PointStruct(
                        id=chunk["chunk_id"],
                        vector=vectors[j].tolist(),
                        payload={
                            "doc_id": chunk["doc_id"],
                            "chunk_id": chunk["chunk_id"],
                            "court": chunk.get("court"),
                            "date": str(chunk.get("date") or ""),
                            "citation": chunk.get("citation"),
                            "current_validity": chunk.get("current_validity"),
                            "act_name": chunk.get("act_name"),
                            "section_header": chunk.get("section_header"),
                        }
                    ))

                # Upsert to Qdrant (async for throughput)
                qdrant.upsert(collection_name=COLLECTION_NAME, points=points, wait=False)

                # Mark as embedded in Postgres
                now = datetime.now(timezone.utc)
                with pg.cursor() as cur:
                    cur.executemany(
                        "UPDATE document_chunks SET embedding_id = %(eid)s, embedding_model = %(model)s, embedded_at = %(ts)s, needs_reembedding = false WHERE chunk_id = %(cid)s",
                        [{"eid": c["chunk_id"], "model": EMBEDDING_MODEL, "ts": now, "cid": c["chunk_id"]} for c in batch]
                    )
                pg.commit()

                processed += len(batch)
                stats_queue.put(len(batch))

            except Exception as e:
                logger.error(f"GPU {gpu_id} batch error: {e}")
                try:
                    pg.rollback()
                except:
                    pass

        pg.close()
        logger.info(f"GPU Worker {gpu_id}: Completed. Total processed: {processed:,}")

    except Exception as e:
        logger.error(f"GPU Worker {gpu_id} FATAL: {e}")


def main():
    if GPU_COUNT == 0:
        logger.error("No GPUs detected! Cannot proceed.")
        return

    logger.info("═══════════════════════════════════════════════════")
    logger.info("🚀 K80-OPTIMIZED VECTORIZER — FULL HARDWARE MODE")
    logger.info(f"   GPUs:          {GPU_COUNT}× Tesla K80")
    logger.info(f"   Model:         {EMBEDDING_MODEL}")
    logger.info(f"   Batch Size:    {BATCH_SIZE}")
    logger.info(f"   Max Seq Len:   {MAX_SEQ_LENGTH}")
    logger.info(f"   Queue Depth:   {QUEUE_DEPTH}")
    logger.info(f"   Collection:    {COLLECTION_NAME}")
    logger.info("═══════════════════════════════════════════════════")

    # Launch GPU workers
    task_queue = mp.Queue(maxsize=QUEUE_DEPTH)
    stats_queue = mp.Queue()
    workers = []
    for i in range(GPU_COUNT):
        p = mp.Process(target=gpu_worker, args=(i, task_queue, stats_queue), name=f"GPU-{i}")
        p.start()
        workers.append(p)
    logger.info(f"Launched {GPU_COUNT} GPU workers.")

    # Feed chunks from Postgres using server-side cursor
    total_fed = 0
    start_time = time.time()
    try:
        with psycopg.connect(POSTGRES_DSN, row_factory=dict_row) as conn:
            with conn.cursor(name="chunk_feeder") as cur:
                cur.execute("""
                    SELECT chunk_id, doc_id, text, section_header, act_name,
                           court, date, citation, current_validity
                    FROM document_chunks
                    WHERE embedding_id IS NULL
                """)

                batch = []
                while True:
                    rows = cur.fetchmany(BATCH_SIZE)
                    if not rows:
                        break
                    task_queue.put(rows)
                    total_fed += len(rows)

                    if total_fed % 10000 == 0:
                        elapsed = time.time() - start_time
                        rate = total_fed / elapsed if elapsed > 0 else 0
                        logger.info(f"Fed {total_fed:>12,} chunks to GPUs ({rate:,.0f} chunks/sec feed rate)")

    except Exception as e:
        logger.error(f"Feeder error: {e}")
    finally:
        # Send poison pills to workers
        for _ in range(GPU_COUNT):
            task_queue.put(None)

    logger.info(f"Feeder complete. Total fed: {total_fed:,}. Waiting for GPU workers to finish...")

    # Monitor progress
    total_embedded = 0
    while any(p.is_alive() for p in workers):
        while not stats_queue.empty():
            count = stats_queue.get()
            total_embedded += count
        time.sleep(5)

        elapsed = time.time() - start_time
        rate = total_embedded / elapsed if elapsed > 0 else 0
        pct = (total_embedded / total_fed * 100) if total_fed > 0 else 0
        remaining = (total_fed - total_embedded) / rate if rate > 0 else 0
        logger.info(
            f"Progress: {total_embedded:>12,}/{total_fed:,} ({pct:.1f}%) "
            f"| {rate:,.0f} chunks/sec "
            f"| ETA: {remaining/3600:.1f}h"
        )

    # Drain remaining stats
    while not stats_queue.empty():
        total_embedded += stats_queue.get()

    elapsed = time.time() - start_time
    logger.info("═══════════════════════════════════════════════════")
    logger.info(f"🏆 VECTORIZATION COMPLETE")
    logger.info(f"   Total Embedded: {total_embedded:,}")
    logger.info(f"   Total Time:     {elapsed/3600:.1f} hours")
    logger.info(f"   Avg Throughput: {total_embedded/elapsed:,.0f} chunks/sec")
    logger.info("═══════════════════════════════════════════════════")


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    main()
