#!/usr/bin/env python3
"""
Neo4j Bulk Projector — High-velocity direct-SQL pipeline.
Creates document nodes and citation edges in Neo4j from PostgreSQL.
Bypasses ORM entirely for maximum throughput.
"""
import logging
import psycopg
from psycopg.rows import dict_row
from neo4j import GraphDatabase
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import time

# Configuration
PG_DSN = "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag"
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "nyayarag_dev_password"
NODE_BATCH_SIZE = 5000
EDGE_BATCH_SIZE = 2000
WORKERS = 8

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("/home/mohanganesh/project002/backend/neo4j_projection.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("neo4j_projector")


def create_constraints(driver):
    """Create indexes and constraints for performance."""
    with driver.session() as session:
        session.run("CREATE CONSTRAINT doc_id_unique IF NOT EXISTS FOR (d:LegalDocument) REQUIRE d.doc_id IS UNIQUE")
        session.run("CREATE INDEX doc_court IF NOT EXISTS FOR (d:LegalDocument) ON (d.court)")
        session.run("CREATE INDEX doc_type IF NOT EXISTS FOR (d:LegalDocument) ON (d.doc_type)")
        session.run("CREATE INDEX doc_validity IF NOT EXISTS FOR (d:LegalDocument) ON (d.current_validity)")
    logger.info("Neo4j constraints and indexes created.")


def phase1_project_nodes(driver):
    """
    Phase 1: Create all document nodes in Neo4j.
    Uses server-side cursor to stream from Postgres, UNWIND batches into Neo4j.
    """
    logger.info("═══ PHASE 1: Projecting Document Nodes ═══")
    start = time.time()
    total_projected = 0

    conn = psycopg.connect(PG_DSN, row_factory=dict_row)
    cursor = conn.cursor(name="node_streamer")
    cursor.execute("""
        SELECT doc_id, doc_type, court, citation, neutral_citation,
               current_validity, title, date_text, source_system,
               language, source_url
        FROM legal_documents
    """)

    batch = []
    while True:
        rows = cursor.fetchmany(NODE_BATCH_SIZE)
        if not rows:
            break
        batch = []
        for row in rows:
            batch.append({
                "doc_id": row["doc_id"],
                "doc_type": str(row.get("doc_type") or "JUDGMENT"),
                "court": str(row.get("court") or ""),
                "citation": str(row.get("citation") or ""),
                "neutral_citation": str(row.get("neutral_citation") or ""),
                "current_validity": str(row.get("current_validity") or "GOOD_LAW"),
                "title": str(row.get("title") or "")[:500],
                "date_text": str(row.get("date_text") or ""),
                "source_system": str(row.get("source_system") or ""),
                "language": str(row.get("language") or "en"),
            })

        with driver.session() as session:
            session.run("""
                UNWIND $batch AS doc
                MERGE (d:LegalDocument {doc_id: doc.doc_id})
                SET d.doc_type = doc.doc_type,
                    d.court = doc.court,
                    d.citation = doc.citation,
                    d.neutral_citation = doc.neutral_citation,
                    d.current_validity = doc.current_validity,
                    d.title = doc.title,
                    d.date_text = doc.date_text,
                    d.source_system = doc.source_system,
                    d.language = doc.language
            """, batch=batch)

        total_projected += len(batch)
        if total_projected % 50000 == 0:
            elapsed = time.time() - start
            rate = total_projected / elapsed if elapsed > 0 else 0
            logger.info(f"  Nodes: {total_projected:>12,} projected  ({rate:,.0f} nodes/sec)")

    cursor.close()
    conn.close()
    elapsed = time.time() - start
    logger.info(f"═══ PHASE 1 COMPLETE: {total_projected:,} nodes in {elapsed/60:.1f} min ═══")
    return total_projected


def phase2_project_edges(driver):
    """
    Phase 2: Project citation edges from the citation_edges table in Postgres.
    These are already resolved source→target pairs.
    """
    logger.info("═══ PHASE 2: Projecting Citation Edges ═══")
    start = time.time()
    total_edges = 0

    conn = psycopg.connect(PG_DSN, row_factory=dict_row)
    cursor = conn.cursor(name="edge_streamer")
    cursor.execute("""
        SELECT id, source_doc_id, target_doc_id, citation_type
        FROM citation_edges
    """)

    while True:
        rows = cursor.fetchmany(EDGE_BATCH_SIZE)
        if not rows:
            break
        batch = []
        for row in rows:
            batch.append({
                "edge_id": row["id"],
                "source": row["source_doc_id"],
                "target": row["target_doc_id"],
                "ctype": str(row.get("citation_type") or "refers_to"),
            })

        with driver.session() as session:
            session.run("""
                UNWIND $batch AS edge
                MATCH (s:LegalDocument {doc_id: edge.source})
                MATCH (t:LegalDocument {doc_id: edge.target})
                MERGE (s)-[r:CITES {edge_id: edge.edge_id}]->(t)
                SET r.citation_type = edge.ctype
            """, batch=batch)

        total_edges += len(batch)
        if total_edges % 10000 == 0:
            logger.info(f"  Edges: {total_edges:>10,} projected")

    cursor.close()
    conn.close()
    elapsed = time.time() - start
    logger.info(f"═══ PHASE 2 COMPLETE: {total_edges:,} edges in {elapsed/60:.1f} min ═══")
    return total_edges


def phase3_project_structural_edges(driver):
    """
    Phase 3: Create structural edges from document metadata.
    - overruled_by relationships
    - followed_by relationships
    - distinguished_by relationships
    These are stored as JSON arrays in the legal_documents table.
    """
    logger.info("═══ PHASE 3: Projecting Structural Edges ═══")
    start = time.time()
    total = 0

    conn = psycopg.connect(PG_DSN, row_factory=dict_row)

    # Overruled relationships
    cursor = conn.cursor(name="overruled_streamer")
    cursor.execute("""
        SELECT doc_id, overruled_by
        FROM legal_documents
        WHERE overruled_by IS NOT NULL AND overruled_by != ''
    """)
    batch = []
    while True:
        rows = cursor.fetchmany(EDGE_BATCH_SIZE)
        if not rows:
            break
        for row in rows:
            if row["overruled_by"]:
                batch.append({"source": row["doc_id"], "target": row["overruled_by"]})
        if len(batch) >= EDGE_BATCH_SIZE:
            with driver.session() as session:
                session.run("""
                    UNWIND $batch AS edge
                    MATCH (s:LegalDocument {doc_id: edge.source})
                    MATCH (t:LegalDocument {doc_id: edge.target})
                    MERGE (s)-[r:OVERRULED_BY]->(t)
                """, batch=batch)
            total += len(batch)
            batch = []
    if batch:
        with driver.session() as session:
            session.run("""
                UNWIND $batch AS edge
                MATCH (s:LegalDocument {doc_id: edge.source})
                MATCH (t:LegalDocument {doc_id: edge.target})
                MERGE (s)-[r:OVERRULED_BY]->(t)
            """, batch=batch)
        total += len(batch)
    cursor.close()

    conn.close()
    elapsed = time.time() - start
    logger.info(f"═══ PHASE 3 COMPLETE: {total:,} structural edges in {elapsed/60:.1f} min ═══")
    return total


def main():
    logger.info("🚀 NEO4J BULK PROJECTOR — STARTING")
    logger.info(f"   Neo4j: {NEO4J_URI}")
    logger.info(f"   Postgres: localhost:5432/nyayarag")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    # Verify connectivity
    driver.verify_connectivity()
    logger.info("✅ Neo4j connection verified.")

    # Step 0: Constraints
    create_constraints(driver)

    # Step 1: Nodes
    nodes = phase1_project_nodes(driver)

    # Step 2: Citation edges from resolved table
    edges = phase2_project_edges(driver)

    # Step 3: Structural edges from document metadata
    structural = phase3_project_structural_edges(driver)

    driver.close()

    logger.info("═══════════════════════════════════════════")
    logger.info(f"🏆 NEO4J PROJECTION COMPLETE")
    logger.info(f"   Nodes:            {nodes:>12,}")
    logger.info(f"   Citation Edges:   {edges:>12,}")
    logger.info(f"   Structural Edges: {structural:>12,}")
    logger.info("═══════════════════════════════════════════")


if __name__ == "__main__":
    main()
