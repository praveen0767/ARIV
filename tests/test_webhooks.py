import pytest
import hmac
import hashlib
import json
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch, MagicMock

# Ensure settings are loaded or mocked before importing app
from app.core.config import settings
settings.RAZORPAY_WEBHOOK_SECRET = "test_secret"

from app.main import app

def generate_signature(payload: str, secret: str = "test_secret") -> str:
    return hmac.new(
        secret.encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

@pytest.fixture
def valid_payload():
    return json.dumps({
        "event": "payment.failed",
        "account_id": "acc_test",
        "payload": {"payment": {"entity": {"id": "pay_test"}}}
    })

@pytest.mark.asyncio
async def test_valid_webhook(valid_payload):
    signature = generate_signature(valid_payload)
    
    with patch('app.api.webhooks.razorpay.acquire_redis_lock', new_callable=AsyncMock) as mock_redis:
        with patch('app.api.webhooks.razorpay.persist_event_pg', new_callable=AsyncMock) as mock_pg:
            mock_redis.return_value = True # Lock acquired
            mock_pg.return_value = MagicMock() # Persisted
            
            async with AsyncClient(app=app, base_url="http://test") as ac:
                response = await ac.post(
                    "/webhooks/razorpay",
                    content=valid_payload,
                    headers={
                        "x-razorpay-signature": signature,
                        "x-razorpay-event-id": "ev_123"
                    }
                )
            
            assert response.status_code == 200
            assert response.json() == {"status": "ok", "message": "accepted"}
            mock_redis.assert_called_once_with("razorpay_ev_123")
            mock_pg.assert_called_once()

@pytest.mark.asyncio
async def test_invalid_signature(valid_payload):
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post(
            "/webhooks/razorpay",
            content=valid_payload,
            headers={
                "x-razorpay-signature": "invalid_sig",
                "x-razorpay-event-id": "ev_123"
            }
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid signature"

@pytest.mark.asyncio
async def test_duplicate_event_redis_catch(valid_payload):
    signature = generate_signature(valid_payload)
    with patch('app.api.webhooks.razorpay.acquire_redis_lock', new_callable=AsyncMock) as mock_redis:
        mock_redis.return_value = False # Lock failed, duplicate
        async with AsyncClient(app=app, base_url="http://test") as ac:
            response = await ac.post(
                "/webhooks/razorpay",
                content=valid_payload,
                headers={
                    "x-razorpay-signature": signature,
                    "x-razorpay-event-id": "ev_123"
                }
            )
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "message": "duplicate"}

@pytest.mark.asyncio
async def test_duplicate_event_pg_catch(valid_payload):
    signature = generate_signature(valid_payload)
    with patch('app.api.webhooks.razorpay.acquire_redis_lock', new_callable=AsyncMock) as mock_redis:
        with patch('app.api.webhooks.razorpay.persist_event_pg', new_callable=AsyncMock) as mock_pg:
            mock_redis.return_value = True # Redis didn't catch it
            mock_pg.return_value = None # PG threw IntegrityError and returned None
            
            async with AsyncClient(app=app, base_url="http://test") as ac:
                response = await ac.post(
                    "/webhooks/razorpay",
                    content=valid_payload,
                    headers={
                        "x-razorpay-signature": signature,
                        "x-razorpay-event-id": "ev_123"
                    }
                )
            assert response.status_code == 200
            assert response.json() == {"status": "ok", "message": "duplicate"}

@pytest.mark.asyncio
async def test_malformed_payload():
    payload = "not-json"
    signature = generate_signature(payload)
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post(
            "/webhooks/razorpay",
            content=payload,
            headers={
                "x-razorpay-signature": signature,
                "x-razorpay-event-id": "ev_123"
            }
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid JSON"

@pytest.mark.asyncio
async def test_redis_unavailable_fallback(valid_payload):
    signature = generate_signature(valid_payload)
    # The actual implementation of acquire_redis_lock catches exception and returns True
    # We test the route assuming acquire_redis_lock acts correctly in that case
    with patch('app.api.webhooks.razorpay.acquire_redis_lock', new_callable=AsyncMock) as mock_redis:
        with patch('app.api.webhooks.razorpay.persist_event_pg', new_callable=AsyncMock) as mock_pg:
            mock_redis.return_value = True # Lock returned True because fallback
            mock_pg.return_value = MagicMock()
            
            async with AsyncClient(app=app, base_url="http://test") as ac:
                response = await ac.post(
                    "/webhooks/razorpay",
                    content=valid_payload,
                    headers={
                        "x-razorpay-signature": signature,
                        "x-razorpay-event-id": "ev_123"
                    }
                )
            assert response.status_code == 200
            assert response.json() == {"status": "ok", "message": "accepted"}

# Placeholders for deeper logic tests since background task testing needs worker setup
@pytest.mark.asyncio
async def test_out_of_order_event():
    # Will be tested against actual state machine transition (Phase 2)
    pass

@pytest.mark.asyncio
async def test_late_success_event():
    # Will be tested against active recovery cases (Phase 2)
    pass

@pytest.mark.asyncio
async def test_worker_retry():
    # Background worker retry logic relies on external message queue/Redis task system in real implementation
    pass

@pytest.mark.asyncio
async def test_tenant_resolution_failure(valid_payload):
    # Simulated inside `process_provider_event`
    pass

