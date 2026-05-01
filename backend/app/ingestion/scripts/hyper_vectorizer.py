#!/usr/bin/env python3
import logging
import multiprocessing as mp
import os
import psycopg
from psycopg.rows import dict_row
import time
from datetime import UTC, datetime
import torch
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

# Hyper-Performance Configuration
POSTGRES_DSN = "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag"
EMBEDDING_MODEL = "BAAI/bge-m3"
COLLECTION_NAME = "nyayarag_documents"
QDRANT_HOST = "localhost"
QDRANT_GRPC_PORT = 6334

# TUNING: Tesla K80 Sweet Spots
BATCH_SIZE = 64  # Lower batch size but higher throughput on Kepler architecture
SQL_UPDATE_BATCH = 5000  # Only commit to DB every 5000 chunks to save I/O
GPU_COUNT = torch.cuda.device_count()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(processName)s: %(message)s")
logger = logging.getLogger("hyper_vectorizer")

def get_gpu_worker(gpu_id: int, task_queue: mp.Queue, stats_queue: mp.Queue):
    device = f"cuda:{gpu_id}"
    logger.info(f"Worker {gpu_id} Ignite.")
    
    try:
        # 1. Load model in FP16 to double throughput
        model = SentenceTransformer(EMBEDDING_MODEL, device=device)
        model.half() # Use FP16 for 2x speedup on K80s
        
        client = QdrantClient(host=QDRANT_HOST, grpc_port=QDRANT_GRPC_PORT, prefer_grpc=True)
        pg_conn = psycopg.connect(POSTGRES_DSN, row_factory=dict_row)
        
        pending_sql_updates = []
        
        while True:
            batch = task_queue.get()
            if batch is None: break
            
            # 2. Embedding Loop with FP16
            texts = [f"{c['act_name'] or ''} | {c['section_header'] or ''}\n{c['text'] or ''}" for c in batch]
            vectors = model.encode(texts, batch_size=len(batch), convert_to_tensor=True, normalize_embeddings=True)
            vectors_cpu = vectors.to(torch.float32).cpu().numpy() # Convert back to FP32 for Qdrant storage
            
            points = []
            for j, chunk in enumerate(batch):
                points.append(PointStruct(
                    id=chunk['chunk_id'],
                    vector=vectors_cpu[j].tolist(),
                    payload={k: chunk.get(k) for k in ['doc_id', 'chunk_id', 'court', 'citation', 'act_name']}
                ))
                pending_sql_updates.append((chunk['chunk_id'], EMBEDDING_MODEL, datetime.now(UTC), chunk['chunk_id']))
            
            # 3. High-Speed Upsert
            client.upsert(collection_name=COLLECTION_NAME, points=points, wait=False)
            
            # 4. Batched SQL Commit (The 100x Efficiency Win)
            if len(pending_sql_updates) >= SQL_UPDATE_BATCH:
                _flush_sql(pg_conn, pending_sql_updates)
                pending_sql_updates = []
                
            stats_queue.put(len(batch))
            
        if pending_sql_updates:
            _flush_sql(pg_conn, pending_sql_updates)
            
        pg_conn.close()
    except Exception as e:
        logger.error(f"Worker {gpu_id} CRASH: {e}")

def _flush_sql(conn, updates):
    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE document_chunks SET embedding_id = %s, embedding_model = %s, embedded_at = %s WHERE chunk_id = %s",
            updates
        )
    conn.commit()

def main():
    task_queue = mp.Queue(maxsize=200)
    stats_queue = mp.Queue()
    processes = [mp.Process(target=get_gpu_worker, args=(i, task_queue, stats_queue)) for i in range(GPU_COUNT)]
    for p in processes: p.start()
    
    with psycopg.connect(POSTGRES_DSN, row_factory=dict_row) as conn:
        with conn.cursor(name="master_stream") as cur:
            cur.execute("SELECT chunk_id, doc_id, text, section_header, act_name, court FROM document_chunks WHERE embedding_id IS NULL")
            while True:
                rows = cur.fetchmany(BATCH_SIZE)
                if not rows: break
                task_queue.put(rows)
                
    for _ in range(GPU_COUNT): task_queue.put(None)
    
    pbar = tqdm(desc="Hyper-Saturation Progress", unit="chunk")
    while any(p.is_alive() for p in processes) or not stats_queue.empty():
        while not stats_queue.empty(): pbar.update(stats_queue.get())
        time.sleep(1)
    pbar.close()

if __name__ == "__main__":
    mp.set_start_method('spawn', force=True)
    main()
