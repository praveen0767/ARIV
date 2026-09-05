import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.api.health import router as health_router
from app.api.webhooks.razorpay import router as razorpay_router
from app.api.recovery import router as recovery_router
from app.api.agent import router as agent_router

# Configure ariv.* loggers to emit INFO so Telegram notification outcomes
# (and other operational events) are visible in docker compose logs.
logging.basicConfig(
    level=logging.WARNING,  # root stays at WARNING to avoid uvicorn noise
    format="%(levelname)s [%(name)s] %(message)s",
)
logging.getLogger("ariv").setLevel(logging.INFO)

logger = logging.getLogger("ariv.startup")


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Application lifespan — runs bootstrap tasks once before serving requests."""
    # Ensure all required Qdrant collections exist (idempotent).
    try:
        from app.infrastructure.qdrant import ensure_collections
        await ensure_collections()
    except Exception as exc:
        logger.error(f"Qdrant bootstrap failed (non-fatal): {exc}")

    yield  # Application is now live and serving requests.


app = FastAPI(
    title="ARIV - Autonomous Revenue Intelligence & Value",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(razorpay_router, prefix="/webhooks", tags=["webhooks"])
app.include_router(recovery_router)
app.include_router(agent_router)

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
