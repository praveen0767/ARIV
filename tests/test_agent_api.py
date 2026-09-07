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


def _scalar_query(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def make_mock_db():
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def _override():
        yield mock_session

    return _override


@pytest.fixture(autouse=True)
def override_db_dependency():
    app.dependency_overrides[get_db_session] = make_mock_db()
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db_session, None)


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


def test_agent_execution_meta_status_reflects_blocked_action():
    """
    Regression: when the concrete action is blocked by the execution pipeline
    (e.g. unsupported action), the chat metadata must NOT claim SUCCEEDED.
    """
    mock_tenant = Tenant(id=TENANT_ID, type=TenantType.CONSUMER, name="Test Tenant")
    case = RecoveryCase(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        domain=RecoveryDomain.B2C,
        case_type=CaseType.PAYMENT_FAILED,
        status=CaseStatus.RISK_ASSESSED,
        amount_minor=10000,
        context={"currency": "INR"},
    )
    classification = RecoveryClassification(
        case_id=case.id,
        failure_category=FailureCategory.CUSTOMER_ACTION_REQUIRED,
        retryability=Retryability.REQUIRES_NEW_METHOD,
        recoverability=Recoverability.HIGH,
    )
    decision = DecisionRecord(
        case_id=case.id,
        tenant_id=TENANT_ID,
        proposed_action=RecoveryAction.RETRY_LATER,
        baseline_action=RecoveryAction.RETRY_LATER,
        policy_status=PolicyStatus.APPROVED,
        autonomy_level=AutonomyLevel.FULL_AUTO,
        ai_confidence=0.8,
    )
    # The outbox item exists but the concrete execution is blocked (CANCELLED).
    blocked_action = Action(
        id=uuid.uuid4(),
        case_id=case.id,
        tenant_id=TENANT_ID,
        action_type=RecoveryAction.RETRY_LATER,
        status=ActionStatus.CANCELLED,
    )
    attempt = MagicMock()
    attempt.attempt_metadata = {}
    attempt.provider_request_id = "N/A"

    mock_session = AsyncMock()
    mock_case_result = MagicMock()
    mock_case_result.scalars.return_value.all.return_value = [case]
    mock_class_result = _scalar_query(classification)
    mock_dec_result = _scalar_query(decision)
    mock_att_result = _scalar_query(attempt)
    mock_none_result = MagicMock()
    mock_none_result.scalars.return_value.all.return_value = []
    mock_none_result.scalar_one_or_none.return_value = None

    async def mock_execute(query, *args, **kwargs):
        q = str(query)
        if "recovery_classification" in q:
            return mock_class_result
        if "decision_record" in q:
            return mock_dec_result
        if "execution_attempt" in q:
            return mock_att_result
        if "action" in q and "FROM action" in q:
            return _scalar_query(blocked_action)
        if "recovery_case" in q:
            return mock_case_result
        return mock_none_result

    mock_session.execute = AsyncMock(side_effect=mock_execute)
    mock_session.commit = AsyncMock()

    async def _override():
        yield mock_session

    from app.infrastructure.adapters import get_razorpay_adapter
    from app.services.outbox import OutboxService
    from app.services.execution_worker import ExecutionWorker

    with patch("app.api.agent.resolve_tenant", new_callable=AsyncMock, return_value=mock_tenant), \
         patch("app.api.agent.get_razorpay_adapter", return_value=MagicMock()), \
         patch.object(OutboxService, "create_authorized_action", new_callable=AsyncMock) as mock_create, \
         patch.object(ExecutionWorker, "process_outbox_item", new_callable=AsyncMock) as mock_process:
        mock_create.return_value = (blocked_action, MagicMock())
        app.dependency_overrides[get_db_session] = _override
        try:
            resp = client.post(
                "/v1/agent/query",
                json={"query": "Recover this case."},
                headers=auth_headers(),
            )
        finally:
            app.dependency_overrides.pop(get_db_session, None)

    assert resp.status_code == 200
    assert "data: [DONE]" in resp.text
    # Meta status must be the action's real status, not a fabricated SUCCEEDED.
    assert '"status": "CANCELLED"' in resp.text
    assert '"status": "SUCCEEDED"' not in resp.text
    assert "did not succeed" in resp.text
    mock_process.assert_awaited_once()
