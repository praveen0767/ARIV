import logging
from typing import List, Dict, Any
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as rest
from app.infrastructure.qdrant import get_qdrant

logger = logging.getLogger("ariv.interfaces.knowledge")

class TenantAwareKnowledgeRetriever:
    """
    Semantic retrieval interface.
    Enforces strict tenant_id isolation on all queries.
    """
    
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    async def search_playbooks(self, query_vector: List[float], limit: int = 3) -> List[Dict[str, Any]]:
        client: AsyncQdrantClient = await get_qdrant()
        
        # Mandatory Tenant Filter
        tenant_filter = rest.Filter(
            must=[
                rest.FieldCondition(
                    key="tenant_id",
                    match=rest.MatchValue(value=self.tenant_id)
                )
            ]
        )
        
        try:
            results = await client.search(
                collection_name="playbooks",
                query_vector=query_vector,
                query_filter=tenant_filter,
                limit=limit
            )
            return [hit.payload for hit in results]
        except Exception as e:
            logger.error(f"Qdrant retrieval failed for tenant {self.tenant_id}: {e}")
            # Degrade gracefully - return empty context
            return []

    async def search_historical_cases(self, query_vector: List[float], limit: int = 5) -> List[Dict[str, Any]]:
        client: AsyncQdrantClient = await get_qdrant()
        
        # Mandatory Tenant Filter
        tenant_filter = rest.Filter(
            must=[
                rest.FieldCondition(
                    key="tenant_id",
                    match=rest.MatchValue(value=self.tenant_id)
                )
            ]
        )
        
        try:
            results = await client.search(
                collection_name="historical_cases",
                query_vector=query_vector,
                query_filter=tenant_filter,
                limit=limit
            )
            return [hit.payload for hit in results]
        except Exception as e:
            logger.error(f"Qdrant historical cases retrieval failed for tenant {self.tenant_id}: {e}")
            return []
