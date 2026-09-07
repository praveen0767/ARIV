"""Regression coverage for Phase 1 production-correctness boundaries."""

import hashlib
import hmac
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.recovery import get_current_tenant
from app.core.config import settings
from app.domain.action import Action, ActionStatus, ExecutionAttempt, ExecutionOutbox, ExecutionStatus, OutboxStatus
from app.domain.classification import FailureCategory, RecoveryClassification, Recoverability, Retryability
from app.domain.decision import AutonomyLevel, DecisionRecord, PolicyStatus, RecoveryAction
from app.domain.provider import ProviderExecutionResult, ProviderOutcomeStatus, RetrySafety
from app.domain.recovery_case import CaseStatus, CaseType, RecoveryCase, RecoveryDomain
from app.domain.tenant import Tenant, TenantType
from app.infrastructure.qdrant import REQUIRED_COLLECTIONS
from app.services.execution_control import ExecutionControlService
from app.services.execution_worker import ExecutionWorker
from app.services.ingestion import _handle_payment_success_event, resolve_tenant
from app.services.qdrant_memory import QdrantMemoryService
from app.services.reconciliation import ReconciliationService


def _scalar(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_resolve_tenant_returns_only_exact_account_mapping():
    mapped_tenant = Tenant(
        id=uuid.uuid4(),
        type=TenantType.CONSUMER,
        name="Mapped tenant",
        config={"account_id": "acc_a"},
    )
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_scalar(mapped_tenant))

    resolved = await resolve_tenant(session, "acc_a")

    assert resolved is mapped_tenant
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_tenant_fails_closed_for_unknown_account_when_tenants_exist():
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_scalar(None), _scalar(uuid.uuid4())])

    resolved = await resolve_tenant(session, "acc_unknown")

    assert resolved is None
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_tenant_bootstrap_binds_first_tenant_to_account_id():
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_scalar(None), _scalar(None)])
    session.flush = AsyncMock()

    resolved = await resolve_tenant(session, "acc_first")

    assert resolved.config == {"account_id": "acc_first"}
    session.add.assert_called_once_with(resolved)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_authenticated_unknown_account_is_rejected_without_tenant_fallback():
    account_id = "acc_unknown"
    valid_signature = hmac.new(
        settings.INTERNAL_API_KEY.encode("utf-8"), account_id.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    with patch("app.api.recovery.resolve_tenant", new_callable=AsyncMock, return_value=None):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_tenant(
                request=MagicMock(),
                x_account_id=account_id,
                x_signature=valid_signature,
                session=AsyncMock(),
            )

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_unconfirmed_success_event_never_recovers_case():
    tenant = Tenant(id=uuid.uuid4(), type=TenantType.CONSUMER, name="Tenant")
    event = MagicMock()
    event.external_id = "evt_unpaid"
    event.payload = {
        "event": "payment_link.paid",
        "payload": {
            "payment_link": {
                "entity": {"id": "plink_unpaid", "status": "created", "notes": {}}
            }
        },
    }
    session = AsyncMock()

    with patch("app.services.ingestion.RecoveryService.record_outcome", new_callable=AsyncMock) as record_outcome:
        await _handle_payment_success_event(session, event, tenant)

    record_outcome.assert_not_awaited()
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconciliation_of_unpaid_payment_link_does_not_recover_case():
    tenant = Tenant(id=uuid.uuid4(), type=TenantType.CONSUMER, name="Tenant")
    case = RecoveryCase(
        id=uuid.uuid4(), tenant_id=tenant.id, domain=RecoveryDomain.B2C,
        case_type=CaseType.PAYMENT_FAILED, status=CaseStatus.RISK_ASSESSED,
    )
    action = Action(
        id=uuid.uuid4(), case_id=case.id, tenant_id=tenant.id, decision_id=uuid.uuid4(),
        action_type=RecoveryAction.GENERATE_PAYMENT_LINK, status=ActionStatus.UNKNOWN,
    )
    attempt = ExecutionAttempt(
        id=uuid.uuid4(), action_id=action.id, attempt_number=1,
        status=ExecutionStatus.UNKNOWN, provider_request_id="plink_created", attempt_metadata={},
    )
    outbox = ExecutionOutbox(id=uuid.uuid4(), action_id=action.id, status=OutboxStatus.CLAIMED)
    adapter = MagicMock()
    adapter.provider_name = "razorpay"
    adapter.fetch_payment_link = AsyncMock(return_value=ProviderExecutionResult(
        status=ProviderOutcomeStatus.SUCCEEDED, provider="razorpay",
        provider_resource_id="plink_created", provider_status="created",
        retry_safety=RetrySafety.NOT_RETRIABLE,
    ))
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    await ReconciliationService.reconcile_action(session, action, attempt, outbox, case, adapter)

    assert action.status == ActionStatus.SUCCEEDED
    assert attempt.status == ExecutionStatus.SUCCEEDED
    assert outbox.status == OutboxStatus.COMPLETED
    assert case.status == CaseStatus.RISK_ASSESSED
    audit = session.add.call_args.args[0]
    assert audit.details["reconciliation_result"] == "RESOURCE_CONFIRMED_AWAITING_PAYMENT_CONFIRMATION"


@pytest.mark.asyncio
async def test_unsupported_action_is_cancelled_and_audited_before_dispatch():
    tenant = Tenant(id=uuid.uuid4(), type=TenantType.CONSUMER, name="Tenant")
    case = RecoveryCase(
        id=uuid.uuid4(), tenant_id=tenant.id, domain=RecoveryDomain.B2C,
        case_type=CaseType.PAYMENT_FAILED, status=CaseStatus.RISK_ASSESSED,
    )
    decision = DecisionRecord(
        id=uuid.uuid4(), case_id=case.id, tenant_id=tenant.id,
        proposed_action=RecoveryAction.SEND_REMINDER, baseline_action=RecoveryAction.SEND_REMINDER,
        policy_status=PolicyStatus.APPROVED, autonomy_level=AutonomyLevel.FULL_AUTO,
    )
    action = Action(
        id=uuid.uuid4(), case_id=case.id, tenant_id=tenant.id, decision_id=decision.id,
        action_type=RecoveryAction.SEND_REMINDER, status=ActionStatus.AUTHORIZED,
    )
    outbox = ExecutionOutbox(id=uuid.uuid4(), action_id=action.id, payload={}, status=OutboxStatus.CLAIMED, attempt_count=1)
    classification = RecoveryClassification(
        case_id=case.id, failure_category=FailureCategory.CUSTOMER_ACTION_REQUIRED,
        retryability=Retryability.REQUIRES_NEW_METHOD, recoverability=Recoverability.MEDIUM,
    )
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        _scalar(action), _scalar(case), _scalar(decision), _scalar(tenant),
        _scalar(classification), _scalar(None),
    ])
    adapter = MagicMock()
    adapter.create_payment_link = AsyncMock()

    with patch.object(ExecutionControlService, "is_execution_enabled", new_callable=AsyncMock, return_value=True):
        result = await ExecutionWorker(provider_adapter=adapter).process_outbox_item(session, outbox)

    assert result is None
    assert action.status == ActionStatus.CANCELLED
    assert outbox.status == OutboxStatus.FAILED
    adapter.create_payment_link.assert_not_awaited()
    audit = session.add.call_args.args[0]
    assert audit.event_type == "EXECUTION_PREFLIGHT_BLOCKED"
    assert "Unsupported execution action" in audit.details["reason"]


@pytest.mark.asyncio
async def test_memory_index_and_decision_collection_contract_match():
    assert QdrantMemoryService.COLLECTION_NAME == "historical_cases"
    assert QdrantMemoryService.COLLECTION_NAME in REQUIRED_COLLECTIONS

    client = AsyncMock()
    await QdrantMemoryService.index_recovery_measurement(
        measurement_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        payload={"failure_category": "UNKNOWN", "domain": "B2C", "outcome_status": "RECOVERED"},
        client=client,
    )

    assert client.upsert.call_args.kwargs["collection_name"] == "historical_cases"


@pytest.mark.asyncio
async def test_decision_retrieval_uses_configured_collection_name():
    """The decision-engine retrieval path must search the same configured
    recovery-memory collection used by measurement indexing (non-authoritative)."""
    from app.interfaces.knowledge import TenantAwareKnowledgeRetriever

    assert settings.QDRANT_COLLECTION_NAME == "historical_cases"

    client = AsyncMock()
    client.search = AsyncMock(return_value=[MagicMock(payload={"action_type": "RETRY_NOW"})])

    retriever = TenantAwareKnowledgeRetriever(tenant_id="tenant-123")
    with patch("app.interfaces.knowledge.get_qdrant", new_callable=AsyncMock, return_value=client):
        hits = await retriever.search_historical_cases(query_vector=[0.1] * 4, limit=2)

    assert len(hits) == 1
    assert client.search.call_args.kwargs["collection_name"] == settings.QDRANT_COLLECTION_NAME
