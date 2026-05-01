import httpx
from typing import List, Dict, Any

class QdrantService:
    def __init__(self, base_url: str = "http://localhost:6333"):
        self.base_url = base_url
        self.client = httpx.Client(timeout=10.0)
        self.collection_name = "nyayarag_documents"

    def search(
        self, 
        query_vector: List[float], 
        top_k: int = 20,
        filters: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """
        Executes a dense vector search against Qdrant.
        """
        payload = {
            "vector": query_vector,
            "limit": top_k,
            "with_payload": True,
            "with_vectors": False
        }
        
        if filters:
            payload["filter"] = filters

        response = self.client.post(
            f"{self.base_url}/collections/{self.collection_name}/points/search",
            json=payload
        )
        response.raise_for_status()
        
        data = response.json()
        return data.get("result", [])

qdrant_service = QdrantService()
