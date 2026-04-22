#!/usr/bin/env python3
"""
NyayaRAG Hyper Vectorizer - Tiered Intelligence
===============================================
Pass 1: "Golden Chunks" (chunk_index 0, 1) - Document headers and summaries.
Pass 2: "Deep Body" (chunk_index > 1) - Full judgment text.
"""
import os, sys, json, time, hashlib, logging, multiprocessing as mp
import psycopg, torch
from psycopg.rows import dict_row
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from transformers import AutoTokenizer, AutoModel

# ── Config ────────────────────────────────────────────────────────────────────
POSTGRES_DSN  = "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag"
QDRANT_HOST   = "localhost"
QDRANT_PORT   = 6334
COLLECTION    = "nyayarag_documents"
MODEL_ID      = "intfloat/multilingual-e5-large"
GPUS          = [0, 2]         # GPU 1 & 3 are FREE for friend
BATCH_SIZE    = 64             # Tier 1 batch
MAX_LEN       = 256            # High fidelity for Golden Chunks (Headers)
PAGE_SIZE     = 2000           # Larger pages
QDRANT_BATCH  = 500            # Robust uploads
CPU_TOK_PROCS = 16
STATE_DIR     = "/home/mohanganesh/project002/backend"
LOG_FILE      = "/home/mohanganesh/project002/backend/vectorizer_turbo.log"

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s [%(processName)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, mode='a'), logging.StreamHandler()]
)
logger = logging.getLogger("hyper")

def chunk_to_qid(cid: str) -> int:
    return int.from_bytes(hashlib.sha1(cid.encode()).digest()[:8], 'big') & 0x7FFFFFFFFFFFFFFF

# ── Workers ───────────────────────────────────────────────────────────────────

def tokenizer_worker(in_q, out_q):
    name = mp.current_process().name
    logger.info(f"{name} loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    logger.info(f"{name} ready.")
    while True:
        batch = in_q.get()
        if batch is None: break
        
        texts = []
        for r in batch:
            hdr = f"{r.get('act_name') or ''} {r.get('section_header') or ''}".strip()
            body = r.get('text') or ''
            texts.append(f"passage: {hdr + ': ' + body if hdr else body}")
            
        enc = tokenizer(texts, padding=True, truncation=True, max_length=MAX_LEN, return_tensors="pt")
        enc_np = {k: v.cpu().numpy() for k,v in enc.items()}
        out_q.put((batch, enc_np))
    logger.info(f"{name} exiting.")

def gpu_worker(gpu_id, in_q, out_q):
    name = mp.current_process().name
    device = f"cuda:{gpu_id}"
    logger.info(f"{name} loading model on {device}...")
    model = AutoModel.from_pretrained(MODEL_ID, torch_dtype=torch.float16).to(device).eval()
    logger.info(f"{name} model ready.")
    
    with torch.no_grad():
        while True:
            item = in_q.get()
            if item is None: break
            batch, enc_np = item
            
            inp = {k: torch.from_numpy(v).to(device) for k,v in enc_np.items()}
            out = model(**inp)
            mask = inp['attention_mask'].unsqueeze(-1).float()
            vecs = (out.last_hidden_state * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            vecs = torch.nn.functional.normalize(vecs, p=2, dim=1).cpu().float().numpy()
            
            out_q.put((batch, vecs))
    logger.info(f"{name} exiting.")

def upload_worker(in_q, stats_q):
    name = mp.current_process().name
    logger.info(f"{name} connecting to Qdrant...")
    client = QdrantClient(host=QDRANT_HOST, grpc_port=QDRANT_PORT, prefer_grpc=True, check_compatibility=False)
    logger.info(f"{name} ready.")
    while True:
        item = in_q.get()
        if item is None: break
        batch, vecs = item
        
        points = [PointStruct(
            id=chunk_to_qid(r['chunk_id']),
            vector=v.tolist(),
            payload={"chunk_id": r['chunk_id'], "doc_id": r['doc_id'], "chunk_index": r.get('chunk_index',0)}
        ) for r, v in zip(batch, vecs)]
        
        client.upsert(COLLECTION, points=points, wait=False)
        stats_q.put(len(batch))
    logger.info(f"{name} exiting.")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    fetch_q = mp.Queue(maxsize=100)
    tok_q   = mp.Queue(maxsize=100)
    gpu_q   = mp.Queue(maxsize=50)
    stats_q = mp.Queue()
    
    procs = []
    for i in range(CPU_TOK_PROCS):
        p = mp.Process(target=tokenizer_worker, args=(fetch_q, tok_q), name=f"Tok{i}")
        p.start(); procs.append(p)
    for g in GPUS:
        p = mp.Process(target=gpu_worker, args=(g, tok_q, gpu_q), name=f"GPU{g}")
        p.start(); procs.append(p)
    for i in range(4):
        p = mp.Process(target=upload_worker, args=(gpu_q, stats_q), name=f"Up{i}")
        p.start(); procs.append(p)

    pg = psycopg.connect(POSTGRES_DSN, row_factory=dict_row)
    cur = pg.cursor()
    total = 0
    t0 = time.time()
    
    print(f"Hyper Vectorizer | GPUs={GPUS} | batch={BATCH_SIZE} | max_len={MAX_LEN}", flush=True)
    
    try:
        for tier in [1, 2]:
            print(f"--- STARTING TIER {tier} ---", flush=True)
            last_id = ""
            sp = f"{STATE_DIR}/hyper_state_tier{tier}.json"
            if os.path.exists(sp):
                with open(sp) as f: 
                    state = json.load(f)
                    last_id = state.get("last_chunk_id", "")
                    print(f"Resuming Tier {tier} from {last_id}", flush=True)
                
            while True:
                if tier == 1:
                    query = "SELECT chunk_id, doc_id, chunk_index, text, section_header, act_name FROM document_chunks WHERE chunk_id > %s AND chunk_index IN (0, 1) AND embedding_id IS NULL ORDER BY chunk_id LIMIT 2000"
                else:
                    query = "SELECT chunk_id, doc_id, chunk_index, text, section_header, act_name FROM document_chunks WHERE chunk_id > %s AND chunk_index > 1 AND embedding_id IS NULL ORDER BY chunk_id LIMIT 2000"
                    
                cur.execute(query, (last_id,))
                rows = cur.fetchall()
                if not rows: 
                    print(f"Tier {tier} DONE.", flush=True)
                    break
                
                for i in range(0, len(rows), BATCH_SIZE):
                    fetch_q.put(rows[i:i+BATCH_SIZE])
                
                last_id = rows[-1]['chunk_id']
                while not stats_q.empty(): total += stats_q.get()
                elapsed = time.time() - t0
                rate = total / elapsed if elapsed > 0 else 1
                target = 23_000_000 if tier == 1 else 177_000_000
                eta = (target-total)/rate/3600 if rate > 0 else 0
                print(f"Tier {tier} | Proc: {total:,} | Rate: {rate:.1f}/s | Tier ETA: {eta:.1f}h", flush=True)
                with open(sp, "w") as f: json.dump({"last_chunk_id": last_id}, f)
            
    finally:
        for _ in range(CPU_TOK_PROCS): fetch_q.put(None)
        # Give some time for workers to see None
        time.sleep(2)
        for p in procs: 
            if p.is_alive(): p.terminate()
        cur.close(); pg.close()

if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    main()
