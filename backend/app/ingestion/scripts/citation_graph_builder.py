#!/usr/bin/env python3
# /// script
# dependencies = [
#   "psycopg[binary]",
#   "neo4j",
#   "sqlalchemy",
# ]
# ///

import logging
from neo4j import GraphDatabase
from sqlalchemy.orm import Session
from app.db.session import get_session_factory
from app.ingestion.citation_graph import CitationGraphProjector
from app.ingestion.contracts import IngestionExecutionResult
from app.models import LegalDocument

# Configuration
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "nyayarag_dev_password"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("graph_builder")

def main():
    logger.info("Initializing Citation Graph Builder")
    
    # 1. Connect to Neo4j
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    # 2. Get SQLAlchemy session
    session_factory = get_session_factory()
    projector = CitationGraphProjector()
    
    with session_factory() as session:
        # Fetch all documents to process their citations
        # To avoid memory issues for 12.6M, we batch
        BATCH_SIZE = 1000
        offset = 0
        
        while True:
            docs = session.query(LegalDocument).offset(offset).limit(BATCH_SIZE).all()
            if not docs:
                break
                
            for doc in docs:
                # In a real ingestion execution, execution object is provided.
                # Here we simulate by checking the doc's internal citation mentions.
                # Projector.project would normally be called during original ingestion.
                # This script is for RE-CONSTRUCTING the graph from existing Postgres data.
                
                try:
                    # We would need to extract citations from doc.text if they aren't pre-saved.
                    # For this 100% completion task, we rely on the projector's build_neo4j_projection.
                    statements = projector.build_neo4j_projection(session, doc.doc_id)
                    
                    with driver.session() as neo4j_sess:
                        for stmt in statements:
                            neo4j_sess.run(stmt)
                            
                except Exception as e:
                    logger.warning(f"Failed to project doc {doc.doc_id}: {e}")
            
            offset += BATCH_SIZE
            logger.info(f"Processed {offset} documents for graph")

    driver.close()
    logger.info("Graph Construction Complete")

if __name__ == "__main__":
    main()
