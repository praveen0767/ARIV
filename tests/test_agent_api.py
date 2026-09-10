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
from app.domain.system_settings import SystemSetting
from app.domain.recovery.recovery_outcome import RecoveryOutcome, RecoveryOutcomeStatus, RecoverySource
from app.api.agent import is_aggregate_metrics_query
from app.api.agent import is_conversational_greeting


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

    # Mock SystemSetting for execution kill switch (must be True to allow execution)
    mock_setting = MagicMock(spec=SystemSetting)
    mock_setting.value = True
    mock_setting.key = "execution_enabled"

    # Mock tenant for gateway's _verify_tenant_and_case
    mock_tenant_result = _scalar_query(mock_tenant)

    mock_session = AsyncMock()
    mock_case_result = MagicMock()
    mock_case_result.scalars.return_value.all.return_value = [case]
    mock_case_result.scalar_one_or_none.return_value = case
    mock_class_result = _scalar_query(classification)
    mock_dec_result = _scalar_query(decision)
    mock_att_result = _scalar_query(attempt)
    mock_none_result = MagicMock()
    mock_none_result.scalars.return_value.all.return_value = []
    mock_none_result.scalar_one_or_none.return_value = None

    async def mock_execute(query, *args, **kwargs):
        q = str(query)
        if "system_setting" in q.lower() or "execution_enabled" in q:
            return _scalar_query(mock_setting)
        if "FROM tenant" in q or "from tenant" in q.lower():
            return mock_tenant_result
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


# ---------------------------------------------------------------------------
# Aggregate / workspace metrics intent routing (highest precedence)
# ---------------------------------------------------------------------------

def test_aggregate_metrics_query_intent():
    """Workspace-level questions (including typos) must classify as aggregate."""
    assert is_aggregate_metrics_query("how many payments recoveredd untill now?")
    assert is_aggregate_metrics_query("how much revenue have we recovered overall?")
    assert is_aggregate_metrics_query("how many recoveries have happened entirely?")
    assert is_aggregate_metrics_query("what is our recovery rate?")
    assert is_aggregate_metrics_query("how much revenue is at risk?")
    assert is_aggregate_metrics_query("how much revenue do we have at risk?")
    assert is_aggregate_metrics_query("how many payments were recovered so far?")

    # Post-fix coverage: exact production phrases that previously fell through
    # to the default/case branches.
    assert is_aggregate_metrics_query("how many payments recovered until now?")
    assert is_aggregate_metrics_query("how much was recovered?")
    assert is_aggregate_metrics_query("how much recovered?")
    assert is_aggregate_metrics_query("how many payments were recovered?")
    assert is_aggregate_metrics_query("total recovered")
    assert is_aggregate_metrics_query("total recovered amount across all cases?")
    assert is_aggregate_metrics_query("what is the recovered amount?")
    assert is_aggregate_metrics_query("how much amount recovered?")


def test_case_pinned_queries_are_not_aggregate():
    """Queries that reference a specific case must stay case-scoped."""
    assert not is_aggregate_metrics_query("what's happening with this case?")
    assert not is_aggregate_metrics_query("was the payment actually recovered?")
    assert not is_aggregate_metrics_query("where is the payment link?")
    assert not is_aggregate_metrics_query("why is this case still pending?")
    assert not is_aggregate_metrics_query("recover this case")
    assert not is_aggregate_metrics_query("how much revenue is at risk for that case?")
    assert not is_aggregate_metrics_query(
        "what happened with 516244d8-e20d-4ef5-af5d-1cc02eac075e?"
    )


def test_aggregate_query_answered_from_case_page_context():
    """
    Regression: aggregate questions opened from a specific case drawer
    (case_id + /cases/{id} route) must return workspace metrics, NOT the
    single-case diagnosis that used to hijack the response.
    """
    mock_tenant = Tenant(id=TENANT_ID, type=TenantType.CONSUMER, name="Test Tenant")
    case_id = str(uuid.uuid4())

    with patch("app.api.agent.resolve_tenant", new_callable=AsyncMock, return_value=mock_tenant):
        resp = client.post(
            "/v1/agent/query",
            json={
                "query": "how many payments recoveredd untill now?",
                "current_route": f"/cases/{case_id}",
                "case_id": case_id,
            },
            headers=auth_headers(),
        )

    assert resp.status_code == 200
    assert "ARIV WORKSPACE RECOVERY METRICS" in resp.text
    assert "Payments Recovered:   0" in resp.text
    assert "STATUS & DIAGNOSIS" not in resp.text


def test_case_pinned_query_keeps_own_branch():
    """Case-control intents must NOT be rerouted to the aggregate branch."""
    mock_tenant = Tenant(id=TENANT_ID, type=TenantType.CONSUMER, name="Test Tenant")

    with patch("app.api.agent.resolve_tenant", new_callable=AsyncMock, return_value=mock_tenant):
        resp = client.post(
            "/v1/agent/query",
            json={"query": "Recover this case."},
            headers=auth_headers(),
        )

    assert resp.status_code == 200
    assert "No recovery cases found in this workspace." in resp.text
    assert "WORKSPACE RECOVERY METRICS" not in resp.text


def test_aggregate_how_much_was_recovered_answered_from_case_page():
    """
    'how much was recovered?' opened from a specific case drawer must return the
    authoritative workspace metrics, not the single-case diagnosis that used to
    hijack the response.
    """
    mock_tenant = Tenant(id=TENANT_ID, type=TenantType.CONSUMER, name="Test Tenant")
    case_id = str(uuid.uuid4())

    with patch("app.api.agent.resolve_tenant", new_callable=AsyncMock, return_value=mock_tenant):
        resp = client.post(
            "/v1/agent/query",
            json={
                "query": "how much was recovered?",
                "current_route": f"/cases/{case_id}",
                "case_id": case_id,
            },
            headers=auth_headers(),
        )

    assert resp.status_code == 200
    assert "ARIV WORKSPACE RECOVERY METRICS" in resp.text
    assert "STATUS & DIAGNOSIS" not in resp.text


def test_agent_stream_emits_structured_error_event():
    """
    A failure inside the stream must surface as a structured SSE `error` event
    (code + message) followed by DONE — never a bare connection close.
    """
    mock_tenant = Tenant(id=TENANT_ID, type=TenantType.CONSUMER, name="Test Tenant")

    async def _failing_execute(*a, **k):
        raise RuntimeError("simulated operational failure")

    mock_db = AsyncMock()
    mock_db.execute = _failing_execute

    async def _override():
        yield mock_db

    app.dependency_overrides[get_db_session] = _override
    try:
        with patch("app.api.agent.resolve_tenant", new_callable=AsyncMock, return_value=mock_tenant):
            resp = client.post(
                "/v1/agent/query",
                json={"query": "Is ARIV healthy?"},
                headers=auth_headers(),
            )
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    assert resp.status_code == 200
    assert '"type": "error"' in resp.text
    assert 'OPERATIONAL_ERROR' in resp.text
    assert "simulated operational failure" in resp.text
    assert "[DONE]" in resp.text


# ---------------------------------------------------------------------------
# BRANCH GRT: conversational greeting / identity / capability routing
# ---------------------------------------------------------------------------


def test_is_conversational_greeting_true_positives():
    greetings = [
        "hi",
        "hello",
        "hey",
        "howdy",
        "good morning",
        "good evening",
        "how are you",
        "what can you do?",
        "what do you do?",
        "who are you?",
        "are you ARIV?",
        "thank you",
        "thanks a lot",
        "help",
        "Hi",
        "HELLO THERE",
    ]
    for g in greetings:
        assert is_conversational_greeting(g), f"expected greeting for: {g!r}"


def test_is_conversational_greeting_false_for_operational_queries():
    not_greetings = [
        "how much was recovered?",
        "how many payments recovered until now?",
        "total recovered",
        "what's happening with this case?",
        "was the payment actually recovered?",
        "where is the payment link?",
        "recover this case.",
        "why is this case still pending?",
        "is ariv healthy?",
        "who's pending?",
        "how would ariv recover this case?",
        "hey, recover this case.",
        "hi, where is the payment link?",
        "this case needs a check",
        "long " * 40,
        "",
        "tell me about quantum physics",
    ]
    for ng in not_greetings:
        assert not is_conversational_greeting(ng), f"expected NOT greeting for: {ng!r}"


def test_greeting_answered_in_empty_workspace():
    """Bare greetings must be answered even when the tenant has zero cases and
    no drawer context — beating the 'No recovery cases found' guard."""
    mock_tenant = Tenant(id=TENANT_ID, type=TenantType.CONSUMER, name="Test Tenant")

    with patch("app.api.agent.resolve_tenant", new_callable=AsyncMock, return_value=mock_tenant):
        resp = client.post(
            "/v1/agent/query",
            json={"query": "hi"},
            headers=auth_headers(),
        )

    assert resp.status_code == 200
    assert "Hey! I'm ASK ARIV" in resp.text
    assert "No recovery cases found in this workspace." not in resp.text
    assert "RECOVERY METRICS" not in resp.text
    assert "STATUS & DIAGNOSIS" not in resp.text
    assert "[DONE]" in resp.text


def test_greeting_never_hijacked_by_case_drawer_context():
    """A greeting sent from a case page drawer must NOT be treated as a request
    to diagnose that case — conversational intent wins, case text is absent."""
    mock_tenant = Tenant(id=TENANT_ID, type=TenantType.CONSUMER, name="Test Tenant")
    case_id = str(uuid.uuid4())

    with patch("app.api.agent.resolve_tenant", new_callable=AsyncMock, return_value=mock_tenant):
        resp = client.post(
            "/v1/agent/query",
            json={
                "query": "hello",
                "current_route": f"/cases/{case_id}",
                "case_id": case_id,
            },
            headers=auth_headers(),
        )

    assert resp.status_code == 200
    assert "Hey! I'm ASK ARIV" in resp.text
    assert "STATUS & DIAGNOSIS" not in resp.text
    assert "[DONE]" in resp.text


def test_capability_question_answers_with_grounded_capabilities():
    mock_tenant = Tenant(id=TENANT_ID, type=TenantType.CONSUMER, name="Test Tenant")

    with patch("app.api.agent.resolve_tenant", new_callable=AsyncMock, return_value=mock_tenant):
        resp = client.post(
            "/v1/agent/query",
            json={"query": "what can you do?"},
            headers=auth_headers(),
        )

    assert resp.status_code == 200
    assert "revenue-recovery control layer" in resp.text
    assert "payment-link status" in resp.text
    assert "recovery metrics" in resp.text
    assert "Recover this case" in resp.text
    assert "[DONE]" in resp.text


def test_greeting_prefix_does_not_reroute_operational_intent():
    """A greeting prefixed to an operational request must keep the operational
    routing (here: recover-this-case falls through to the case branch, which in
    an empty workspace reports no cases — it must NOT be answered as a chat)."""
    mock_tenant = Tenant(id=TENANT_ID, type=TenantType.CONSUMER, name="Test Tenant")

    with patch("app.api.agent.resolve_tenant", new_callable=AsyncMock, return_value=mock_tenant):
        resp = client.post(
            "/v1/agent/query",
            json={"query": "hey, recover this case."},
            headers=auth_headers(),
        )

    assert resp.status_code == 200
    assert "Hey! I'm ASK ARIV" not in resp.text
    assert "No recovery cases found in this workspace." in resp.text
    assert "[DONE]" in resp.text
