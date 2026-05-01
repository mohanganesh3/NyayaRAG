import os
import sys
import time
import logging
import multiprocessing as mp
from sqlalchemy import text
from app.db.session import get_session_factory, get_engine
from app.ingestion.sentinel import StrictCitationSentinel
from app.ingestion.citation_graph import CitationGraphProjector

# Performance Tuning
CHUNK_BATCH_SIZE = 5000  # Stream 5k chunks at a time from Master
UPSERT_BATCH_SIZE = 2500  # Batch insert 2.5k edges
NUM_WORKERS = 10  # Use the remaining 10 cores (Vectorizer uses ~36)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(processName)s: %(message)s',
    handlers=[logging.FileHandler("citation_saturation.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

def process_worker(worker_id, task_queue):
    """
    Saturates a single CPU core to extract and verify citations from the queue.
    """
    sentinel = StrictCitationSentinel()
    projector = CitationGraphProjector()
    db_factory = get_session_factory()
    db = db_factory()
    
    logger.info(f"Worker {worker_id} starting queued extraction...")
    
    try:
        edges_buffer = []
        processed_count = 0
        
        while True:
            batch = task_queue.get()
            if batch is None:
                break
                
            for chunk_id, doc_id, chunk_text, doc_cit, doc_neut_cit in batch:
                candidates = sentinel.extract_all(chunk_text)
                for cand in candidates:
                    # Self-citation guard
                    if cand.citation_text == doc_cit or cand.citation_text == doc_neut_cit:
                        continue
                        
                    # Zero-Mistake Resolution
                    target = projector.resolve_target_document(db, cand)
                    if target:
                        edges_buffer.append({
                            'source': doc_id,
                            'target': target.doc_id,
                            'type': cand.citation_type
                        })
                
                processed_count += 1
                
            if len(edges_buffer) >= UPSERT_BATCH_SIZE:
                _flush_edges(db, edges_buffer)
                edges_buffer = []
            
            if processed_count % 10000 == 0:
                logger.info(f"Worker {worker_id} processed {processed_count} chunks...")
            
        if edges_buffer:
            _flush_edges(db, edges_buffer)
            
    except Exception as e:
        logger.error(f"Worker {worker_id} failed: {e}")
    finally:
        db.close()

def _flush_edges(db, edges):
    """
    Massive batch insert into Postgres and Neo4j projection logic.
    """
    if not edges: return
    try:
        # Re-establish a direct psycopg connection for fast copying or executemany
        connection = db.connection().connection
        with connection.cursor() as cur:
            # We use an ON CONFLICT DO NOTHING to ensure idempotency
            cur.executemany(
                "INSERT INTO citation_edges (source_doc_id, target_doc_id, citation_type) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                [(e['source'], e['target'], e['type']) for e in edges]
            )
        connection.commit()
    except Exception as e:
        logger.error(f"Failed to flush edges: {e}")

def main():
    logger.info("Initializing Global Citation Saturation Pipeline...")
    
    task_queue = mp.Queue(maxsize=100)
    
    processes = []
    for i in range(NUM_WORKERS):
        p = mp.Process(target=process_worker, args=(i, task_queue), name=f"Worker-{i}")
        p.start()
        processes.append(p)
        
    db_factory = get_session_factory()
    db = db_factory()
    try:
        connection = db.connection().connection
        with connection.cursor(name="master_citation_stream") as cursor:
            # We don't need a WHERE embedding_id IS NULL here because we want to extract from everything
            cursor.execute("""
                SELECT c.chunk_id, c.doc_id, c.text, d.citation, d.neutral_citation 
                FROM document_chunks c
                JOIN legal_documents d ON c.doc_id = d.doc_id
            """)
            
            while True:
                rows = cursor.fetchmany(CHUNK_BATCH_SIZE)
                if not rows: break
                task_queue.put(rows)
    except Exception as e:
        logger.error(f"Master fetcher failed: {e}")
    finally:
        db.close()
        for _ in range(NUM_WORKERS):
            task_queue.put(None)
        
    for p in processes:
        p.join()

    logger.info("Global Citation Saturation Complete.")

if __name__ == "__main__":
    main()
