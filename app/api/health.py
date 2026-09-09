from fastapi import APIRouter, Response
from app.infrastructure.database import check_db_health
from app.infrastructure.redis import check_redis_health
from app.infrastructure.qdrant import check_qdrant_health

router = APIRouter()

@router.get("/ready")
async def ready():
    return {"status": "ok"}

@router.get("/health")
@router.get("/v1/health")
async def health():
    return {"status": "ok"}

@router.get("/health/ready")
@router.get("/v1/health/ready")
async def readiness(response: Response):
    """Readiness probe for orchestration platforms (e.g. Render healthCheckPath).

    Unlike the liveness endpoints (/health, /ready), this verifies the service is
    actually able to serve operational traffic: Postgres and Redis (the two core
    dependencies for financial recovery) must be reachable. Returns HTTP 200 only
    when core dependencies are healthy, otherwise HTTP 503 so the platform keeps
    the instance out of the load balancer.
    """
    db_ok = await check_db_health()
    redis_ok = await check_redis_health()
    if not (db_ok and redis_ok):
        response.status_code = 503
        return {
            "status": "not_ready",
            "postgres": "ok" if db_ok else "down",
            "redis": "ok" if redis_ok else "down",
        }
    return {
        "status": "ready",
        "postgres": "ok",
        "redis": "ok",
    }

@router.get("/health/dependencies")
@router.get("/v1/health/dependencies")
async def health_dependencies():
    db_ok = await check_db_health()
    redis_ok = await check_redis_health()
    qdrant_status = await check_qdrant_health()
    
    # Check Telegram connector health dynamically
    try:
        from app.services.telegram import TelegramNotifier
        telegram_status = await TelegramNotifier.check_health()
    except Exception:
        telegram_status = "degraded"
    
    # Overall system health:
    # PostgreSQL and Redis are core dependencies for financial recovery.
    # Qdrant and Telegram provide vector memory and operational alerts with graceful degradation.
    is_core_ok = db_ok and redis_ok
    if not is_core_ok:
        status = "down"
    elif qdrant_status in ("degraded", "down") or telegram_status == "degraded":
        status = "degraded"
    else:
        status = "ok"
    
    return {
        "status": status,
        "api": "ok",
        "postgres": "ok" if db_ok else "down",
        "redis": "ok" if redis_ok else "down",
        "qdrant": qdrant_status,
        "decision_engine": "ok",
        "policy_engine": "ok",
        "execution_worker": "ok",
        "razorpay": "ok",
        "telegram": telegram_status,
    }


@router.get("/routes/health")
@router.get("/v1/routes/health")
async def routes_health():
    """Return real-time health and degradation status of payment corridors."""
    from app.services.systemic_intelligence import SystemicIntelligenceService
    corridors = SystemicIntelligenceService.get_all_corridors()
    return {
        "status": "ok",
        "corridors": corridors,
    }
