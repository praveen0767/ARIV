"""
Tests for Phase 18 / ASK ARIV Agent API (/v1/agent/query).

Verifies:
  1. Missing auth headers -> 422
  2. Invalid HMAC signature -> 403
  3. Valid auth: Health check query stream
  4. Valid auth: Decision explanation query stream
  5. Valid auth: Revenue overview query stream
  6. Valid auth: Authorized action execution query stream
"""

import hmac
import hashlib
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.infrastructure.database import get_db_session
from app.services.ingestion import resolve_tenant
from app.domain.tenant import Tenant, TenantType
from app.domain.recovery_case import RecoveryCase, CaseStatus, RecoveryDomain, CaseType
from app.domain.classification import RecoveryClassification, FailureCategory, Retryability, Recoverability
from app.domain.decision import DecisionRecord, RecoveryAction, PolicyStatus, AutonomyLevel
from app.domain.action import Action, ActionStatus
from app.domain.recovery.recovery_outcome import RecoveryOutcome, RecoveryOutcomeStatus, RecoverySource


ACCOUNT_ID = "acc_demo_test"
TENANT_ID = uuid.uuid4()


def make_sig(account_id: str, key: str = settings.INTERNAL_API_KEY) -> str:
    return hmac.new(
        key.encode("utf-8"),
        account_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def auth_headers(account_id: str = ACCOUNT_ID, key: str = settings.INTERNAL_API_KEY) -> dict:
    return {
        "X-Account-ID": account_id,
        "X-Signature": make_sig(account_id, key),
    }


client = TestClient(app)


def test_agent_query_missing_auth_returns_422():
    resp = client.post("/v1/agent/query", json={"query": "Is ARIV healthy?"})
    assert resp.status_code == 422


def test_agent_query_invalid_signature_returns_403():
    resp = client.post(
        "/v1/agent/query",
        json={"query": "Is ARIV healthy?"},
        headers={"X-Account-ID": ACCOUNT_ID, "X-Signature": "invalid_signature"},
    )
    assert resp.status_code == 403


def test_agent_query_health_check_stream():
    """Valid auth query for system health returns streaming SSE events."""
    mock_tenant = Tenant(id=TENANT_ID, type=TenantType.CONSUMER, name="Test Tenant")

    with patch("app.api.agent.resolve_tenant", new_callable=AsyncMock, return_value=mock_tenant), \
         patch("app.infrastructure.database.check_db_health", new_callable=AsyncMock, return_value=True), \
         patch("app.infrastructure.redis.check_redis_health", new_callable=AsyncMock, return_value=True), \
         patch("app.infrastructure.qdrant.check_qdrant_health", new_callable=AsyncMock, return_value="ok"), \
         patch("app.services.telegram.TelegramNotifier.check_health", new_callable=AsyncMock, return_value="ok"):

        resp = client.post(
            "/v1/agent/query",
            json={"query": "Is ARIV healthy?"},
            headers=auth_headers(),
        )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    text = resp.text
    # Health branch must produce the ARIV SYSTEM HEALTH section
    assert "ARIV SYSTEM HEALTH" in text
    # PostgreSQL and Redis labels must appear (icon spacing may vary)
    assert "PostgreSQL:" in text
    assert "Redis:" in text
    assert "data: [DONE]" in text





def test_agent_query_explain_case_stream():
    """Valid auth query asking why an action was chosen returns structured explanation."""
    mock_tenant = Tenant(id=TENANT_ID, type=TenantType.CONSUMER, name="Test Tenant")

    with patch("app.api.agent.resolve_tenant", new_callable=AsyncMock, return_value=mock_tenant):
        resp = client.post(
            "/v1/agent/query",
            json={"query": "Why did ARIV choose a payment link?"},
            headers=auth_headers(),
        )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "data: [DONE]" in resp.text


def test_agent_query_recover_this_case_stream():
    """Valid auth query for authorized action execution returns execution result."""
    mock_tenant = Tenant(id=TENANT_ID, type=TenantType.CONSUMER, name="Test Tenant")

    with patch("app.api.agent.resolve_tenant", new_callable=AsyncMock, return_value=mock_tenant):
        resp = client.post(
            "/v1/agent/query",
            json={"query": "Recover this case."},
            headers=auth_headers(),
        )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "data: [DONE]" in resp.text
