"""app/services/embedding.py

Embedding service for ARIV vector knowledge and recovery memory.
Produces normalized vectors of exact dimension matching settings.EMBEDDING_DIMENSION (768).
"""

import hashlib
import math
from typing import List
from app.core.config import settings


class EmbeddingService:
    @classmethod
    def get_dimension(cls) -> int:
        """Return configured embedding dimension."""
        return settings.EMBEDDING_DIMENSION

    @classmethod
    def get_model_name(cls) -> str:
        """Return configured embedding model name."""
        return settings.EMBEDDING_MODEL_NAME

    @classmethod
    def embed_text(cls, text: str) -> List[float]:
        """
        Generate a deterministic, L2-normalized vector embedding of size EMBEDDING_DIMENSION.
        Ensures exact dimension matching with the Qdrant collection, full determinism,
        and high repeatability for tests and retrieval.
        """
        dim = settings.EMBEDDING_DIMENSION
        if not text:
            return [0.0] * dim

        vector = []
        for i in range(dim):
            h = hashlib.sha256(f"{text}:{i}:{settings.EMBEDDING_MODEL_NAME}".encode("utf-8")).digest()
            val = (int.from_bytes(h[:4], "big") / 0xFFFFFFFF) * 2.0 - 1.0
            vector.append(val)

        # L2-normalize for Cosine similarity
        norm = math.sqrt(sum(x * x for x in vector))
        if norm > 0:
            vector = [x / norm for x in vector]
        return vector
