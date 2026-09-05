import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from app.infrastructure.redis import get_redis
from app.domain.events import ProviderEvent

logger = logging.getLogger("ariv.idempotency")

async def acquire_redis_lock(idempotency_key: str, ttl: int = 86400) -> bool:
    """Fast-path idempotency check using Redis SET NX."""
    try:
        redis_client = await get_redis()
        # SET NX returns True if set, False if it already exists
        return await redis_client.set(f"idemp:{idempotency_key}", "locked", nx=True, ex=ttl)
    except Exception as e:
        logger.warning(f"Redis idempotency check failed, falling back to PostgreSQL: {e}")
        # If Redis fails, we must fall back to PG uniqueness constraint
        return True 

async def persist_event_pg(session: AsyncSession, provider: str, external_id: str, payload: dict, idempotency_key: str) -> ProviderEvent:
    """Authoritative idempotency check using PostgreSQL."""
    try:
        event = ProviderEvent(
            provider=provider,
            external_id=external_id,
            payload=payload,
            idempotency_key=idempotency_key
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return event
    except IntegrityError as e:
        await session.rollback()
        logger.info(f"Duplicate event detected in PostgreSQL for key {idempotency_key}")
        # We can either return None or raise an exception. Let's return None to indicate duplicate.
        return None
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to persist event in PostgreSQL: {e}")
        raise
