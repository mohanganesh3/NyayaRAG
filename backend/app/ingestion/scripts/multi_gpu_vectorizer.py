#!/usr/bin/env python3
import json
import logging
import multiprocessing as mp
import os
import psycopg
from psycopg.rows import dict_row
import time
from datetime import UTC, datetime
from pathlib import Path

import torch
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

# Configuration
POSTGRES_DSN = "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag"
EMBEDDING_MODEL = "BAAI/bge-m3"
COLLECTION_NAME = "nyayarag_documents"
QDRANT_HOST = "localhost"
QDRANT_GRPC_PORT = 6334
BATCH_SIZE = 256  # Doubled for maximum GPU saturation
GPU_COUNT = torch.cuda.device_count() if torch.cuda.is_available() else 1

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(processName)s: %(message)s")
logger = logging.getLogger("gpu_vectorizer")

def get_gpu_worker(gpu_id: int, task_queue: mp.Queue, stats_queue: mp.Queue):
    """Worker process that uses a specific GPU to embed documents from Postgres."""
    device = f"cuda:{gpu_id}" if torch.cuda.is_available() else "cpu"
    logger.info(f"Worker started on {device}")
    
    try:
        # 1. Initialize Model
        model = SentenceTransformer(EMBEDDING_MODEL, device=device)
        
        # 2. Initialize Qdrant Client (using gRPC for performance)
        client = QdrantClient(host=QDRANT_HOST, grpc_port=QDRANT_GRPC_PORT, prefer_grpc=True)
        
        pg_conn = psycopg.connect(POSTGRES_DSN, row_factory=dict_row)
        
        while True:
            batch = task_queue.get()
            if batch is None:
                break
            
            process_batch_with_gpu(batch, model, client, pg_conn, stats_queue)
            
        pg_conn.close()
    except Exception as e:
        logger.error(f"Worker on {device} failed: {e}")
    finally:
        logger.info(f"Worker on {device} shutting down.")

def process_batch_with_gpu(batch, model: SentenceTransformer, client: QdrantClient, pg_conn, stats_queue: mp.Queue):
    """Processes a batch of chunks, embedding them and updating both Qdrant and Postgres."""
    try:
        texts = [build_text(c) for c in batch]
        
        # Embed
        vectors = model.encode(texts, batch_size=len(batch), normalize_embeddings=True)
        
        # Prepare Qdrant Points
        points = []
        for j, chunk in enumerate(batch):
            point_id = chunk['chunk_id']
            vector_list = vectors[j].tolist()
            
            points.append(
                PointStruct(
                    id=point_id,
                    vector=vector_list,
                    payload={
                        "doc_id": chunk['doc_id'],
                        "chunk_id": chunk['chunk_id'],
                        "court": chunk.get('court'),
                        "date": str(chunk.get('date')),
                        "citation": chunk.get('citation'),
                        "current_validity": chunk.get('current_validity'),
                        "act_name": chunk.get('act_name'),
                        "section_header": chunk.get('section_header')
                    }
                )
            )
        
        # Bulk Upsert to Qdrant
        client.upsert(collection_name=COLLECTION_NAME, points=points, wait=False)
            
        # Update Postgres (mark as embedded)
        timestamp = datetime.now(UTC)
        with pg_conn.cursor() as cur:
            cur.executemany(
                "UPDATE document_chunks SET embedding_id = %s, embedding_model = %s, embedded_at = %s WHERE chunk_id = %s",
                [(c['chunk_id'], EMBEDDING_MODEL, timestamp, c['chunk_id']) for c in batch]
            )
        pg_conn.commit()
        
        stats_queue.put(len(batch))
    except Exception as e:
        logger.error(f"Failed to process batch: {e}")

def build_text(chunk) -> str:
    """Combines metadata and text for optimal embedding."""
    header = chunk.get('section_header') or ""
    act = chunk.get('act_name') or ""
    body = chunk.get('text') or ""
    return f"{act} | {header}\n{body}".strip()

def main():
    logger.info(f"Connecting to Postgres to fetch pending chunks...")
    
    # 1. Start Workers
    task_queue = mp.Queue(maxsize=100)
    stats_queue = mp.Queue()
    processes = []
    for i in range(GPU_COUNT):
        p = mp.Process(target=get_gpu_worker, args=(i, task_queue, stats_queue), name=f"GPU-Worker-{i}")
        p.start()
        processes.append(p)
    
    # 2. Feed tasks from Postgres (using cursor pagination)
    try:
        with psycopg.connect(POSTGRES_DSN, row_factory=dict_row) as conn:
            with conn.cursor(name="chunk_iterator") as cur:
                # Use a server-side cursor for large datasets
                cur.execute("""
                    SELECT chunk_id, doc_id, text, section_header, act_name, court, date, citation, current_validity
                    FROM document_chunks 
                    WHERE (embedding_id IS NULL OR embedding_model <> %s)
                """, (EMBEDDING_MODEL,))
                
                batch = []
                while True:
                    rows = cur.fetchmany(BATCH_SIZE)
                    if not rows:
                        break
                    task_queue.put(rows)
                    
    except Exception as e:
        logger.error(f"Error fetching from Postgres: {e}")
    finally:
        # Finish
        for _ in range(GPU_COUNT):
            task_queue.put(None)

    # 3. Monitor Progress
    pbar = tqdm(desc="Embedding Chunks", unit="chunk")
    while any(p.is_alive() for p in processes) or not stats_queue.empty():
        while not stats_queue.empty():
            count = stats_queue.get()
            pbar.update(count)
        time.sleep(1)
            
    pbar.close()
    logger.info("Embedding Phase Complete.")

if __name__ == "__main__":
    mp.set_start_method('spawn', force=True)
    main()

