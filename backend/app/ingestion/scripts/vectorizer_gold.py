#!/usr/bin/env python3
"""
NyayaRAG Vectorizer - Gold Standard Edition
============================================
Architecture: 4 fully independent GPU processes, each with their own
DB connection, tokenizer, model, and Qdrant client.
No shared queues = no deadlocks, no cascade failures.

Each GPU process handles one stripe of the data:
  GPU 0 → chunk_index % 4 == 0
  GPU 1 → chunk_index % 4 == 1
  GPU 2 → chunk_index % 4 == 2
  GPU 3 → chunk_index % 4 == 3

Resume-safe: tracks last processed chunk_id in a file per GPU.
Qdrant ID: sha1(chunk_id)[:16] → 64-bit int (collision-resistant).
"""
import os
import sys
import json
import time
import uuid
import hashlib
import logging
import argparse
import multiprocessing as mp

import psycopg
import torch
from psycopg.rows import dict_row
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from transformers import AutoTokenizer, AutoModel

POSTGRES_DSN    = "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag"
QDRANT_HOST     = "localhost"
QDRANT_PORT     = 6334
COLLECTION      = "nyayarag_documents"
MODEL_ID        = "BAAI/bge-m3"
BATCH_SIZE      = 16     # per GPU — K80 OOM at 32, safe at 16 with fp16
PAGE_SIZE       = 4000   # rows fetched from DB per page
QDRANT_UPLOAD   = 500    # points per Qdrant upsert
STATE_DIR       = "/home/mohanganesh/project002/backend"
LOG_FILE        = "/home/mohanganesh/project002/backend/vectorizer_gold.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [GPU%(gpu_id)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

def chunk_id_to_qdrant_id(chunk_id_str: str) -> int:
    """Convert UUID string to stable 64-bit integer for Qdrant."""
    h = hashlib.sha1(chunk_id_str.encode()).digest()
    return int.from_bytes(h[:8], 'big') & 0x7FFFFFFFFFFFFFFF  # positive int64


def state_file(gpu_id: int) -> str:
    return os.path.join(STATE_DIR, f"vectorizer_gpu{gpu_id}_state.json")


def load_state(gpu_id: int) -> dict:
    sf = state_file(gpu_id)
    if os.path.exists(sf):
        with open(sf) as f:
            return json.load(f)
    return {"last_chunk_id": "", "processed": 0, "uploaded": 0}


def save_state(gpu_id: int, state: dict):
    sf = state_file(gpu_id)
    with open(sf + ".tmp", "w") as f:
        json.dump(state, f)
    os.replace(sf + ".tmp", sf)


def mean_pool(last_hidden_state, attention_mask):
    """Mean pool over non-padding tokens."""
    mask = attention_mask.unsqueeze(-1).float()
    summed = (last_hidden_state * mask).sum(dim=1)
    counts = mask.sum(dim=1).clamp(min=1e-9)
    return summed / counts


def run_gpu_worker(gpu_id: int, num_gpus: int):
    """
    Fully independent GPU worker. Fetches its own stripe of document_chunks,
    embeds them, and uploads to Qdrant. Resumes from state file.
    """
    log = logging.LoggerAdapter(logging.getLogger("vectorizer"), {"gpu_id": gpu_id})
    log.info(f"Starting — GPU {gpu_id}/{num_gpus}")

    device = f"cuda:{gpu_id}"

    # Load model onto this GPU
    log.info(f"Loading BGE-M3 on {device}...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModel.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.float16,
    ).to(device).eval()
    log.info(f"Model loaded. Memory: {torch.cuda.memory_allocated(gpu_id)/1e9:.1f}GB")

    # Qdrant client
    qdrant = QdrantClient(
        host=QDRANT_HOST,
        grpc_port=QDRANT_PORT,
        prefer_grpc=True,
        check_compatibility=False,
    )

    # Postgres
    pg = psycopg.connect(POSTGRES_DSN, row_factory=dict_row)
    pg_plain = psycopg.connect(POSTGRES_DSN)

    # Load resume state
    state = load_state(gpu_id)
    last_id = state["last_chunk_id"]
    total_processed = state["processed"]
    total_uploaded = state["uploaded"]
    log.info(f"Resuming from chunk_id='{last_id}' | processed={total_processed:,} uploaded={total_uploaded:,}")

    t0 = time.time()
    page_buf = []  # accumulate for GPU batching

    def embed_and_upload(rows):
        nonlocal total_uploaded
        if not rows:
            return

        # Build text inputs
        texts = []
        for row in rows:
            # Rich text format for legal chunks
            header = f"{row.get('act_name') or ''} | {row.get('section_header') or ''}".strip(" |")
            body = row.get('text') or ''
            texts.append(f"{header}\n{body}" if header else body)

        # Tokenize
        enc = tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )

        # GPU inference
        with torch.no_grad():
            inputs = {k: v.to(device) for k, v in enc.items()}
            out = model(**inputs)
            # BGE-M3: use CLS token (first token) for dense retrieval
            cls = out.last_hidden_state[:, 0, :]
            vecs = torch.nn.functional.normalize(cls, p=2, dim=1)
            vecs_np = vecs.cpu().float().numpy()

        # Build Qdrant points
        points = []
        for row, vec in zip(rows, vecs_np):
            qid = chunk_id_to_qdrant_id(row['chunk_id'])
            payload = {
                "chunk_id":    row['chunk_id'],
                "doc_id":      row['doc_id'],
                "chunk_index": row.get('chunk_index', 0),
            }
            points.append(PointStruct(id=qid, vector=vec.tolist(), payload=payload))

        # Upload in sub-batches
        for i in range(0, len(points), QDRANT_UPLOAD):
            qdrant.upsert(
                collection_name=COLLECTION,
                points=points[i:i+QDRANT_UPLOAD],
                wait=False,
            )
        total_uploaded += len(points)

    try:
        while True:
            # Keyset paginate — this GPU's stripe by chunk_index % num_gpus
            cur = pg.cursor()
            cur.execute("""
                SELECT
                    c.chunk_id, c.doc_id, c.chunk_index,
                    c.text, c.section_header, c.act_name
                FROM document_chunks c
                WHERE c.chunk_id > %s
                  AND (c.chunk_index %% %s) = %s
                  AND c.embedding_id IS NULL
                ORDER BY c.chunk_id
                LIMIT %s
            """, (last_id, num_gpus, gpu_id, PAGE_SIZE))
            rows = cur.fetchall()
            cur.close()

            if not rows:
                log.info(f"No more rows — GPU {gpu_id} COMPLETE. Total processed={total_processed:,} uploaded={total_uploaded:,}")
                break

            # Accumulate into GPU batch
            for row in rows:
                page_buf.append(row)
                if len(page_buf) >= BATCH_SIZE:
                    embed_and_upload(page_buf)
                    page_buf = []

            total_processed += len(rows)
            last_id = rows[-1]['chunk_id']

            # Save state every page
            state = {"last_chunk_id": last_id, "processed": total_processed, "uploaded": total_uploaded}
            save_state(gpu_id, state)

            elapsed = time.time() - t0
            rate = total_processed / elapsed if elapsed > 0 else 0
            log.info(
                f"GPU{gpu_id}: {total_processed:,} processed | "
                f"{total_uploaded:,} uploaded | {rate:.0f}/s"
            )

        # Flush remainder
        if page_buf:
            embed_and_upload(page_buf)
            page_buf = []
            total_uploaded += len(page_buf)

    except Exception as e:
        log.error(f"GPU{gpu_id} CRASHED: {e}", exc_info=True)
    finally:
        save_state(gpu_id, {"last_chunk_id": last_id, "processed": total_processed, "uploaded": total_uploaded})
        pg.close()
        pg_plain.close()
        log.info(f"GPU{gpu_id} worker exiting. uploaded={total_uploaded:,}")


def main():
    num_gpus = torch.cuda.device_count()
    print(f"Detected {num_gpus} GPUs")
    if num_gpus == 0:
        print("ERROR: No CUDA GPUs found!")
        sys.exit(1)

    # Parse optional single-GPU mode for testing
    parser = argparse.ArgumentParser()
    parser.add_argument("--gpu", type=int, default=None, help="Run only this GPU id (for testing)")
    args, _ = parser.parse_known_args()

    if args.gpu is not None:
        run_gpu_worker(args.gpu, num_gpus)
        return

    # Launch all GPU workers as independent processes
    procs = []
    for gpu_id in range(num_gpus):
        p = mp.Process(
            target=run_gpu_worker,
            args=(gpu_id, num_gpus),
            name=f"VecGPU{gpu_id}",
            daemon=False,
        )
        p.start()
        procs.append(p)
        print(f"Started GPU {gpu_id} worker PID={p.pid}")

    # Monitor loop
    t0 = time.time()
    while any(p.is_alive() for p in procs):
        time.sleep(60)
        alive = [p.pid for p in procs if p.is_alive()]
        # Read state files for live stats
        total_up = 0
        for gpu_id in range(num_gpus):
            st = load_state(gpu_id)
            total_up += st.get("uploaded", 0)
        elapsed = (time.time() - t0) / 3600
        print(f"[{elapsed:.1f}h] Alive PIDs={alive} | Total uploaded≈{total_up:,}")

    print("All GPU workers finished.")
    # Final Qdrant count
    try:
        qdrant = QdrantClient(host=QDRANT_HOST, grpc_port=QDRANT_PORT,
                              prefer_grpc=True, check_compatibility=False)
        info = qdrant.get_collection(COLLECTION)
        print(f"Final Qdrant count: {info.points_count:,}")
    except Exception as e:
        print(f"Could not get final count: {e}")


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    main()
