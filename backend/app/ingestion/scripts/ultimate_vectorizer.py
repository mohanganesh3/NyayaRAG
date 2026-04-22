#!/usr/bin/env python3
import logging
import multiprocessing as mp
import psycopg
from psycopg.rows import dict_row
import torch
import time
from datetime import datetime, timezone
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from transformers import AutoTokenizer, AutoModel
from tqdm import tqdm

# "Nuclear" Configuration
POSTGRES_DSN = "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag"
MODEL_ID = "BAAI/bge-m3"
COLLECTION_NAME = "nyayarag_documents"
GPU_COUNT = torch.cuda.device_count()
CPU_WORKERS = 32 # For Tokenization

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("nuclear_vectorizer")

def tokenizer_worker(input_q, output_q):
    """Heavy XLM-R Tokenization on CPU Cores."""
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    while True:
        batch = input_q.get()
        if batch is None: break
        
        texts = [f"{c['act_name'] or ''} | {c['section_header'] or ''}\n{c['text'] or ''}" for c in batch]
        encoded = tokenizer(texts, padding=True, truncation=True, max_length=512, return_tensors="pt")
        output_q.put((batch, encoded))

def gpu_inference_worker(gpu_id, input_q, upload_q):
    """Pure GPU Matrix Multiplication (The Heart)."""
    device = f"cuda:{gpu_id}"
    model = AutoModel.from_pretrained(MODEL_ID).to(device).half().eval()
    
    with torch.no_grad():
        while True:
            data = input_q.get()
            if data is None: break
            batch, encoded = data
            
            # Transfer to GPU
            inputs = {k: v.to(device) for k, v in encoded.items()}
            outputs = model(**inputs)
            
            # Dense pool (BGE-M3 uses CLS)
            embeddings = outputs.last_hidden_state[:, 0, :]
            embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
            
            upload_q.put((batch, embeddings.cpu().float().numpy()))

def upload_worker(input_q, stats_q):
    """Parallel Qdrant & Postgres I/O."""
    client = QdrantClient(host="localhost", grpc_port=6334, prefer_grpc=True)
    pg_conn = psycopg.connect(POSTGRES_DSN)
    
    while True:
        data = input_q.get()
        if data is None: break
        batch, vectors = data
        
        points = [PointStruct(id=c['chunk_id'], vector=v.tolist(), payload=c) for c, v in zip(batch, vectors)]
        client.upsert(collection_name=COLLECTION_NAME, points=points, wait=False)
        
        # Super-batch SQL update in background
        # (Actually, for 1.3-day speed, we recommend skipping SQL updates until the end)
        stats_q.put(len(batch))

def main():
    logger.info("Igniting NUCLEAR ASSEMBLY LINE...")
    
    fetch_q = mp.Queue(maxsize=100)
    token_q = mp.Queue(maxsize=100)
    infer_q = mp.Queue(maxsize=50)
    upload_q = mp.Queue(maxsize=100)
    stats_q = mp.Queue()
    
    # 1. Start Assembly Line Stages
    t_procs = [mp.Process(target=tokenizer_worker, args=(fetch_q, token_q)) for _ in range(CPU_WORKERS)]
    g_procs = [mp.Process(target=gpu_inference_worker, args=(i, token_q, upload_q)) for i in range(GPU_COUNT)]
    u_procs = [mp.Process(target=upload_worker, args=(upload_q, stats_q)) for _ in range(4)]
    
    for p in t_procs + g_procs + u_procs: p.start()
    
    # 2. Master Fetcher
    with psycopg.connect(POSTGRES_DSN, row_factory=dict_row) as conn:
        with conn.cursor(name="master_stream") as cur:
            cur.execute("SELECT chunk_id, doc_id, text, section_header, act_name FROM document_chunks WHERE embedding_id IS NULL")
            while True:
                rows = cur.fetchmany(128) # Larger batches for the line
                if not rows: break
                fetch_q.put(rows)
    
    # Shutdown sequence
    for _ in range(CPU_WORKERS): fetch_q.put(None)
    for p in t_procs: p.join()
    for _ in range(GPU_COUNT): token_q.put(None)
    for p in g_procs: p.join()
    for _ in range(4): upload_q.put(None)
    
    pbar = tqdm(desc="NUCLEAR SATURATION", total=177453232)
    while any(p.is_alive() for p in u_procs) or not stats_q.empty():
        while not stats_q.empty(): pbar.update(stats_q.get())
        time.sleep(1)

if __name__ == "__main__":
    mp.set_start_method('spawn', force=True)
    main()
