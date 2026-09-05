import json
import logging
from fastapi import APIRouter, Request, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.infrastructure.database import get_db_session, async_session_factory
from app.core.security import verify_razorpay_signature
from app.core.idempotency import acquire_redis_lock, persist_event_pg
from app.services.ingestion import process_provider_event

logger = logging.getLogger("ariv.api.webhooks.razorpay")

router = APIRouter()


async def _process_event_with_own_session(event_id: str, provider_event_id: str, event_type: str):
    """
    Shim that opens a fresh SQLAlchemy session for background processing.

    The FastAPI request-scoped session passed via Depends(get_db_session) is
    closed when the HTTP response is sent — before the BackgroundTask coroutine
    runs. Passing that dead session into process_provider_event caused all DB
    writes for payment_link.paid (RecoveryOutcome, state transition) to fail
    silently. This shim owns its own session lifetime independently of the
    request lifecycle.
    """
    from app.domain.events import ProviderEvent
    from sqlalchemy import select

    logger.info(
        "Background processing started: event_id=%s provider_event_id=%s event_type=%s",
        event_id, provider_event_id, event_type,
    )
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(ProviderEvent).where(ProviderEvent.id == provider_event_id)
            )
            event = result.scalar_one_or_none()
            if not event:
                logger.error(
                    "Background task could not reload ProviderEvent %s — skipping", provider_event_id
                )
                return
            await process_provider_event(session, event)
            logger.info(
                "Background processing complete: event_id=%s event_type=%s", event_id, event_type
            )
    except Exception as exc:
        logger.error(
            "Background processing failed: event_id=%s event_type=%s error=%s",
            event_id, event_type, exc, exc_info=True,
        )


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Receives Razorpay webhook securely and enqueues processing.
    """
    # 1. Signature validation (preserves raw body)
    raw_body = await verify_razorpay_signature(request)
    
    try:
        payload = json.loads(raw_body.decode('utf-8'))
    except json.JSONDecodeError:
        logger.warning("Malformed JSON payload in webhook")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # 2. Event Identity
    # Note: Razorpay webhooks have 'x-razorpay-event-id' header
    event_id = request.headers.get("x-razorpay-event-id")
    if not event_id:
        logger.warning("Missing x-razorpay-event-id header")
        raise HTTPException(status_code=400, detail="Missing event ID")

    event_type = payload.get("event", "unknown")

    # Log safe identifying information — never log secrets, raw body, or signatures
    sub = payload.get("payload", {})
    plink_id = sub.get("payment_link", {}).get("entity", {}).get("id")
    payment_id = sub.get("payment", {}).get("entity", {}).get("id")
    logger.info(
        "Webhook received: event_id=%s event_type=%s payment_link_id=%s payment_id=%s",
        event_id, event_type, plink_id, payment_id,
    )

    idempotency_key = f"razorpay_{event_id}"

    # 3. Redis fast-path deduplication
    lock_acquired = await acquire_redis_lock(idempotency_key)
    if not lock_acquired:
        logger.info("Duplicate event dropped via Redis lock: %s", event_id)
        return {"status": "ok", "message": "duplicate"}

    # 4. Durable acceptance (PG fallback)
    event = await persist_event_pg(db, "razorpay", event_id, payload, idempotency_key)
    if not event:
        # Duplicate caught by PG
        return {"status": "ok", "message": "duplicate"}

    # 5. Enqueue background processing using a FRESH session (not the request-scoped one).
    #    The request session closes when the response is sent; passing it to a background
    #    task causes all writes to be lost.  The shim below opens its own session.
    background_tasks.add_task(
        _process_event_with_own_session,
        event_id,
        str(event.id),
        event_type,
    )

    # 6. Fast 2xx response
    return {"status": "ok", "message": "accepted"}
