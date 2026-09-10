import os
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.api.health import router as health_router
from app.api.webhooks.razorpay import router as razorpay_router
from app.api.recovery import router as recovery_router
from app.api.agent import router as agent_router
from app.api.mcp import router as mcp_router
from app.core.config import settings

# Configure ariv.* loggers to emit INFO so Telegram notification outcomes
# (and other operational events) are visible in docker compose logs.
logging.basicConfig(
    level=logging.WARNING,  # root stays at WARNING to avoid uvicorn noise
    format="%(levelname)s [%(name)s] %(message)s",
)
logging.getLogger("ariv").setLevel(logging.INFO)

logger = logging.getLogger("ariv.startup")


async def _knowledge_drain_loop(worker_id: str = "lifespan_drainer"):
    """Background durable KnowledgeOutbox -> Qdrant reconciliation drainer.

    The durable outbox (created transactionally with each RecoveryMeasurement) is
    the single producer for Qdrant memory vectors. Its claim-based consumer was
    never wired to run, so PENDING items could sit forever and collection renames
    were never reconciled. This loop claims PENDING/FAILED/expired items (and
    COMPLETED items pending a newer index version) and processes them, using the
    outbox row itself as the reconciliation record — never writing to Qdrant
    outside that durable path.

    ``worker_id`` names the claim holder; pass a distinct id when running from a
    dedicated Render worker service (e.g. "worker_render_drainer").
    """
    from app.services.qdrant_indexer import QdrantIndexerWorker
    from app.infrastructure.database import async_session_factory

    interval = float(getattr(settings, "KNOWLEDGE_DRAIN_INTERVAL_SECONDS", 30.0))
    drain_logger = logging.getLogger("ariv.knowledge_drain")
    while True:
        try:
            async with async_session_factory() as session:
                items = await QdrantIndexerWorker.claim_pending_items(
                    session, worker_id=worker_id, batch_size=25, lease_seconds=60
                )
                if items:
                    for item in items:
                        await QdrantIndexerWorker.process_item(session, item)
                    await session.commit()
                    drain_logger.info(
                        "Knowledge drainer processed %d item(s) in this sweep", len(items)
                    )
        except asyncio.CancelledError:
            break
        except Exception as exc:
            # A failed sweep never breaks the loop; the outbox lease reclaims
            # claimed rows and the next sweep retries them.
            drain_logger.error("Knowledge drainer sweep failed (non-fatal): %s", exc)
        await asyncio.sleep(interval)


async def _bootstrap_demo_tenant():
    """Idempotently provision the local/demo tenant mapping (DEMO_MODE only).

    The empty-database bootstrap exception in `resolve_tenant` only fires when no
    tenants exist at all.  Once a tenant (e.g. a benchmark tenant) has been
    provisioned, any later demo account would fail closed with 401 because there
    is no mapping.  This restores the intended local/demo developer experience by
    binding the configured demo account to the existing "default" tenant (or a
    fresh dedicated tenant if none exists), without weakening fail-closed tenant
    isolation or the HMAC authentication path.
    """
    from sqlalchemy import select
    from app.infrastructure.database import async_session_factory
    from app.domain.tenant import Tenant, TenantType
    from app.core.config import settings

    demo_account = (settings.DEMO_ACCOUNT_ID or "").strip()
    if not demo_account:
        return

    async with async_session_factory() as session:
        mapped = (
            await session.execute(
                select(Tenant).where(
                    Tenant.config["account_id"].as_string() == demo_account
                )
            )
        ).scalar_one_or_none()
        if mapped is not None:
            return  # Mapping already exists — idempotent.

        # Bind to the existing default tenant (legacy row with no account_id) so
        # the dashboard surfaces its existing demo cases; otherwise provision a
        # dedicated tenant (mirrors benchmark_utils.resolve_benchmark_account_id).
        default_tenant = (
            await session.execute(
                select(Tenant).where(Tenant.name == "Default Test Tenant")
            )
        ).scalar_one_or_none()
        target = default_tenant or Tenant(
            type=TenantType.CONSUMER,
            name="Default Test Tenant",
            config={},
        )
        if target.id is None:
            session.add(target)
        cfg = dict(target.config or {})
        cfg["account_id"] = demo_account
        target.config = cfg
        await session.commit()
        logger.info(
            "Demo tenant bootstrap: bound account_id=%s to tenant %s",
            demo_account,
            target.id,
        )


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Application lifespan — runs bootstrap tasks once before serving requests."""
    # Ensure all required Qdrant collections exist (idempotent).
    try:
        from app.infrastructure.qdrant import ensure_collections
        await ensure_collections()
    except Exception as exc:
        logger.error(f"Qdrant bootstrap failed (non-fatal): {exc}")

    # Provision the local/demo tenant mapping only when DEMO_MODE is enabled.
    if settings.DEMO_MODE:
        try:
            await _bootstrap_demo_tenant()
        except Exception as exc:
            logger.error(f"Demo tenant bootstrap failed (non-fatal): {exc}")

    # Start the durable KnowledgeOutbox -> Qdrant drainer (the missing consumer
    # for the durable vector-index queue). Cancelled on shutdown. When a dedicated
    # Render worker service owns the drainer, the web service can opt out via
    # KNOWLEDGE_DRAIN_ENABLED=false to avoid competing sweepers.
    drain_task = None
    if getattr(settings, "KNOWLEDGE_DRAIN_ENABLED", True):
        try:
            drain_task = asyncio.create_task(_knowledge_drain_loop())
            logger.info("KnowledgeOutbox drainer started (interval=%ss)", settings.KNOWLEDGE_DRAIN_INTERVAL_SECONDS)
        except Exception as exc:
            logger.error(f"Could not start knowledge drainer (non-fatal): {exc}")
    else:
        logger.info("KnowledgeOutbox drainer disabled on this service (KNOWLEDGE_DRAIN_ENABLED=false)")

    yield  # Application is now live and serving requests.

    if drain_task is not None:
        drain_task.cancel()
        try:
            await drain_task
        except (asyncio.CancelledError, Exception):
            pass


app = FastAPI(
    title="ARIV - Autonomous Revenue Intelligence & Value",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(razorpay_router, prefix="/webhooks", tags=["webhooks"])
app.include_router(recovery_router)
app.include_router(agent_router)
app.include_router(mcp_router)

# Mount static files and serve dashboard
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
@app.get("/dashboard")
async def serve_dashboard():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "ARIV Autonomous Recovery Engine running. Dashboard UI assets loading..."}
