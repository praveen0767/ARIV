import redis.asyncio as redis
import logging
from app.core.config import settings

logger = logging.getLogger("ariv.redis")

redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

async def get_redis():
    return redis_client

async def check_redis_health() -> bool:
    try:
        return await redis_client.ping()
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        return False
