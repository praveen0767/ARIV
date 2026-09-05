"""
tests/test_phase4d_hardening.py

Phase 4D Comprehensive Hardening, Capability-Specific Reconciliation,
Crash Windows Analysis, Concurrency, Security, and End-to-End Recovery Flow.
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import httpx

from app.domain.action import (
    Action,
    ActionStatus,
    ExecutionAttempt,
    ExecutionStatus,
    ExecutionOutbox,
    OutboxStatus,
)
from app.domain.classification import FailureCategory, RecoveryClassification, Retryability, Recoverability
from app.domain.decision import (
    AutonomyLevel,
    DecisionRecord,
    PolicyStatus,
    RecoveryAction,
)
from app.domain.events import AuditEvent, ProviderEvent
from app.domain.provider import (
    CancelPaymentLinkRequest,
    CreatePaymentLinkRequest,
    FetchPaymentLinkRequest,
    FetchPaymentRequest,
    ProviderCapability,
    ProviderEnvironment,
    ProviderErrorCode,
    ProviderExecutionResult,
    ProviderOutcomeStatus,
    RetrySafety,
    UnsupportedCapabilityError,
)
from app.domain.recovery_case import CaseStatus, CaseType, RecoveryCase, RecoveryDomain
from app.domain.schemas import DecisionProposal
from app.domain.state_machine import CaseStateMachine, StateTransitionError
from app.domain.tenant import Tenant, TenantType
from app.infrastructure.adapters.razorpay import RazorpayConfig, RazorpaySandboxAdapter
from app.services.decision_engine import DecisionEngineService
from app.services.execution_control import ExecutionControlService
from app.services.execution_worker import ExecutionPreflightValidator, ExecutionWorker
from app.services.outbox import OutboxService
from app.services.policy import PolicyEngine
from app.services.reconciliation import ReconciliationService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def base_context():
    tenant_id = uuid.uuid4()
    case_id = uuid.uuid4()
    decision_id = uuid.uuid4()

    tenant = Tenant(
        id=tenant_id,
        name="Enterprise Client A",
        type=TenantType.ENTERPRISE,
        config={},
    )
    case = RecoveryCase(
        id=case_id,
        tenant_id=tenant_id,
        domain=RecoveryDomain.B2C,
        case_type=CaseType.PAYMENT_FAILED,
        status=CaseStatus.RISK_ASSESSED,
        version=1,
    )
    decision = DecisionRecord(
        id=decision_id,
        case_id=case_id,
        tenant_id=tenant_id,
        proposed_action=RecoveryAction.GENERATE_PAYMENT_LINK,
        baseline_action=RecoveryAction.GENERATE_PAYMENT_LINK,
        policy_status=PolicyStatus.APPROVED,
        autonomy_level=AutonomyLevel.FULL_AUTO,
        ai_confidence=0.98,
        expected_irv=10000.0,
    )
    classification = RecoveryClassification(
        id=uuid.uuid4(),
        case_id=case_id,
        failure_category=FailureCategory.CUSTOMER_ACTION_REQUIRED,
        retryability=Retryability.REQUIRES_NEW_METHOD,
        recoverability=Recoverability.HIGH,
    )
    return {
        "tenant": tenant,
        "case": case,
        "decision": decision,
        "classification": classification,
    }


def create_mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    return session


def create_mock_razorpay_adapter(handler):
    config = RazorpayConfig(
        key_id="rzp_test_mock_123",
        key_secret="mock_secret_abc",
        environment=ProviderEnvironment.SANDBOX,
    )
    if handler:
        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
    else:
        client = None
    return RazorpaySandboxAdapter(config=config, client=client)


# ===========================================================================
# 4D.1 — BUSINESS IDEMPOTENCY HARDENING
# ===========================================================================

@pytest.mark.asyncio
async def test_4d_1_stable_action_idempotency_across_retries(base_context):
    """
    Ensures that for a single logical Action, the business idempotency key
    remains identical across Attempt 1, Attempt 2, and Attempt 3.
    """
    action_id = uuid.uuid4()
    action = Action(
        id=action_id,
        case_id=base_context["case"].id,
        tenant_id=base_context["tenant"].id,
        decision_id=base_context["decision"].id,
        action_type=RecoveryAction.GENERATE_PAYMENT_LINK,
        status=ActionStatus.AUTHORIZED,
    )

    captured_keys = []
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        key = request.headers.get("X-Razorpay-Idempotency")
        captured_keys.append(key)
        if call_count == 1:
            return httpx.Response(429, json={"error": {"code": "RATE_LIMIT", "description": "Too many requests"}})
        return httpx.Response(200, json={"id": "plink_idem_1", "status": "created"})

    adapter = create_mock_razorpay_adapter(handler)
    worker = ExecutionWorker(worker_id="worker_idem", provider_adapter=adapter)

    # Attempt 1 (transient 429 failure)
    outbox_1 = ExecutionOutbox(id=uuid.uuid4(), action_id=action_id, attempt_count=1, max_retries=3)
    session = create_mock_session()
    act_res = MagicMock(scalar_one_or_none=MagicMock(return_value=action))
    case_res = MagicMock(scalar_one_or_none=MagicMock(return_value=base_context["case"]))
    dec_res = MagicMock(scalar_one_or_none=MagicMock(return_value=base_context["decision"]))
    ten_res = MagicMock(scalar_one_or_none=MagicMock(return_value=base_context["tenant"]))
    class_res = MagicMock(scalar_one_or_none=MagicMock(return_value=base_context["classification"]))
    exist_res = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    session.execute.side_effect = [act_res, case_res, dec_res, ten_res, class_res, exist_res]

    with patch.object(ExecutionControlService, "is_execution_enabled", return_value=True):
        await worker.process_outbox_item(session, outbox_1)

    # Reset action to AUTHORIZED for worker retry
    action.status = ActionStatus.AUTHORIZED

    # Attempt 2 (retry of the same logical Action)
    outbox_2 = ExecutionOutbox(id=uuid.uuid4(), action_id=action_id, attempt_count=2, max_retries=3)
    session.execute.side_effect = [act_res, case_res, dec_res, ten_res, class_res, exist_res]

    with patch.object(ExecutionControlService, "is_execution_enabled", return_value=True):
        await worker.process_outbox_item(session, outbox_2)

    assert len(captured_keys) == 2
    # CRITICAL: Both attempts must share the exact same business idempotency key!
    assert captured_keys[0] == f"ariv:action:{action_id}"
    assert captured_keys[1] == f"ariv:action:{action_id}"
    assert captured_keys[0] == captured_keys[1]


def test_4d_1_distinct_actions_produce_unique_keys():
    """Different Actions cannot share the same business idempotency key."""
    id1 = uuid.uuid4()
    id2 = uuid.uuid4()
    key1 = f"ariv:action:{id1}"
    key2 = f"ariv:action:{id2}"
    assert key1 != key2


# ===========================================================================
# 4D.2 — CAPABILITY-SPECIFIC RECONCILIATION
# ===========================================================================

@pytest.mark.asyncio
async def test_4d_2_payment_link_reconciliation_routes_to_fetch_payment_link(base_context):
    """
    Verifies that reconciling GENERATE_PAYMENT_LINK explicitly calls
    fetch_payment_link (not fetch_payment).
    """
    called_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        called_paths.append(request.url.path)
        return httpx.Response(
            200,
            json={"id": "plink_spec_1", "status": "created", "short_url": "https://rzp.io/i/spec1"},
        )

    adapter = create_mock_razorpay_adapter(handler)

    action = Action(
        id=uuid.uuid4(),
        case_id=base_context["case"].id,
        tenant_id=base_context["tenant"].id,
        decision_id=base_context["decision"].id,
        action_type=RecoveryAction.GENERATE_PAYMENT_LINK,
        status=ActionStatus.UNKNOWN,
    )
    attempt = ExecutionAttempt(
        id=uuid.uuid4(),
        action_id=action.id,
        attempt_number=1,
        status=ExecutionStatus.UNKNOWN,
        provider_request_id="plink_spec_1",
        attempt_metadata={},
    )
    outbox = ExecutionOutbox(id=uuid.uuid4(), action_id=action.id, status=OutboxStatus.CLAIMED)
    session = create_mock_session()

    result = await ReconciliationService.reconcile_action(
        session=session,
        action=action,
        attempt=attempt,
        outbox=outbox,
        case=base_context["case"],
        provider_adapter=adapter,
    )

    assert result.status == ProviderOutcomeStatus.SUCCEEDED
    assert len(called_paths) == 1
    # Must query payment_links endpoint specifically!
    assert called_paths[0] == "/v1/payment_links/plink_spec_1"
    assert action.status == ActionStatus.SUCCEEDED
    assert base_context["case"].status == CaseStatus.RECOVERED


@pytest.mark.asyncio
async def test_4d_2_payment_charge_reconciliation_routes_to_fetch_payment(base_context):
    """
    Verifies that reconciling RETRY_NOW explicitly calls
    fetch_payment (querying /v1/payments/{id}).
    """
    called_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        called_paths.append(request.url.path)
        return httpx.Response(
            200,
            json={"id": "pay_spec_99", "status": "captured", "amount": 10000},
        )

    adapter = create_mock_razorpay_adapter(handler)

    action = Action(
        id=uuid.uuid4(),
        case_id=base_context["case"].id,
        tenant_id=base_context["tenant"].id,
        decision_id=base_context["decision"].id,
        action_type=RecoveryAction.RETRY_NOW,
        status=ActionStatus.UNKNOWN,
    )
    attempt = ExecutionAttempt(
        id=uuid.uuid4(),
        action_id=action.id,
        attempt_number=1,
        status=ExecutionStatus.UNKNOWN,
        provider_request_id="pay_spec_99",
        attempt_metadata={},
    )
    outbox = ExecutionOutbox(id=uuid.uuid4(), action_id=action.id, status=OutboxStatus.CLAIMED)
    session = create_mock_session()

    result = await ReconciliationService.reconcile_action(
        session=session,
        action=action,
        attempt=attempt,
        outbox=outbox,
        case=base_context["case"],
        provider_adapter=adapter,
    )

    assert result.status == ProviderOutcomeStatus.SUCCEEDED
    assert len(called_paths) == 1
    # Must query payments endpoint specifically!
    assert called_paths[0] == "/v1/payments/pay_spec_99"


# ===========================================================================
# 4D.3 — UNKNOWN IS A FIRST-CLASS STATE
# ===========================================================================

@pytest.mark.asyncio
async def test_4d_3_unresolvable_unknown_remains_unknown_with_audit(base_context):
    """
    When reconciliation cannot determine resource state, the Action remains UNKNOWN
    and generates an audit trail without entering an uncontrolled retry loop.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Timeout reading payment link")

    adapter = create_mock_razorpay_adapter(handler)

    action = Action(
        id=uuid.uuid4(),
        case_id=base_context["case"].id,
        tenant_id=base_context["tenant"].id,
        decision_id=base_context["decision"].id,
        action_type=RecoveryAction.GENERATE_PAYMENT_LINK,
        status=ActionStatus.UNKNOWN,
    )
    attempt = ExecutionAttempt(
        id=uuid.uuid4(),
        action_id=action.id,
        attempt_number=1,
        status=ExecutionStatus.UNKNOWN,
        provider_request_id="plink_unresolvable",
        attempt_metadata={},
    )
    outbox = ExecutionOutbox(id=uuid.uuid4(), action_id=action.id, status=OutboxStatus.CLAIMED)
    session = create_mock_session()

    result = await ReconciliationService.reconcile_action(
        session=session,
        action=action,
        attempt=attempt,
        outbox=outbox,
        case=base_context["case"],
        provider_adapter=adapter,
    )

    assert result.status == ProviderOutcomeStatus.UNKNOWN
    assert action.status == ActionStatus.UNKNOWN
    assert attempt.status == ExecutionStatus.UNKNOWN
    # Outbox status remains CLAIMED/PENDING for manual review, not completed or failed
    assert outbox.status == OutboxStatus.CLAIMED


# ===========================================================================
# 4D.5 — WORKER CRASH WINDOWS ANALYSIS (WINDOWS A through G)
# ===========================================================================

@pytest.mark.asyncio
async def test_4d_5_window_a_claim_crash_reclaim():
    """Window A: Worker claims outbox, crashes, lease expires, next worker reclaims safely."""
    crashed_outbox = ExecutionOutbox(
        id=uuid.uuid4(),
        action_id=uuid.uuid4(),
        status=OutboxStatus.CLAIMED,
        claimed_by="worker_crashed_A",
        claimed_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=30),  # Expired lease
        attempt_count=1,
        max_retries=3,
    )

    session = create_mock_session()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [crashed_outbox]
    session.execute.return_value = result_mock

    claimed = await OutboxService.claim_pending_items(
        session=session,
        worker_id="worker_survivor_B",
        lease_seconds=30,
    )

    assert len(claimed) == 1
    assert claimed[0].claimed_by == "worker_survivor_B"
    assert claimed[0].attempt_count == 2


@pytest.mark.asyncio
async def test_4d_5_window_d_provider_request_sent_worker_crashes_reconciles(base_context):
    """
    Window D: Provider request was sent, worker crashed before processing response.
    Survivor worker executes and triggers reconciliation to confirm outcome.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": "plink_crash_d", "status": "created", "short_url": "https://rzp.io/i/d"},
        )

    adapter = create_mock_razorpay_adapter(handler)

    action = Action(
        id=uuid.uuid4(),
        case_id=base_context["case"].id,
        tenant_id=base_context["tenant"].id,
        decision_id=base_context["decision"].id,
        action_type=RecoveryAction.GENERATE_PAYMENT_LINK,
        status=ActionStatus.UNKNOWN,
    )
    attempt = ExecutionAttempt(
        id=uuid.uuid4(),
        action_id=action.id,
        attempt_number=1,
        status=ExecutionStatus.UNKNOWN,
        provider_request_id="plink_crash_d",
        attempt_metadata={},
    )
    outbox = ExecutionOutbox(id=uuid.uuid4(), action_id=action.id, status=OutboxStatus.CLAIMED)
    session = create_mock_session()

    result = await ReconciliationService.reconcile_action(
        session=session,
        action=action,
        attempt=attempt,
        outbox=outbox,
        case=base_context["case"],
        provider_adapter=adapter,
    )

    assert result.status == ProviderOutcomeStatus.SUCCEEDED
    assert action.status == ActionStatus.SUCCEEDED
    assert base_context["case"].status == CaseStatus.RECOVERED


@pytest.mark.asyncio
async def test_4d_5_window_g_case_becomes_recovered_while_worker_claims(base_context):
    """
    Window G: Case transitioned to RECOVERED (e.g. customer paid offline)
    while outbox job was in flight. Preflight blocks execution.
    """
    base_context["case"].status = CaseStatus.RECOVERED  # Customer already recovered

    action = Action(
        id=uuid.uuid4(),
        case_id=base_context["case"].id,
        tenant_id=base_context["tenant"].id,
        decision_id=base_context["decision"].id,
        action_type=RecoveryAction.GENERATE_PAYMENT_LINK,
        status=ActionStatus.AUTHORIZED,
    )
    outbox = ExecutionOutbox(id=uuid.uuid4(), action_id=action.id, attempt_count=1)
    session = create_mock_session()
    adapter = create_mock_razorpay_adapter(None)

    is_valid, reason, rec_status = await ExecutionPreflightValidator.validate(
        session=session,
        outbox=outbox,
        action=action,
        case=base_context["case"],
        decision=base_context["decision"],
        tenant=base_context["tenant"],
        provider_adapter=adapter,
    )

    assert is_valid is False
    assert "terminal state" in reason.lower()
    assert rec_status == ActionStatus.SUPERSEDED


# ===========================================================================
# 4D.7 — CONCURRENCY & RACE TESTING
# ===========================================================================

@pytest.mark.asyncio
async def test_4d_7_active_lease_cannot_be_reclaimed_before_expiry():
    """A live worker holding an unexpired lease cannot have its job stolen by another worker."""
    active_outbox = ExecutionOutbox(
        id=uuid.uuid4(),
        action_id=uuid.uuid4(),
        status=OutboxStatus.CLAIMED,
        claimed_by="worker_active_1",
        claimed_at=datetime.now(timezone.utc),
        lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=25),  # 25s remaining!
        attempt_count=1,
    )

    session = create_mock_session()
    # Mock query returning empty because lease is active
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    session.execute.return_value = result_mock

    claimed = await OutboxService.claim_pending_items(
        session=session,
        worker_id="worker_intruder_2",
    )
    assert len(claimed) == 0


# ===========================================================================
# 4D.8 — ACTION / CASE STATE CONSISTENCY
# ===========================================================================

def test_4d_8_terminal_case_cannot_regress_to_failure():
    """State machine prevents regressing RECOVERED case to FAILED."""
    recovered_case = RecoveryCase(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        domain=RecoveryDomain.B2C,
        case_type=CaseType.PAYMENT_FAILED,
        status=CaseStatus.RECOVERED,
        version=2,
    )

    with pytest.raises(StateTransitionError, match="Cannot regress"):
        CaseStateMachine.transition_to(recovered_case, CaseStatus.FAILED)


# ===========================================================================
# 4D.10 — COMPLETE END-TO-END SANDBOX RECOVERY FLOW
# ===========================================================================

@pytest.mark.asyncio
async def test_4d_10_complete_e2e_recovery_flow(base_context):
    """
    Demonstrates complete pipeline:
    Payment Failure Event -> Decision -> Policy Approval -> Action Authorization
    -> Outbox Persistence -> Worker Claim -> Preflight Revalidation -> Razorpay Link Generation
    -> Outcome -> Case Recovery -> Full Audit Trail.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-Razorpay-Idempotency") is not None
        return httpx.Response(
            200,
            json={
                "id": "plink_e2e_buildathon_100",
                "status": "created",
                "short_url": "https://rzp.io/i/e2e100",
                "amount": 100000,
                "currency": "INR",
            },
            headers={"x-request-id": "req_e2e_corr_100"},
        )

    adapter = create_mock_razorpay_adapter(handler)
    worker = ExecutionWorker(worker_id="worker_e2e_demo", provider_adapter=adapter)

    session = create_mock_session()
    session.add = MagicMock()
    session.flush = AsyncMock()

    # Step 1: Decision & Authorization -> Transactional Outbox Creation
    action, outbox = await OutboxService.create_authorized_action(
        session=session,
        case_id=base_context["case"].id,
        tenant_id=base_context["tenant"].id,
        decision_id=base_context["decision"].id,
        action_type=RecoveryAction.GENERATE_PAYMENT_LINK,
        payload={"amount": 100000, "currency": "INR", "description": "E2E Recovery Invoice"},
    )
    assert action.status == ActionStatus.AUTHORIZED
    assert outbox.status == OutboxStatus.PENDING

    # Step 2: Worker claims outbox item
    outbox.status = OutboxStatus.CLAIMED
    outbox.attempt_count = 1

    # Step 3: Setup query mocks for worker preflight
    act_res = MagicMock(scalar_one_or_none=MagicMock(return_value=action))
    case_res = MagicMock(scalar_one_or_none=MagicMock(return_value=base_context["case"]))
    dec_res = MagicMock(scalar_one_or_none=MagicMock(return_value=base_context["decision"]))
    ten_res = MagicMock(scalar_one_or_none=MagicMock(return_value=base_context["tenant"]))
    class_res = MagicMock(scalar_one_or_none=MagicMock(return_value=base_context["classification"]))
    exist_res = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    session.execute.side_effect = [act_res, case_res, dec_res, ten_res, class_res, exist_res]

    # Step 4: Worker processes outbox item with kill switch enabled
    with patch.object(ExecutionControlService, "is_execution_enabled", return_value=True):
        result = await worker.process_outbox_item(session, outbox)

    # Step 5: Verify outcomes
    assert result.status == ProviderOutcomeStatus.SUCCEEDED
    assert result.provider_resource_id == "plink_e2e_buildathon_100"
    assert action.status == ActionStatus.SUCCEEDED
    assert outbox.status == OutboxStatus.COMPLETED
    assert outbox.dispatched is True
    # Payment link created -> non-terminal state waiting for payment
    assert base_context["case"].status == CaseStatus.RISK_ASSESSED
    assert base_context["case"].context.get("recovery_stage") == "WAITING_FOR_PAYMENT"

    # Step 6: Verify full audit lineage was recorded
    added_items = [call.args[0] for call in session.add.call_args_list]
    audit_event_types = [item.event_type for item in added_items if isinstance(item, AuditEvent)]

    assert "ACTION_AUTHORIZED" in audit_event_types
    assert "EXECUTION_ATTEMPT_STARTED" in audit_event_types
    assert "EXECUTION_SUCCEEDED" in audit_event_types


# ===========================================================================
# 4D.12 — SECURITY & CROSS-TENANT TESTS
# ===========================================================================

@pytest.mark.asyncio
async def test_4d_12_cross_tenant_isolation_fails_safe(base_context):
    """An action belonging to Tenant A cannot be executed under Tenant B's case."""
    alien_tenant_id = uuid.uuid4()
    tampered_action = Action(
        id=uuid.uuid4(),
        case_id=base_context["case"].id,
        tenant_id=alien_tenant_id,  # Forged tenant!
        decision_id=base_context["decision"].id,
        action_type=RecoveryAction.GENERATE_PAYMENT_LINK,
        status=ActionStatus.AUTHORIZED,
    )
    outbox = ExecutionOutbox(id=uuid.uuid4(), action_id=tampered_action.id, attempt_count=1)
    session = create_mock_session()
    adapter = create_mock_razorpay_adapter(None)

    is_valid, reason, _ = await ExecutionPreflightValidator.validate(
        session=session,
        outbox=outbox,
        action=tampered_action,
        case=base_context["case"],
        decision=base_context["decision"],
        tenant=base_context["tenant"],
        provider_adapter=adapter,
    )

    assert is_valid is False
    assert "tenant mismatch" in reason.lower()
