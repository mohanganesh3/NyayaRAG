from typing import List, Dict, Any
from neo4j import GraphDatabase

class Neo4jService:
    def __init__(self, uri: str = "bolt://localhost:7687", user: str = "neo4j", password: str = "nyayarag_password"):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def get_doctrinal_timeline(self, anchor_doc_id: str, max_depth: int = 4) -> List[Dict[str, Any]]:
        """
        Executes a bidirectional BFS to find the doctrinal timeline for a given anchor case.
        Filters out OVERRULED edges automatically.
        """
        query = """
        MATCH (start:LegalDocument {doc_id: $anchor_doc_id})
        CALL apoc.path.expandConfig(start, {
            relationshipFilter: "CITES>",
            minLevel: 1,
            maxLevel: $max_depth,
            uniqueness: "NODE_GLOBAL"
        }) YIELD path
        WITH [node in nodes(path) | node.doc_id] AS doc_ids
        UNWIND doc_ids AS doc_id
        RETURN DISTINCT doc_id
        """
        with self.driver.session() as session:
            result = session.run(query, anchor_doc_id=anchor_doc_id, max_depth=max_depth)
            return [record["doc_id"] for record in result]

    def check_overruled_status(self, doc_id: str) -> bool:
        """
        Checks if a specific judgment has been overruled.
        """
        query = """
        MATCH (n:LegalDocument {doc_id: $doc_id})<-[r:CITES {type: 'overrules'}]-(:LegalDocument)
        RETURN count(r) > 0 AS is_overruled
        """
        with self.driver.session() as session:
            result = session.run(query, doc_id=doc_id)
            record = result.single()
            return record["is_overruled"] if record else False

neo4j_service = Neo4jService()
