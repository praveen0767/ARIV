import logging
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as rest
from app.core.config import settings

logger = logging.getLogger("ariv.qdrant")

qdrant_client = AsyncQdrantClient(url=settings.QDRANT_URL)

# Collections required by the application and their vector configuration.
# Adding a name here is sufficient to have it auto-created on startup.
REQUIRED_COLLECTIONS = {
    "historical_cases": {
        "size": settings.EMBEDDING_DIMENSION,   # 768 (BAAI/bge-base-en-v1.5)
        "distance": rest.Distance.COSINE,
    },
}


async def get_qdrant():
    return qdrant_client


async def close_qdrant():
    global qdrant_client
    if qdrant_client:
        try:
            await qdrant_client.close()
        except Exception as e:
            logger.warning(f"Error closing Qdrant client: {e}")


async def ensure_collections() -> None:
    """
    Idempotent bootstrap: create required Qdrant collections if they are absent.
    Called once at application startup.  Never deletes or overwrites existing data.
    """
    try:
        res = await qdrant_client.get_collections()
        existing = {c.name for c in res.collections}
    except Exception as e:
        logger.error(f"Qdrant bootstrap: could not list collections — {e}")
        return

    for name, cfg in REQUIRED_COLLECTIONS.items():
        if name in existing:
            logger.info(f"Qdrant: collection '{name}' already exists — skipping creation.")
            continue
        try:
            await qdrant_client.create_collection(
                collection_name=name,
                vectors_config=rest.VectorParams(
                    size=cfg["size"],
                    distance=cfg["distance"],
                ),
            )
            logger.info(
                f"Qdrant: collection '{name}' created "
                f"(dim={cfg['size']}, distance={cfg['distance']})."
            )
        except Exception as e:
            logger.error(f"Qdrant: failed to create collection '{name}': {e}")


async def check_qdrant_health() -> str:
    """
    Probes Qdrant status using the existing AsyncQdrantClient.
    Returns:
    - 'ok':       Qdrant service is reachable and all required collections exist.
    - 'degraded': Qdrant service is reachable, but a required collection is missing.
    - 'down':     Qdrant service is unreachable or encounters a connection failure.

    An empty collection (0 vectors) is treated as healthy infrastructure.
    """
    try:
        res = await qdrant_client.get_collections()
        existing_names = {c.name for c in res.collections}
        for name in REQUIRED_COLLECTIONS:
            if name not in existing_names:
                logger.warning(f"Qdrant health: required collection '{name}' missing.")
                return "degraded"
        return "ok"
    except Exception as e:
        logger.error(f"Qdrant health check failed: {e}")
        return "down"
