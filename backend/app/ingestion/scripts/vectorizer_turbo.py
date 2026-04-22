#!/usr/bin/env python3
"""
NyayaRAG Turbo Vectorizer
=========================
Key speedups vs gold standard:
  1. max_length=192 → reduces self-attention compute by ~4x (O(n²)) vs 512
  2. Prefetch thread per GPU → zero GPU idle time waiting for DB
  3. Async Qdrant upload thread → zero GPU idle time waiting for network
  4. torch.jit.trace → ~15% kernel fusion speedup
  5. Model: multilingual-e5-large (already cached, 1024-dim, pure encoder = faster than BGE-M3)
  6. Only GPUs 0, 1, 2 — GPU 3 reserved for friend
  7. Larger batch (24 at 192 tokens, safe for K80 11GB)

Target: 300-600 chunks/sec total → ~90-180 hours → 4-7 days
(vs current 205/sec at 512 tokens = 10 days)
"""
import os, sys, json, time, hashlib, logging, threading, queue
import psycopg, torch
from psycopg.rows import dict_row
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from transformers import AutoTokenizer, AutoModel
import multiprocessing as mp

# ── Config ────────────────────────────────────────────────────────────────────
POSTGRES_DSN  = "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag"
QDRANT_HOST   = "localhost"
QDRANT_PORT   = 6334
COLLECTION    = "nyayarag_documents"
MODEL_ID      = "intfloat/multilingual-e5-large"   # 1024-dim, already cached
GPUS          = [0, 2]         # GPU 1 & 3 are FREE for friend
BATCH_SIZE      = 256            # Extreme batching
MAX_LEN       = 64             # Minimal context for maximum speed
PAGE_SIZE     = 2000           # Larger pages
QDRANT_BATCH  = 1000           # Larger uploads
PREFETCH_Q    = 2              # avoid overwhelming DB
STATE_DIR     = "/home/mohanganesh/project002/backend"
LOG_FILE      = "/home/mohanganesh/project002/backend/vectorizer_turbo.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, mode='a'), logging.StreamHandler()]
)
NUM_GPUS_TOTAL = 4  # for stripe calculation

def chunk_to_qid(cid: str) -> int:
    return int.from_bytes(hashlib.sha1(cid.encode()).digest()[:8], 'big') & 0x7FFFFFFFFFFFFFFF

def state_path(gpu_id): return f"{STATE_DIR}/turbo_gpu{gpu_id}_state.json"

def load_state(gpu_id):
    p = state_path(gpu_id)
    if os.path.exists(p):
        with open(p) as f: return json.load(f)
    return {"last_chunk_id": "", "processed": 0, "uploaded": 0}

def save_state(gpu_id, s):
    p = state_path(gpu_id)
    with open(p+".tmp","w") as f: json.dump(s,f)
    os.replace(p+".tmp", p)

def mean_pool(last_hidden, attention_mask):
    mask = attention_mask.unsqueeze(-1).float()
    return (last_hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)

# ── DB Prefetch Thread ────────────────────────────────────────────────────────

def db_fetcher(gpu_id: int, start_chunk_id: str, out_q: queue.Queue, stop_evt: threading.Event):
    """Runs in a thread: streams pages from Postgres into out_q ahead of GPU."""
    log = logging.LoggerAdapter(logging.getLogger("vectorizer"), {"gpu_id": gpu_id})
    pg = psycopg.connect(POSTGRES_DSN, row_factory=dict_row)
    cur = pg.cursor()
    last_id = start_chunk_id
    stripe_idx = GPUS.index(gpu_id)
    num_stripes = len(GPUS)
    try:
        while not stop_evt.is_set():
            cur.execute("""
                SELECT chunk_id, doc_id, chunk_index, text, section_header, act_name
                FROM document_chunks
                WHERE chunk_id > %s
                  AND (chunk_index %% %s) = %s
                  AND embedding_id IS NULL
                ORDER BY chunk_id
                LIMIT %s
            """, (last_id, num_stripes, stripe_idx, PAGE_SIZE))
            rows = cur.fetchall()
            if not rows:
                out_q.put(None)  # signal done
                break
            last_id = rows[-1]['chunk_id']
            # Block if prefetch queue is full (backpressure)
            out_q.put(rows, timeout=300)
    except Exception as e:
        log.error(f"DB fetcher error: {e}", exc_info=True)
        out_q.put(None)
    finally:
        cur.close(); pg.close()

# ── Qdrant Upload Thread ──────────────────────────────────────────────────────

def qdrant_uploader(upload_q: queue.Queue, stop_evt: threading.Event, gpu_id: int):
    """Runs in a thread: uploads points to Qdrant asynchronously."""
    client = QdrantClient(host=QDRANT_HOST, grpc_port=QDRANT_PORT,
                          prefer_grpc=True, check_compatibility=False)
    log = logging.LoggerAdapter(logging.getLogger("vectorizer"), {"gpu_id": gpu_id})
    while not stop_evt.is_set():
        try:
            item = upload_q.get(timeout=5)
            if item is None: break
            points, _ = item
            for i in range(0, len(points), QDRANT_BATCH):
                client.upsert(COLLECTION, points=points[i:i+QDRANT_BATCH], wait=False)
        except queue.Empty:
            continue
        except Exception as e:
            log.error(f"Qdrant upload error: {e}")

# ── GPU Worker ────────────────────────────────────────────────────────────────

def run_gpu(gpu_id: int):
    log = logging.LoggerAdapter(logging.getLogger("vectorizer"), {"gpu_id": gpu_id})
    device = f"cuda:{gpu_id}"
    log.info(f"Starting on {device}")

    # Load model
    log.info("Loading multilingual-e5-large...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModel.from_pretrained(MODEL_ID, torch_dtype=torch.float16).to(device).eval()

    # JIT trace for faster inference (~15% speedup via kernel fusion)
    try:
        dummy = tokenizer(["passage: warm up trace text"], return_tensors="pt",
                          padding="max_length", max_length=MAX_LEN, truncation=True)
        dummy = {k: v.to(device) for k,v in dummy.items()}
        with torch.no_grad():
            traced = torch.jit.trace(model, (dummy['input_ids'], dummy['attention_mask']), strict=False)
        log.info("JIT trace successful")
        use_traced = True
    except Exception as e:
        log.warning(f"JIT trace failed ({e}), using regular model")
        use_traced = False

    log.info(f"Model loaded. VRAM: {torch.cuda.memory_allocated(gpu_id)/1e9:.1f}GB")

    state = load_state(gpu_id)
    last_id = state["last_chunk_id"]
    total_proc = state["processed"]
    total_up = state["uploaded"]
    log.info(f"Resuming from processed={total_proc:,} uploaded={total_up:,}")

    # Start prefetch thread
    prefetch_q = queue.Queue(maxsize=PREFETCH_Q)
    upload_q = queue.Queue(maxsize=10)
    stop_evt = threading.Event()

    fetch_t = threading.Thread(target=db_fetcher, args=(gpu_id, last_id, prefetch_q, stop_evt), daemon=True)
    upload_t = threading.Thread(target=qdrant_uploader, args=(upload_q, stop_evt, gpu_id), daemon=True)
    fetch_t.start()
    upload_t.start()

    t0 = time.time()
    page_buf = []

    def embed_and_queue(rows):
        nonlocal total_up
        if not rows: return
        # multilingual-e5: prepend "passage: " for document encoding
        texts = []
        for r in rows:
            hdr = f"{r.get('act_name') or ''} {r.get('section_header') or ''}".strip()
            body = r.get('text') or ''
            texts.append(f"passage: {hdr + ': ' + body if hdr else body}")

        enc = tokenizer(texts, padding=True, truncation=True, max_length=MAX_LEN, return_tensors="pt")
        with torch.no_grad():
            inp = {k: v.to(device) for k, v in enc.items()}
            if use_traced:
                out = traced(inp['input_ids'], inp['attention_mask'])
                # JIT output can be a tuple, dict, or tensor depending on trace method
                if isinstance(out, (list, tuple)):
                    hidden = out[0]
                elif isinstance(out, dict):
                    hidden = out['last_hidden_state']
                else:
                    hidden = out
            else:
                out = model(**inp)
                hidden = out.last_hidden_state
            vecs = mean_pool(hidden, inp['attention_mask'])
            vecs = torch.nn.functional.normalize(vecs, p=2, dim=1)
            vecs_np = vecs.cpu().float().numpy()

        points = [PointStruct(
            id=chunk_to_qid(r['chunk_id']),
            vector=v.tolist(),
            payload={"chunk_id": r['chunk_id'], "doc_id": r['doc_id'], "chunk_index": r.get('chunk_index',0)}
        ) for r, v in zip(rows, vecs_np)]

        upload_q.put((points, len(rows)))
        total_up += len(rows)

    try:
        while True:
            try:
                page = prefetch_q.get(timeout=60)
            except queue.Empty:
                log.warning("Prefetch queue empty — DB may be slow")
                continue

            if page is None:
                log.info("No more pages — GPU DONE")
                break
            
            log.info(f"Processing page of {len(page)} chunks...")
            for i, row in enumerate(page):
                page_buf.append(row)
                if len(page_buf) >= BATCH_SIZE:
                    embed_and_queue(page_buf)
                    page_buf = []
                if i % 100 == 0 and i > 0:
                    log.info(f"  ... Heartbeat: {i}/{len(page)} chunks in current page")

            total_proc += len(page)
            last_id = page[-1]['chunk_id']
            save_state(gpu_id, {"last_chunk_id": last_id, "processed": total_proc, "uploaded": total_up})

            elapsed = time.time() - t0
            rate = total_proc / elapsed if elapsed > 0 else 1
            eta_h = (177_000_000 / len(GPUS) - total_proc) / rate / 3600 if rate > 0 else 0
            log.info(f"GPU{gpu_id}: {total_proc:,} proc | {total_up:,} up | {rate:.0f}/s | ETA ~{eta_h:.1f}h")

        if page_buf:
            embed_and_queue(page_buf)

    except Exception as e:
        log.error(f"GPU{gpu_id} error: {e}", exc_info=True)
    finally:
        stop_evt.set()
        upload_q.put(None)
        fetch_t.join(timeout=10)
        upload_t.join(timeout=10)
        save_state(gpu_id, {"last_chunk_id": last_id, "processed": total_proc, "uploaded": total_up})
        log.info(f"GPU{gpu_id} DONE. total_proc={total_proc:,} total_up={total_up:,}")

def main():
    print(f"Turbo Vectorizer | GPUs={GPUS} | model={MODEL_ID} | batch={BATCH_SIZE} | max_len={MAX_LEN}")
    print(f"GPU 3 is FREE for your friend ✓")

    procs = []
    for g in GPUS:
        p = mp.Process(target=run_gpu, args=(g,), name=f"TurboGPU{g}", daemon=False)
        p.start()
        procs.append(p)
        print(f"Started GPU {g} PID={p.pid}")

    t0 = time.time()
    while any(p.is_alive() for p in procs):
        time.sleep(120)
        total_up = sum(load_state(g).get("uploaded",0) for g in GPUS)
        total_proc = sum(load_state(g).get("processed",0) for g in GPUS)
        elapsed_h = (time.time()-t0)/3600
        rate = total_proc / (time.time()-t0) if time.time()>t0 else 1
        eta_h = (177_000_000 - total_proc) / rate / 3600 if rate > 0 else 999
        print(f"[{elapsed_h:.1f}h] Proc={total_proc:,} Up={total_up:,} Rate={rate:.0f}/s ETA={eta_h:.1f}h")

    print("All done.")

if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    main()
