"""app/services/embedding.py

Embedding service for ARIV vector knowledge and recovery memory.
Supports:
1. RealEmbeddingProvider (OpenAI-compatible embeddings when configured)
2. DeterministicEmbeddingProvider (deterministic context-dependent hash-based fallback for tests/benchmarks)
Explicitly tags provenance as 'openai_semantic_embedding' or 'deterministic_embedding_fallback'.
"""

import abc
import hashlib
import logging
import math
from typing import List, Tuple
from app.core.config import settings

logger = logging.getLogger("ariv.services.embedding")


class EmbeddingProvider(abc.ABC):
    """Abstract interface for generating embeddings."""

    @abc.abstractmethod
    def embed_text(self, text: str) -> List[float]:
        """Generate normalized vector embedding."""
        pass

    @abc.abstractmethod
    def get_provenance(self) -> str:
        """Return provider provenance identifier."""
        pass


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """Deterministic, context-dependent hash embedding for testing and offline benchmarks.

    NOTE: Explicitly identified as 'deterministic_embedding_fallback', NOT a semantic AI model.
    """

    def get_provenance(self) -> str:
        return "deterministic_embedding_fallback"

    def embed_text(self, text: str) -> List[float]:
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


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Real semantic embedding provider using OpenAI API.

    Gracefully falls back to DeterministicEmbeddingProvider if unconfigured or unavailable.
    """

    def __init__(self):
        self._fallback = DeterministicEmbeddingProvider()
        self._active_provenance = "openai_semantic_embedding"

    def get_provenance(self) -> str:
        return self._active_provenance

    def embed_text(self, text: str) -> List[float]:
        api_key = getattr(settings, "LLM_API_KEY", "").strip()
        if not api_key:
            self._active_provenance = "deterministic_embedding_fallback"
            return self._fallback.embed_text(text)

        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=api_key,
                base_url=getattr(settings, "LLM_BASE_URL", "").strip() or None,
                timeout=float(getattr(settings, "LLM_TIMEOUT_SECONDS", 10.0)),
            )
            model = getattr(settings, "EMBEDDING_MODEL_NAME", "text-embedding-3-small")
            # If model is not an OpenAI model, default to text-embedding-3-small with 768 dimensions
            if "/" in model:
                model = "text-embedding-3-small"

            resp = client.embeddings.create(
                input=text,
                model=model,
                dimensions=settings.EMBEDDING_DIMENSION,
            )
            vector = resp.data[0].embedding
            self._active_provenance = "openai_semantic_embedding"

            # L2-normalize
            norm = math.sqrt(sum(x * x for x in vector))
            if norm > 0:
                vector = [x / norm for x in vector]
            return vector
        except Exception as e:
            logger.warning("OpenAI embedding failed (%s); falling back to deterministic: %s", type(e).__name__, e)
            self._active_provenance = "deterministic_embedding_fallback"
            return self._fallback.embed_text(text)


class EmbeddingService:
    """Facade for generating context-dependent embeddings across ARIV."""

    _provider_override: EmbeddingProvider = None

    @classmethod
    def set_provider(cls, provider: EmbeddingProvider):
        """Allow injecting specific provider for tests or benchmarks."""
        cls._provider_override = provider

    @classmethod
    def get_provider(cls) -> EmbeddingProvider:
        if cls._provider_override is not None:
            return cls._provider_override

        provider_name = getattr(settings, "EMBEDDING_PROVIDER", "deterministic").lower()
        if provider_name in ("openai", "semantic", "real"):
            return OpenAIEmbeddingProvider()
        return DeterministicEmbeddingProvider()

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
        """Generate normalized vector embedding using configured provider."""
        return cls.get_provider().embed_text(text)

    @classmethod
    def get_provenance(cls) -> str:
        """Return current provider provenance tag."""
        return cls.get_provider().get_provenance()
