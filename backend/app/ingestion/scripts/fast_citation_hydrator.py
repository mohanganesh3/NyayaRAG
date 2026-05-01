#!/usr/bin/env python3
"""
High-Velocity Citation Hydrator
1. Loads all citations from Postgres into an in-memory dictionary.
2. Streams documents with citations_made.
3. Resolves text citations to target doc_ids instantly.
4. UNWIND batches into Neo4j using multithreading.
"""
import logging
import json
import psycopg
from psycopg.rows import dict_row
from neo4j import GraphDatabase
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# Configuration
PG_DSN = "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag"
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "nyayarag_dev_password"
BATCH_SIZE = 10000
WORKERS = 1

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("/home/mohanganesh/project002/backend/fast_citation_hydrator.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("hydrator")

def load_citation_dictionary():
    logger.info("Loading citation -> doc_id lookup dictionary...")
    start = time.time()
    lookup = {}
    with psycopg.connect(PG_DSN, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            # We take the first doc_id for each citation just to have a single target
            cur.execute("""
                SELECT citation, min(doc_id) as doc_id 
                FROM legal_documents 
                WHERE citation IS NOT NULL AND citation != '' 
                GROUP BY citation
            """)
            for row in cur.fetchall():
                # Normalize spaces and lowercase for better matching
                norm_cit = " ".join(row["citation"].lower().split())
                lookup[norm_cit] = row["doc_id"]
            
            # Add neutral citations as fallback
            cur.execute("""
                SELECT neutral_citation, min(doc_id) as doc_id 
                FROM legal_documents 
                WHERE neutral_citation IS NOT NULL AND neutral_citation != '' 
                GROUP BY neutral_citation
            """)
            for row in cur.fetchall():
                norm_cit = " ".join(row["neutral_citation"].lower().split())
                if norm_cit not in lookup:
                    lookup[norm_cit] = row["doc_id"]
                    
    logger.info(f"Loaded {len(lookup):,} citations into memory in {time.time()-start:.1f}s")
    return lookup

def push_edges_to_neo4j(driver, edges_batch):
    if not edges_batch:
        return 0
    with driver.session() as session:
        session.run("""
            UNWIND $batch AS edge
            MATCH (s:LegalDocument {doc_id: edge.source})
            MATCH (t:LegalDocument {doc_id: edge.target})
            MERGE (s)-[r:CITES]->(t)
            SET r.citation_type = 'refers_to'
        """, batch=edges_batch)
    return len(edges_batch)

def main():
    logger.info("🚀 HIGH-VELOCITY CITATION HYDRATOR — STARTING")
    
    # 1. Build lookup
    lookup = load_citation_dictionary()
    
    # 2. Connect to Neo4j
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    driver.verify_connectivity()
    
    total_edges = 0
    start = time.time()
    
    edges_batch = []
    futures = []
    
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        with psycopg.connect(PG_DSN, row_factory=dict_row) as conn:
            with conn.cursor(name="citation_streamer") as cur:
                cur.execute("""
                    SELECT doc_id, citations_made 
                    FROM legal_documents 
                    WHERE citations_made::text != '[]' AND citations_made::text != 'null'
                """)
                
                rows_processed = 0
                while True:
                    rows = cur.fetchmany(10000)
                    if not rows:
                        break
                        
                    for row in rows:
                        rows_processed += 1
                        source_id = row["doc_id"]
                        citations = row["citations_made"]
                        
                        if isinstance(citations, str):
                            try:
                                citations = json.loads(citations)
                            except:
                                continue
                                
                        if not isinstance(citations, list):
                            continue
                            
                        for cit in citations:
                            if not isinstance(cit, str): continue
                            norm_cit = " ".join(cit.lower().split())
                            target_id = lookup.get(norm_cit)
                            if target_id and source_id != target_id:
                                edges_batch.append({"source": source_id, "target": target_id})
                                
                        if len(edges_batch) >= BATCH_SIZE:
                            futures.append(executor.submit(push_edges_to_neo4j, driver, list(edges_batch)))
                            edges_batch = []
                            
                            # Keep queue small
                            if len(futures) > WORKERS * 2:
                                for f in as_completed(futures):
                                    total_edges += f.result()
                                    futures.remove(f)
                                    break
                                    
                    if rows_processed % 50000 == 0:
                        logger.info(f"Scanned {rows_processed:,} docs... Projected ~{total_edges:,} edges so far")
                        
            # Drain remaining edges before closing the executor
            if edges_batch:
                futures.append(executor.submit(push_edges_to_neo4j, driver, edges_batch))
                
            for f in as_completed(futures):
                total_edges += f.result()
        
    driver.close()
    elapsed = time.time() - start
    
    logger.info("═══════════════════════════════════════════")
    logger.info(f"🏆 CITATION HYDRATION COMPLETE")
    logger.info(f"   Edges Projected: {total_edges:,}")
    logger.info(f"   Time Taken:      {elapsed/60:.1f} min")
    logger.info(f"   Throughput:      {total_edges/elapsed:,.0f} edges/sec")
    logger.info("═══════════════════════════════════════════")

if __name__ == "__main__":
    main()
