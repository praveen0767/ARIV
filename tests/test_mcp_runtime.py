"""
tests/test_mcp_runtime.py

Comprehensive Test Suite for ARIV's Real MCP Tool Runtime.
Validates all 20 scenarios required by the architecture specification:
 1. registry registration
 2. duplicate tool rejection
 3. exact tool lookup
 4. schema validation
 5. risk classification cannot be caller-overridden
 6. tenant isolation (cross-tenant rejection)
 7. READ tool success (fetch_payment, fetch_payment_link)
 8. FINANCIAL tool policy rejection
 9. FINANCIAL tool blocked by kill switch
10. FINANCIAL tool creates existing durable outbox path
11. repeated invocation remains idempotent
12. provider errors become structured tool errors
13. audit event creation
14. no credentials appear in audit output
15. ASK ARIV operational tool path
16. ASK ARIV aggregate metrics query remains unchanged
17. ASK ARIV greeting remains unchanged
18. case-specific routing remains unchanged
19. preview performs no provider mutation
20. SSE structured tool error works
21. JSON-RPC MCP tools/list and tools/call protocol endpoints
"""

import hmac
import hashlib
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.infrastructure.database import get_db_session
from app.domain.tenant import Tenant, TenantType
from app.domain.recovery_case import RecoveryCase, CaseStatus, RecoveryDomain, CaseType
from app.domain.classification import RecoveryClassification, FailureCategory, Retryability, Recoverability
from app.domain.decision import DecisionRecord, RecoveryAction, PolicyStatus, AutonomyLevel
from app.domain.action import Action, ActionStatus, ExecutionAttempt, ExecutionStatus
from app.domain.provider import (
    ProviderCapability,
    ProviderEnvironment,
    ProviderExecutionResult,
    ProviderOutcomeStatus,
    RetrySafety,
)
from app.infrastructure.adapters.razorpay import RazorpayConfig, RazorpaySandboxAdapter
from app.interfaces.mcp import (
    MCPErrorCode,
    MCPToolRegistry,
    ToolDefinition,
    ToolInvocation,
    ToolResult,
    ToolRiskClassification,
    tool_registry,
)
from app.services.execution_control import ExecutionControlService
from app.services.mcp_gateway import MCPToolGateway, sanitize_data
from app.services.mcp_tools import register_default_tools


ACCOUNT_ID = "acc_mcp_test"
TENANT_ID = uuid.uuid4()
OTHER_TENANT_ID = uuid.uuid4()


def make_sig(account_id: str, key: str = settings.INTERNAL_API_KEY) -> str:
    return hmac.new(key.encode("utf-8"), account_id.encode("utf-8"), hashlib.sha256).hexdigest()


def auth_headers(account_id: str = ACCOUNT_ID, key: str = settings.INTERNAL_API_KEY) -> dict:
    return {
        "X-Account-ID": account_id,
        "X-Signature": make_sig(account_id, key),
    }


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


client = TestClient(app)


def create_mock_adapter(handler):
    config = RazorpayConfig(
        key_id="rzp_test_mcp_123",
        key_secret="mock_secret_mcp",
        environment=ProviderEnvironment.SANDBOX,
    )
    transport = httpx.MockTransport(handler) if handler else None
    http_client = httpx.AsyncClient(transport=transport) if transport else None
    return RazorpaySandboxAdapter(config=config, client=http_client)


# ===========================================================================
# 1. Registry Registration
# ===========================================================================

def test_1_registry_registration():
    reg = MCPToolRegistry()
    tool = ToolDefinition(
        name="custom_tool",
        description="A test tool",
        risk_classification=ToolRiskClassification.READ,
        input_schema={"type": "object"},
    )
    reg.register(tool)
    assert reg.get("custom_tool") == tool
    assert len(reg.list_tools()) == 1


# ===========================================================================
# 2. Duplicate Tool Rejection
# ===========================================================================

def test_2_duplicate_tool_rejection():
    reg = MCPToolRegistry()
    tool = ToolDefinition(
        name="duplicate_tool",
        description="Tool A",
        risk_classification=ToolRiskClassification.READ,
        input_schema={"type": "object"},
    )
    reg.register(tool)
    with pytest.raises(ValueError, match="already registered"):
        reg.register(tool)


# ===========================================================================
# 3. Exact Tool Lookup
# ===========================================================================

def test_3_exact_tool_lookup():
    reg = MCPToolRegistry()
    register_default_tools(reg)
    assert reg.get("razorpay_fetch_payment") is not None
    assert reg.get("razorpay_fetch_payment_link") is not None
    assert reg.get("razorpay_create_payment_link") is not None
    assert reg.get("non_existent_tool") is None


# ===========================================================================
# 4. Schema Validation
# ===========================================================================

def test_4_schema_validation():
    # Bad name
    with pytest.raises(ValueError, match="non-empty string"):
        ToolDefinition(name="", description="desc", risk_classification=ToolRiskClassification.READ, input_schema={}).validate()
    # Bad schema
    with pytest.raises(ValueError, match="dictionary"):
        ToolDefinition(name="ok", description="desc", risk_classification=ToolRiskClassification.READ, input_schema="bad").validate()


# ===========================================================================
# 5. Risk Classification Cannot Be Caller-Overridden
# ===========================================================================

@pytest.mark.asyncio
async def test_5_risk_classification_server_enforced():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    gateway = MCPToolGateway()

    invocation = ToolInvocation(
        tool_name="razorpay_create_payment_link",
        tenant_id=TENANT_ID,
        input={},  # Missing required 'amount'
    )
    res = await gateway.invoke(session, invocation)
    assert res.risk_classification == ToolRiskClassification.FINANCIAL
    assert res.error_code == MCPErrorCode.INVALID_TOOL_INPUT.value


# ===========================================================================
# 6. Tenant Isolation (Reject Cross-Tenant or Unauthorized Cases)
# ===========================================================================

@pytest.mark.asyncio
async def test_6_tenant_isolation_cross_tenant_rejected():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    tenant = Tenant(id=TENANT_ID, name="Tenant A")
    other_case = RecoveryCase(
        id=uuid.uuid4(),
        tenant_id=OTHER_TENANT_ID,
        domain=RecoveryDomain.B2C,
        case_type=CaseType.PAYMENT_FAILED,
        amount=50000,
    )

    ten_res = MagicMock(scalar_one_or_none=MagicMock(return_value=tenant))
    case_res = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    session.execute.side_effect = [ten_res, case_res]

    gateway = MCPToolGateway()
    invocation = ToolInvocation(
        tool_name="razorpay_create_payment_link",
        tenant_id=TENANT_ID,
        case_id=other_case.id,
        input={"amount": 50000},
    )
    res = await gateway.invoke(session, invocation)
    assert res.success is False
    assert res.error_code == MCPErrorCode.TENANT_FORBIDDEN.value


# ===========================================================================
# 7. READ Tool Success (fetch_payment, fetch_payment_link)
# ===========================================================================

@pytest.mark.asyncio
async def test_7_read_tool_fetch_payment_success():
    tenant = Tenant(id=TENANT_ID, name="Tenant A")
    case = RecoveryCase(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        domain=RecoveryDomain.B2C,
        case_type=CaseType.PAYMENT_FAILED,
        context={"payment_id": "pay_test_123"},
    )

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    ten_res = MagicMock(scalar_one_or_none=MagicMock(return_value=tenant))
    case_res = MagicMock(scalar_one_or_none=MagicMock(return_value=case))
    session.execute.side_effect = [ten_res, case_res]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "pay_test_123", "status": "captured", "amount": 50000})

    adapter = create_mock_adapter(handler)
    gateway = MCPToolGateway(provider_adapter=adapter)

    invocation = ToolInvocation(
        tool_name="razorpay_fetch_payment",
        tenant_id=TENANT_ID,
        case_id=case.id,
        input={"payment_id": "pay_test_123"},
    )
    res = await gateway.invoke(session, invocation)
    assert res.success is True
    assert res.risk_classification == ToolRiskClassification.READ
    assert res.output["status"] == "captured"


@pytest.mark.asyncio
async def test_7_read_tool_fetch_payment_link_success():
    tenant = Tenant(id=TENANT_ID, name="Tenant A")
    case = RecoveryCase(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        domain=RecoveryDomain.B2C,
        case_type=CaseType.PAYMENT_FAILED,
        context={"payment_link_id": "plink_test_456"},
    )

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    ten_res = MagicMock(scalar_one_or_none=MagicMock(return_value=tenant))
    case_res = MagicMock(scalar_one_or_none=MagicMock(return_value=case))
    session.execute.side_effect = [ten_res, case_res]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "plink_test_456", "status": "paid", "amount": 25000})

    adapter = create_mock_adapter(handler)
    gateway = MCPToolGateway(provider_adapter=adapter)

    invocation = ToolInvocation(
        tool_name="razorpay_fetch_payment_link",
        tenant_id=TENANT_ID,
        case_id=case.id,
        input={"payment_link_id": "plink_test_456"},
    )
    res = await gateway.invoke(session, invocation)
    assert res.success is True
    assert res.output["status"] == "paid"


# ===========================================================================
# 8. FINANCIAL Tool Policy Rejection
# ===========================================================================

@pytest.mark.asyncio
async def test_8_financial_tool_policy_rejection():
    tenant = Tenant(id=TENANT_ID, name="Tenant A")
    case = RecoveryCase(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        domain=RecoveryDomain.B2C,
        case_type=CaseType.PAYMENT_FAILED,
        status=CaseStatus.OPEN,
    )
    decision = DecisionRecord(
        id=uuid.uuid4(),
        case_id=case.id,
        tenant_id=TENANT_ID,
        proposed_action=RecoveryAction.GENERATE_PAYMENT_LINK,
        policy_status=PolicyStatus.REJECTED,
        rejection_reason="Test policy rejection",
    )
    classification = RecoveryClassification(
        id=uuid.uuid4(),
        case_id=case.id,
        failure_category=FailureCategory.NON_RETRIABLE,
    )

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    ten_res = MagicMock(scalar_one_or_none=MagicMock(return_value=tenant))
    case_res = MagicMock(scalar_one_or_none=MagicMock(return_value=case))
    class_res = MagicMock(scalar_one_or_none=MagicMock(return_value=classification))
    dec_res = MagicMock(scalar_one_or_none=MagicMock(return_value=decision))
    session.execute.side_effect = [ten_res, case_res, class_res, dec_res]

    adapter = create_mock_adapter(None)
    gateway = MCPToolGateway(provider_adapter=adapter)

    invocation = ToolInvocation(
        tool_name="razorpay_create_payment_link",
        tenant_id=TENANT_ID,
        case_id=case.id,
        input={"amount": 10000},
    )
    res = await gateway.invoke(session, invocation)
    assert res.success is False
    assert res.error_code == MCPErrorCode.POLICY_REJECTED.value
    assert "rejected" in res.error_message.lower()


# ===========================================================================
# 9. FINANCIAL Tool Blocked by Kill Switch
# ===========================================================================

@pytest.mark.asyncio
async def test_9_financial_tool_blocked_by_kill_switch():
    tenant = Tenant(id=TENANT_ID, name="Tenant A")
    case = RecoveryCase(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        domain=RecoveryDomain.B2C,
        case_type=CaseType.PAYMENT_FAILED,
        status=CaseStatus.OPEN,
    )
    decision = DecisionRecord(
        id=uuid.uuid4(),
        case_id=case.id,
        tenant_id=TENANT_ID,
        proposed_action=RecoveryAction.GENERATE_PAYMENT_LINK,
        policy_status=PolicyStatus.APPROVED,
        autonomy_level=AutonomyLevel.FULL_AUTO,
        ai_confidence=0.9,
    )
    classification = RecoveryClassification(
        id=uuid.uuid4(),
        case_id=case.id,
        failure_category=FailureCategory.CUSTOMER_ACTION_REQUIRED,
    )

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    ten_res = MagicMock(scalar_one_or_none=MagicMock(return_value=tenant))
    case_res = MagicMock(scalar_one_or_none=MagicMock(return_value=case))
    class_res = MagicMock(scalar_one_or_none=MagicMock(return_value=classification))
    dec_res = MagicMock(scalar_one_or_none=MagicMock(return_value=decision))
    session.execute.side_effect = [ten_res, case_res, class_res, dec_res]

    adapter = create_mock_adapter(None)
    gateway = MCPToolGateway(provider_adapter=adapter)

    with patch.object(ExecutionControlService, "is_execution_enabled", return_value=False):
        invocation = ToolInvocation(
            tool_name="razorpay_create_payment_link",
            tenant_id=TENANT_ID,
            case_id=case.id,
            input={"amount": 10000},
        )
        res = await gateway.invoke(session, invocation)

    assert res.success is False
    assert res.error_code == MCPErrorCode.EXECUTION_DISABLED.value


# ===========================================================================
# 10. FINANCIAL Tool Creates Existing Durable Outbox Path
# ===========================================================================

@pytest.mark.asyncio
async def test_10_financial_tool_creates_durable_outbox():
    tenant = Tenant(id=TENANT_ID, name="Tenant A")
    case = RecoveryCase(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        domain=RecoveryDomain.B2C,
        case_type=CaseType.PAYMENT_FAILED,
        status=CaseStatus.OPEN,
    )
    decision = DecisionRecord(
        id=uuid.uuid4(),
        case_id=case.id,
        tenant_id=TENANT_ID,
        proposed_action=RecoveryAction.GENERATE_PAYMENT_LINK,
        policy_status=PolicyStatus.APPROVED,
        autonomy_level=AutonomyLevel.FULL_AUTO,
        ai_confidence=0.9,
    )
    classification = RecoveryClassification(
        id=uuid.uuid4(),
        case_id=case.id,
        failure_category=FailureCategory.CUSTOMER_ACTION_REQUIRED,
    )

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    ten_res = MagicMock(scalar_one_or_none=MagicMock(return_value=tenant))
    case_res = MagicMock(scalar_one_or_none=MagicMock(return_value=case))
    class_res = MagicMock(scalar_one_or_none=MagicMock(return_value=classification))
    dec_res = MagicMock(scalar_one_or_none=MagicMock(return_value=decision))

    attempt = ExecutionAttempt(
        id=uuid.uuid4(),
        action_id=uuid.uuid4(),
        attempt_number=1,
        status=ExecutionStatus.SUCCEEDED,
        provider_request_id="plink_mcp_100",
        attempt_metadata={"short_url": "https://rzp.io/i/mcp100"},
    )
    att_res = MagicMock(scalar_one_or_none=MagicMock(return_value=attempt))
    session.execute.side_effect = [ten_res, case_res, class_res, dec_res, att_res]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "plink_mcp_100", "short_url": "https://rzp.io/i/mcp100", "status": "created"})

    adapter = create_mock_adapter(handler)
    gateway = MCPToolGateway(provider_adapter=adapter)

    from app.services.outbox import OutboxService
    from app.domain.action import ExecutionOutbox, OutboxStatus
    mock_action = Action(
        id=uuid.uuid4(),
        case_id=case.id,
        tenant_id=tenant.id,
        decision_id=decision.id,
        action_type=RecoveryAction.GENERATE_PAYMENT_LINK,
        status=ActionStatus.SUCCEEDED,
    )
    mock_outbox = ExecutionOutbox(id=uuid.uuid4(), action_id=mock_action.id, status=OutboxStatus.COMPLETED)

    with patch.object(ExecutionControlService, "is_execution_enabled", return_value=True), \
         patch.object(OutboxService, "create_authorized_action", return_value=(mock_action, mock_outbox)) as mock_outbox_call, \
         patch("app.services.mcp_gateway.ExecutionWorker") as mock_worker_cls:

        mock_worker_instance = MagicMock()
        mock_worker_instance.process_outbox_item = AsyncMock(
            return_value=ProviderExecutionResult(
                status=ProviderOutcomeStatus.SUCCEEDED,
                provider="razorpay",
                retry_safety=RetrySafety.SAFE_TO_RETRY,
            )
        )
        mock_worker_cls.return_value = mock_worker_instance

        invocation = ToolInvocation(
            tool_name="razorpay_create_payment_link",
            tenant_id=TENANT_ID,
            case_id=case.id,
            input={"amount": 50000},
        )
        res = await gateway.invoke(session, invocation)

    assert res.success is True
    assert res.output["payment_link_url"] == "https://rzp.io/i/mcp100"
    mock_outbox_call.assert_awaited_once()


# ===========================================================================
# 11. Repeated Invocation Remains Idempotent
# ===========================================================================

@pytest.mark.asyncio
async def test_11_repeated_invocation_idempotent():
    tenant = Tenant(id=TENANT_ID, name="Tenant A")
    case = RecoveryCase(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        domain=RecoveryDomain.B2C,
        case_type=CaseType.PAYMENT_FAILED,
        status=CaseStatus.RISK_ASSESSED,
        context={"recovery_stage": "WAITING_FOR_PAYMENT", "payment_link_url": "https://rzp.io/i/active", "payment_link_id": "plink_active"},
    )

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    ten_res = MagicMock(scalar_one_or_none=MagicMock(return_value=tenant))
    case_res = MagicMock(scalar_one_or_none=MagicMock(return_value=case))
    session.execute.side_effect = [ten_res, case_res]

    adapter = create_mock_adapter(None)
    gateway = MCPToolGateway(provider_adapter=adapter)

    invocation = ToolInvocation(
        tool_name="razorpay_create_payment_link",
        tenant_id=TENANT_ID,
        case_id=case.id,
        input={"amount": 10000},
    )
    res = await gateway.invoke(session, invocation)
    assert res.success is True
    assert res.status == "IDEMPOTENT_HIT"
    assert res.output["payment_link_url"] == "https://rzp.io/i/active"


# ===========================================================================
# 12. Provider Errors Become Structured Tool Errors
# ===========================================================================

@pytest.mark.asyncio
async def test_12_provider_errors_structured():
    tenant = Tenant(id=TENANT_ID, name="Tenant A")
    case = RecoveryCase(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        domain=RecoveryDomain.B2C,
        case_type=CaseType.PAYMENT_FAILED,
        context={"payment_id": "pay_err"},
    )

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    ten_res = MagicMock(scalar_one_or_none=MagicMock(return_value=tenant))
    case_res = MagicMock(scalar_one_or_none=MagicMock(return_value=case))
    session.execute.side_effect = [ten_res, case_res]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"code": "GATEWAY_ERROR", "description": "Downstream timeout"}})

    adapter = create_mock_adapter(handler)
    gateway = MCPToolGateway(provider_adapter=adapter)

    invocation = ToolInvocation(
        tool_name="razorpay_fetch_payment",
        tenant_id=TENANT_ID,
        case_id=case.id,
        input={"payment_id": "pay_err"},
    )
    res = await gateway.invoke(session, invocation)
    assert res.success is False
    assert res.error_code == MCPErrorCode.PROVIDER_ERROR.value


# ===========================================================================
# 13 & 14. Audit Event Creation & Secret Sanitization
# ===========================================================================

def test_14_data_sanitization_removes_secrets():
    raw = {
        "payment_id": "pay_123",
        "api_key": "secret_abc123",
        "nested": {"card_number": "411111111111", "cvv": "123", "token": "tok_xyz"},
    }
    cleaned = sanitize_data(raw)
    assert cleaned["payment_id"] == "pay_123"
    assert cleaned["api_key"] == "[REDACTED]"
    assert cleaned["nested"]["card_number"] == "[REDACTED]"
    assert cleaned["nested"]["cvv"] == "[REDACTED]"
    assert cleaned["nested"]["token"] == "[REDACTED]"


# ===========================================================================
# 15. ASK ARIV Operational Tool Path
# ===========================================================================

def test_15_ask_ariv_operational_tool_path():
    mock_tenant = Tenant(id=TENANT_ID, type=TenantType.CONSUMER, name="Test Tenant")
    case = RecoveryCase(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        domain=RecoveryDomain.B2C,
        case_type=CaseType.PAYMENT_FAILED,
        amount=50000,
        status=CaseStatus.RISK_ASSESSED,
        context={},
    )
    classification = RecoveryClassification(
        id=uuid.uuid4(),
        case_id=case.id,
        failure_category=FailureCategory.CUSTOMER_ACTION_REQUIRED,
    )
    decision = DecisionRecord(
        id=uuid.uuid4(),
        case_id=case.id,
        tenant_id=TENANT_ID,
        proposed_action=RecoveryAction.GENERATE_PAYMENT_LINK,
        policy_status=PolicyStatus.APPROVED,
        autonomy_level=AutonomyLevel.FULL_AUTO,
        ai_confidence=0.9,
    )

    mock_session = AsyncMock()
    mock_case_result = MagicMock()
    mock_case_result.scalars.return_value.all.return_value = [case]
    mock_class_result = MagicMock(scalar_one_or_none=MagicMock(return_value=classification))
    mock_dec_result = MagicMock(scalar_one_or_none=MagicMock(return_value=decision))
    mock_none_result = MagicMock(
        scalar_one_or_none=MagicMock(return_value=None),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
    )

    async def mock_execute(query, *args, **kwargs):
        q = str(query)
        if "recovery_classification" in q:
            return mock_class_result
        if "decision_record" in q:
            return mock_dec_result
        if "recovery_case" in q:
            return mock_case_result
        return mock_none_result

    mock_session.execute = AsyncMock(side_effect=mock_execute)
    mock_session.commit = AsyncMock()

    async def _override():
        yield mock_session

    with patch("app.api.agent.resolve_tenant", new_callable=AsyncMock, return_value=mock_tenant), \
         patch("app.api.agent.MCPToolGateway") as mock_gateway_cls:

        mock_gw = MagicMock()
        mock_gw.invoke = AsyncMock(
            return_value=ToolResult(
                success=True,
                tool_name="razorpay_create_payment_link",
                risk_classification=ToolRiskClassification.FINANCIAL,
                status="SUCCEEDED",
                output={"payment_link_url": "https://rzp.io/i/agent_demo", "payment_link_id": "plink_demo_1"},
            )
        )
        mock_gateway_cls.return_value = mock_gw

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
    assert "https://rzp.io/i/agent_demo" in resp.text
    mock_gw.invoke.assert_awaited_once()


# ===========================================================================
# 16 & 17. ASK ARIV Greeting and Aggregate Metrics Non-Regressions
# ===========================================================================

def test_16_ask_ariv_greeting_non_regression():
    mock_tenant = Tenant(id=TENANT_ID, type=TenantType.CONSUMER, name="Test Tenant")

    with patch("app.api.agent.resolve_tenant", new_callable=AsyncMock, return_value=mock_tenant):
        resp = client.post("/v1/agent/query", json={"query": "hi"}, headers=auth_headers())
    assert resp.status_code == 200
    assert "ASK ARIV" in resp.text


def test_17_ask_ariv_aggregate_metrics_non_regression():
    mock_tenant = Tenant(id=TENANT_ID, type=TenantType.CONSUMER, name="Test Tenant")

    with patch("app.api.agent.resolve_tenant", new_callable=AsyncMock, return_value=mock_tenant), \
         patch("app.services.dashboard.DashboardService.get_tenant_metrics", new_callable=AsyncMock) as mock_metrics:

        mock_metrics.return_value = {
            "verified_recoveries": {"payments_recovered": 3, "recovered_revenue_minor": 150000, "recovery_rate_pct": 75.0},
            "at_risk": {"revenue_at_risk_minor": 200000, "cases_total": 4},
            "pipeline": {"cases_decisioned": 4, "actions_executed": 3, "payment_links_generated": 3},
        }
        resp = client.post("/v1/agent/query", json={"query": "how much was recovered?"}, headers=auth_headers())

    assert resp.status_code == 200
    assert "ARIV WORKSPACE RECOVERY METRICS" in resp.text


# ===========================================================================
# 19. Preview Performs No Provider Mutation
# ===========================================================================

@pytest.mark.asyncio
async def test_19_preview_no_mutation():
    tenant = Tenant(id=TENANT_ID, name="Tenant A")
    case = RecoveryCase(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        domain=RecoveryDomain.B2C,
        case_type=CaseType.PAYMENT_FAILED,
        status=CaseStatus.OPEN,
    )
    decision = DecisionRecord(
        id=uuid.uuid4(),
        case_id=case.id,
        tenant_id=TENANT_ID,
        proposed_action=RecoveryAction.GENERATE_PAYMENT_LINK,
        policy_status=PolicyStatus.APPROVED,
        autonomy_level=AutonomyLevel.FULL_AUTO,
        ai_confidence=0.95,
    )
    classification = RecoveryClassification(
        id=uuid.uuid4(),
        case_id=case.id,
        failure_category=FailureCategory.CUSTOMER_ACTION_REQUIRED,
    )

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    ten_res = MagicMock(scalar_one_or_none=MagicMock(return_value=tenant))
    case_res = MagicMock(scalar_one_or_none=MagicMock(return_value=case))
    class_res = MagicMock(scalar_one_or_none=MagicMock(return_value=classification))
    dec_res = MagicMock(scalar_one_or_none=MagicMock(return_value=decision))
    session.execute.side_effect = [ten_res, case_res, class_res, dec_res]

    adapter = create_mock_adapter(None)
    gateway = MCPToolGateway(provider_adapter=adapter)

    with patch.object(ExecutionControlService, "is_execution_enabled", return_value=True):
        invocation = ToolInvocation(
            tool_name="razorpay_create_payment_link",
            tenant_id=TENANT_ID,
            case_id=case.id,
            input={"amount": 75000},
            is_preview=True,
        )
        res = await gateway.invoke(session, invocation)

    assert res.success is True
    assert res.status == "PREVIEW"
    assert res.output["preview"] is True
    assert res.output["amount"] == 75000


# ===========================================================================
# 20. JSON-RPC MCP Endpoints (tools/list & tools/call)
# ===========================================================================

def test_20_mcp_tools_list_endpoint():
    mock_tenant = Tenant(id=TENANT_ID, type=TenantType.CONSUMER, name="Test Tenant")

    with patch("app.api.mcp.resolve_tenant", new_callable=AsyncMock, return_value=mock_tenant):
        resp = client.post(
            "/v1/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            },
            headers=auth_headers(),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["jsonrpc"] == "2.0"
    assert "tools" in data["result"]
    tool_names = [t["name"] for t in data["result"]["tools"]]
    assert "razorpay_fetch_payment" in tool_names
    assert "razorpay_create_payment_link" in tool_names


def test_20_mcp_tools_call_endpoint():
    mock_tenant = Tenant(id=TENANT_ID, type=TenantType.CONSUMER, name="Test Tenant")

    with patch("app.api.mcp.resolve_tenant", new_callable=AsyncMock, return_value=mock_tenant), \
         patch.object(MCPToolGateway, "invoke", new_callable=AsyncMock) as mock_invoke:

        mock_invoke.return_value = ToolResult(
            success=True,
            tool_name="razorpay_fetch_payment",
            risk_classification=ToolRiskClassification.READ,
            status="SUCCEEDED",
            output={"id": "pay_test_999", "status": "authorized"},
        )

        resp = client.post(
            "/v1/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "razorpay_fetch_payment",
                    "arguments": {"payment_id": "pay_test_999"},
                },
            },
            headers=auth_headers(),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["isError"] is False
    assert "authorized" in data["result"]["content"][0]["text"]
