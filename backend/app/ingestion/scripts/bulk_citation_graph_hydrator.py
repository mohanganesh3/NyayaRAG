#!/usr/bin/env python3
import json
import logging
from sqlalchemy import select, text
from app.db.session import SessionLocal
from app.models import LegalDocument, CitationEdge
from app.ingestion.citation_graph import CitationGraphProjector
from app.ingestion.contracts import CitationCandidate, IngestionExecutionResult
from tqdm import tqdm
from neo4j import GraphDatabase
from app.core.config import get_settings

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("graph_hydrator")

def hydrate_graph():
    settings = get_settings()
    projector = CitationGraphProjector()
    
    # Neo4j Driver
    driver = GraphDatabase.driver(
        settings.neo4j_uri, 
        auth=(settings.neo4j_user, settings.neo4j_password)
    )
    
    with SessionLocal() as session:
        # Get count of documents with citations
        total = session.scalar(select(text("count(*) FROM legal_documents WHERE jsonb_array_length(citations_made) > 0")))
        if total == 0:
            # Maybe they haven't been resolved yet? Let's check those with citations_made as raw text if any
            # Actually, we should probably scan all documents that have EITHER citations_made OR metadata that implies citations
            total = session.scalar(select(text("count(*) FROM legal_documents")))
            
        logger.info(f"Scanning {total:,} documents for citation resolution and Neo4j hydration...")
        
        batch_size = 100
        offset = 0
        
        while True:
            docs = session.scalars(
                select(LegalDocument)
                .order_by(LegalDocument.doc_id)
                .offset(offset)
                .limit(batch_size)
            ).all()
            
            if not docs:
                break
                
            for doc in docs:
                # If the document has raw citation strings in a metadata field or if we need to re-resolve
                # For this script, we assume we want to (re)resolve based on its citations_made list if it represents raw strings
                # OR we use the CitationGraphProjector.project if we have the ExecutionResult.
                # Since we are backfilling, we might need a way to turn doc.citations_made (list of strings) into CitationCandidates
                
                candidates = []
                # Fallback: if citations_made is already resolved doc_ids, we might just want to project to Neo4j
                # If it's raw text, we resolve first.
                
                # Convert citations_made (which might be raw text) into resolved doc_ids
                try:
                    resolved_doc_ids = []
                    raw_references = []
                    for c in doc.citations_made:
                        if c.startswith("doc_"):
                            resolved_doc_ids.append(c)
                        else:
                            raw_references.append(c)

                    result = projector.project(
                        session,
                        execution=IngestionExecutionResult(
                            doc_id=doc.doc_id,
                            citations=[CitationCandidate(citation_text=c, raw_text=c) for c in raw_references],
                            chunks=[],
                            errors=[]
                        ),
                        source_doc_id=doc.doc_id
                    )
                    
                    # Execute Cypher statements
                    with driver.session() as neo4j_session:
                        for cypher in result.cypher_statements:
                            neo4j_session.run(cypher)
                            
                except Exception as e:
                    logger.error(f"Error projecting {doc.doc_id}: {e}")
            
            session.commit()
            offset += batch_size
            logger.info(f"Processed {offset}/{total}...")
            if offset >= total:
                break

    driver.close()
    logger.info("Graph hydration complete.")

if __name__ == "__main__":
    hydrate_graph()
