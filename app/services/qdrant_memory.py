"""app/services/qdrant_memory.py

Qdrant Vector Memory service for recovery measurements and playbooks.
Enforces:
- Strict tenant isolation on every write and retrieval.
- Exact dimension matching with the embedding model (768, Cosine).
- Payload sanitization (zero secrets, credentials, PAN/CVV).
- Graceful error handling (Qdrant failures are non-fatal to financial workflows).
"""

import logging
from typing import Dict, Any, List, Optional
from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from app.core.config import settings
from app.infrastructure.qdrant import get_qdrant
from app.services.embedding import EmbeddingService

logger = logging.getLogger("ariv.services.qdrant_memory")

# Sensitive key fragments strictly forbidden in vector payloads
FORBIDDEN_KEY_FRAGMENTS = {
    "pan", "cvv", "card", "secret", "token", "password", "key",
    "credential", "auth", "signature", "private", "ssn", "pin"
}


class QdrantIndexingError(Exception):
    """Raised when indexing into Qdrant fails."""
    pass


class QdrantMemoryService:
    COLLECTION_NAME = settings.QDRANT_COLLECTION_NAME
    DIMENSION = settings.EMBEDDING_DIMENSION
    DISTANCE = settings.QDRANT_DISTANCE_METRIC

    @classmethod
    def get_amount_bucket(cls, amount_minor: Optional[int]) -> str:
        """Categorize monetary amount into generic privacy-preserving buckets."""
        if amount_minor is None:
            return "unknown"
        amt = abs(amount_minor)
        if amt == 0:
            return "zero"
        elif amt < 1000:
            return "micro (<10.00)"
        elif amt < 10000:
            return "small (10.00-100.00)"
        elif amt < 100000:
            return "medium (100.00-1000.00)"
        elif amt < 1000000:
            return "large (1000.00-10000.00)"
        else:
            return "enterprise (>10000.00)"

    @classmethod
    def get_ttr_bucket(cls, seconds: Optional[float]) -> str:
        """Categorize time-to-recovery into discrete buckets."""
        if seconds is None:
            return "unrecovered"
        if seconds < 60:
            return "immediate (<1m)"
        elif seconds < 600:
            return "fast (1m-10m)"
        elif seconds < 3600:
            return "moderate (10m-1h)"
        elif seconds < 86400:
            return "delayed (1h-24h)"
        else:
            return "extended (>24h)"

    @classmethod
    def sanitize_payload(cls, raw_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize knowledge payload before indexing.
        Strips any sensitive data (PAN, CVV, secrets, tokens).
        Ensures only structured recovery patterns and metadata are stored.
        """
        sanitized = {}
        for k, v in raw_payload.items():
            lower_k = k.lower()
            if any(frag in lower_k for frag in FORBIDDEN_KEY_FRAGMENTS):
                logger.warning("Sanitizer stripped sensitive key '%s' from vector payload", k)
                continue
            if isinstance(v, (str, int, float, bool)) or v is None:
                sanitized[k] = v
            elif isinstance(v, (UUID,)):
                sanitized[k] = str(v)
            elif isinstance(v, dict):
                sanitized[k] = cls.sanitize_payload(v)
            elif isinstance(v, list):
                sanitized[k] = [
                    cls.sanitize_payload(item) if isinstance(item, dict) else item
                    for item in v
                    if not any(frag in str(item).lower() for frag in FORBIDDEN_KEY_FRAGMENTS)
                ]
        return sanitized

    @classmethod
    async def ensure_collection(cls, client: Optional[AsyncQdrantClient] = None) -> bool:
        """Ensure the target collection exists with the exact configured dimension and metric."""
        if client is None:
            client = await get_qdrant()

        try:
            collections = await client.get_collections()
            names = [c.name for c in collections.collections]
            if cls.COLLECTION_NAME not in names:
                distance_enum = models.Distance.COSINE
                if cls.DISTANCE.lower() == "euclid":
                    distance_enum = models.Distance.EUCLID
                elif cls.DISTANCE.lower() == "dot":
                    distance_enum = models.Distance.DOT

                await client.create_collection(
                    collection_name=cls.COLLECTION_NAME,
                    vectors_config=models.VectorParams(
                        size=cls.DIMENSION,
                        distance=distance_enum
                    )
                )
                logger.info("Created Qdrant collection %s (size=%d, distance=%s)",
                            cls.COLLECTION_NAME, cls.DIMENSION, cls.DISTANCE)
            return True
        except Exception as e:
            logger.error("Failed to ensure Qdrant collection %s: %s", cls.COLLECTION_NAME, e)
            return False

    @classmethod
    async def index_recovery_measurement(
        cls,
        measurement_id: UUID,
        tenant_id: UUID,
        payload: Dict[str, Any],
        client: Optional[AsyncQdrantClient] = None
    ) -> bool:
        """
        Index sanitized measurement metadata with mandatory tenant_id isolation.
        Vector dimension strictly matches EmbeddingService.get_dimension() (768).
        """
        if not tenant_id:
            raise ValueError("tenant_id is required for vector indexing")

        if client is None:
            client = await get_qdrant()

        # 1. Sanitize payload
        clean_payload = cls.sanitize_payload(payload)
        clean_payload["tenant_id"] = str(tenant_id)
        clean_payload["measurement_id"] = str(measurement_id)

        # 2. Build text representation for embedding
        category = clean_payload.get("failure_category", "UNKNOWN")
        domain = clean_payload.get("domain", "B2C")
        action = clean_payload.get("action_type", "NONE")
        outcome = clean_payload.get("outcome_status", "UNKNOWN")
        embed_text = f"domain:{domain} category:{category} action:{action} outcome:{outcome}"

        # 3. Generate embedding vector
        vector = EmbeddingService.embed_text(embed_text)
        if len(vector) != cls.DIMENSION:
            raise ValueError(f"Vector dimension mismatch: got {len(vector)}, expected {cls.DIMENSION}")

        # 4. Upsert into Qdrant
        try:
            await client.upsert(
                collection_name=cls.COLLECTION_NAME,
                points=[
                    models.PointStruct(
                        id=str(measurement_id),
                        vector=vector,
                        payload=clean_payload
                    )
                ]
            )
            logger.info("Successfully indexed measurement %s for tenant %s to Qdrant",
                        measurement_id, tenant_id)
            return True
        except Exception as e:
            logger.error("Qdrant upsert failed for measurement %s: %s", measurement_id, e)
            raise QdrantIndexingError(f"Qdrant indexing failed: {e}") from e

    @classmethod
    async def search_memories(
        cls,
        tenant_id: str,
        query_vector: List[float],
        limit: int = 5,
        client: Optional[AsyncQdrantClient] = None
    ) -> List[Dict[str, Any]]:
        """
        Search recovery memories with STRUCTURAL tenant_id isolation.
        A query WITHOUT a valid tenant_id is strictly rejected.
        Gracefully degrades (returns empty list) if Qdrant is unavailable.
        """
        if not tenant_id or not str(tenant_id).strip():
            raise ValueError("tenant_id is required for retrieval")

        if len(query_vector) != cls.DIMENSION:
            raise ValueError(f"Query vector dimension mismatch: got {len(query_vector)}, expected {cls.DIMENSION}")

        if client is None:
            client = await get_qdrant()

        tenant_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="tenant_id",
                    match=models.MatchValue(value=str(tenant_id).strip())
                )
            ]
        )

        try:
            results = await client.search(
                collection_name=cls.COLLECTION_NAME,
                query_vector=query_vector,
                query_filter=tenant_filter,
                limit=limit
            )
            return [hit.payload for hit in results if hit.payload]
        except Exception as e:
            logger.error("Qdrant search failed for tenant %s: %s", tenant_id, e)
            # Graceful degradation - non-fatal to application
            return []
