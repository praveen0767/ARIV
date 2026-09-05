import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient

from app.main import app
from app.infrastructure.database import check_db_health
from app.infrastructure.redis import check_redis_health
from app.infrastructure.qdrant import check_qdrant_health
from app.services.telegram import TelegramNotifier
from app.core.config import settings


@pytest.mark.asyncio
async def test_postgres_health_probe_success():
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn
    mock_engine.connect.return_value.__aexit__.return_value = None

    with patch("app.infrastructure.database.engine", mock_engine):
        result = await check_db_health()
        assert result is True


@pytest.mark.asyncio
async def test_postgres_health_probe_failure():
    mock_engine = MagicMock()
    mock_engine.connect.side_effect = Exception("DB connection refused")

    with patch("app.infrastructure.database.engine", mock_engine):
        result = await check_db_health()
        assert result is False


@pytest.mark.asyncio
async def test_redis_health_probe_success():
    mock_redis = AsyncMock()
    mock_redis.ping.return_value = True

    with patch("app.infrastructure.redis.redis_client", mock_redis):
        result = await check_redis_health()
        assert result is True


@pytest.mark.asyncio
async def test_redis_health_probe_failure():
    mock_redis = AsyncMock()
    mock_redis.ping.side_effect = Exception("Redis connection timeout")

    with patch("app.infrastructure.redis.redis_client", mock_redis):
        result = await check_redis_health()
        assert result is False


@pytest.mark.asyncio
async def test_qdrant_health_probe_all_collections_present():
    mock_client = AsyncMock()
    mock_colls = MagicMock()
    c1 = MagicMock()
    c1.name = "recovery_measurements"
    c2 = MagicMock()
    c2.name = "historical_cases"
    mock_colls.collections = [c1, c2]
    mock_client.get_collections.return_value = mock_colls

    with patch("app.infrastructure.qdrant.qdrant_client", mock_client):
        result = await check_qdrant_health()
        assert result == "ok"


@pytest.mark.asyncio
async def test_qdrant_health_probe_missing_historical_cases_degraded():
    mock_client = AsyncMock()
    mock_colls = MagicMock()
    c1 = MagicMock()
    c1.name = "recovery_measurements"
    mock_colls.collections = [c1]
    mock_client.get_collections.return_value = mock_colls

    with patch("app.infrastructure.qdrant.qdrant_client", mock_client):
        result = await check_qdrant_health()
        assert result == "degraded"


@pytest.mark.asyncio
async def test_qdrant_health_probe_unreachable_down():
    mock_client = AsyncMock()
    mock_client.get_collections.side_effect = Exception("Connection refused on 6333")

    with patch("app.infrastructure.qdrant.qdrant_client", mock_client):
        result = await check_qdrant_health()
        assert result == "down"


@pytest.mark.asyncio
async def test_qdrant_health_probe_empty_collection_is_healthy():
    """An empty historical_cases collection (0 vectors) is healthy infrastructure."""
    mock_client = AsyncMock()
    mock_colls = MagicMock()
    c1 = MagicMock()
    c1.name = "historical_cases"  # exists but empty
    mock_colls.collections = [c1]
    mock_client.get_collections.return_value = mock_colls

    with patch("app.infrastructure.qdrant.qdrant_client", mock_client):
        result = await check_qdrant_health()
        assert result == "ok", "Empty collection must be treated as healthy infrastructure"


@pytest.mark.asyncio
async def test_ensure_collections_noop_when_already_exists():
    """ensure_collections must NOT recreate a collection that already exists."""
    from app.infrastructure.qdrant import ensure_collections

    mock_client = AsyncMock()
    mock_colls = MagicMock()
    c1 = MagicMock()
    c1.name = "historical_cases"
    mock_colls.collections = [c1]
    mock_client.get_collections.return_value = mock_colls

    with patch("app.infrastructure.qdrant.qdrant_client", mock_client):
        await ensure_collections()
        mock_client.create_collection.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_collections_creates_missing_collection():
    """ensure_collections must create historical_cases when it is absent."""
    from app.infrastructure.qdrant import ensure_collections

    mock_client = AsyncMock()
    mock_colls = MagicMock()
    mock_colls.collections = []  # no collections at all
    mock_client.get_collections.return_value = mock_colls

    with patch("app.infrastructure.qdrant.qdrant_client", mock_client):
        await ensure_collections()
        mock_client.create_collection.assert_called_once()
        call_kwargs = mock_client.create_collection.call_args
        # collection name must be historical_cases
        assert call_kwargs.kwargs.get("collection_name") == "historical_cases" or \
               call_kwargs.args[0] == "historical_cases"


@pytest.mark.asyncio
async def test_ensure_collections_graceful_when_qdrant_unreachable():
    """ensure_collections must not raise even when Qdrant is unreachable."""
    from app.infrastructure.qdrant import ensure_collections

    mock_client = AsyncMock()
    mock_client.get_collections.side_effect = Exception("Connection refused")

    with patch("app.infrastructure.qdrant.qdrant_client", mock_client):
        # Should complete without raising
        await ensure_collections()



@pytest.mark.asyncio
async def test_telegram_health_probe_not_configured():
    with patch.object(settings, "TELEGRAM_BOT_TOKEN", ""), \
         patch.object(settings, "TELEGRAM_CHAT_ID", ""):
        result = await TelegramNotifier.check_health()
        assert result == "unknown"


@pytest.mark.asyncio
async def test_telegram_health_probe_configured_success():
    with patch.object(settings, "TELEGRAM_BOT_TOKEN", "123456:ABC-DEF"), \
         patch.object(settings, "TELEGRAM_CHAT_ID", "987654"):
        result = await TelegramNotifier.check_health()
        assert result == "ok"


@pytest.mark.asyncio
async def test_telegram_health_probe_configured_failure():
    with patch.object(settings, "TELEGRAM_BOT_TOKEN", "123456:ABC-DEF"), \
         patch.object(settings, "TELEGRAM_CHAT_ID", "987654"), \
         patch("httpx.AsyncClient.get", side_effect=Exception("Telegram API timeout")):
        result = await TelegramNotifier.check_health()
        assert result == "degraded"


@pytest.mark.asyncio
async def test_health_dependencies_endpoint_healthy():
    with patch("app.api.health.check_db_health", new_callable=AsyncMock, return_value=True), \
         patch("app.api.health.check_redis_health", new_callable=AsyncMock, return_value=True), \
         patch("app.api.health.check_qdrant_health", new_callable=AsyncMock, return_value="ok"), \
         patch("app.services.telegram.TelegramNotifier.check_health", new_callable=AsyncMock, return_value="ok"):
        
        async with AsyncClient(app=app, base_url="http://test") as ac:
            res = await ac.get("/v1/health/dependencies")
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "ok"
            assert data["postgres"] == "ok"
            assert data["redis"] == "ok"
            assert data["qdrant"] == "ok"
            assert data["telegram"] == "ok"


@pytest.mark.asyncio
async def test_health_dependencies_endpoint_core_down():
    with patch("app.api.health.check_db_health", new_callable=AsyncMock, return_value=False), \
         patch("app.api.health.check_redis_health", new_callable=AsyncMock, return_value=True), \
         patch("app.api.health.check_qdrant_health", new_callable=AsyncMock, return_value="ok"), \
         patch("app.services.telegram.TelegramNotifier.check_health", new_callable=AsyncMock, return_value="ok"):
        
        async with AsyncClient(app=app, base_url="http://test") as ac:
            res = await ac.get("/v1/health/dependencies")
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "down"
            assert data["postgres"] == "down"
            assert data["redis"] == "ok"


@pytest.mark.asyncio
async def test_health_dependencies_endpoint_graceful_degradation():
    with patch("app.api.health.check_db_health", new_callable=AsyncMock, return_value=True), \
         patch("app.api.health.check_redis_health", new_callable=AsyncMock, return_value=True), \
         patch("app.api.health.check_qdrant_health", new_callable=AsyncMock, return_value="degraded"), \
         patch("app.services.telegram.TelegramNotifier.check_health", new_callable=AsyncMock, return_value="ok"):
        
        async with AsyncClient(app=app, base_url="http://test") as ac:
            res = await ac.get("/v1/health/dependencies")
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "degraded"
            assert data["postgres"] == "ok"
            assert data["redis"] == "ok"
            assert data["qdrant"] == "degraded"
