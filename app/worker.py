"""
app/worker.py

ARIV background worker entrypoint for managed platforms (Render).

Owns the durable background consumers that should NOT run N-times across a
horizontally scaled web service:

1. KnowledgeOutbox -> Qdrant drainer (vector memory reconciliation)
2. ExecutionOutbox poller            (durable execution backstop for provider actions)

Both consumers are claim-based (FOR UPDATE SKIP LOCKED + leases), so multiple
worker replicas are still safe, but a single dedicated worker service is the
recommended layout. Run with:

    python -m app.worker

While a dedicated worker is running, set KNOWLEDGE_DRAIN_ENABLED=false on the
web service so the in-process lifespan drainer does not compete with it.
"""

import asyncio
import logging

logger = logging.getLogger("ariv.worker")


async def knowledge_drain_loop(worker_id: str = "worker_render_drainer") -> None:
    """Reconcile the durable KnowledgeOutbox into Qdrant, forever."""
    from app.main import _knowledge_drain_loop

    await _knowledge_drain_loop(worker_id=worker_id)


async def execution_poll_loop(worker_id: str = "worker_render_poller", interval_seconds: float = 5.0) -> None:
    """Durable ExecutionOutbox backstop: claim and execute authorized actions.

    The web request path already attempts immediate governed execution after an
    action is authorized (decision engine / agent). This poller guarantees that
    any item left PENDING (e.g. a deploy interrupted the request, or a provider
    returned UNKNOWN) is claimed and reconciled by a durable consumer.
    """
    from app.infrastructure.adapters import get_razorpay_adapter
    from app.infrastructure.database import async_session_factory
    from app.services.execution_worker import ExecutionWorker

    worker = ExecutionWorker(worker_id=worker_id, provider_adapter=get_razorpay_adapter())
    while True:
        try:
            async with async_session_factory() as session:
                processed = await worker.poll_once(session)
                await session.commit()
            if processed:
                logger.info("Execution poller processed %d outbox item(s)", processed)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            # A failed sweep never breaks the loop; claimed rows are reclaimed
            # by lease expiry and the next sweep retries them.
            logger.error("Execution poller sweep failed (non-fatal): %s", exc)
        await asyncio.sleep(interval_seconds)


def _execution_poller_enabled() -> bool:
    """Only start the execution poller when provider credentials are configured.

    With no Razorpay adapter, preflight would correctly cancel any executed
    action but there is nothing legitimate to execute, so skip claiming entirely
    and keep the action PENDING until credentials exist.
    """
    from app.infrastructure.adapters import get_razorpay_adapter

    return get_razorpay_adapter() is not None


async def run() -> None:
    tasks = [asyncio.create_task(knowledge_drain_loop())]

    if _execution_poller_enabled():
        tasks.append(asyncio.create_task(execution_poll_loop()))
    else:
        logger.warning(
            "Execution poller disabled: no Razorpay provider credentials configured "
            "(set RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET). Authorized actions will "
            "remain in the ExecutionOutbox until credentials are configured."
        )

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
        raise
    except Exception as exc:
        logger.fatal("ARIV worker aborted: %s", exc)
        for task in tasks:
            task.cancel()
        raise


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )
    logging.getLogger("ariv").setLevel(logging.INFO)
    asyncio.run(run())