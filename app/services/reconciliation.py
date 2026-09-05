"""
app/services/reconciliation.py

Capability-specific state reconciliation service for ambiguous provider outcomes (UNKNOWN / timeout).
Queries the payment provider read APIs matching the specific capability executed
to establish whether the exact logical mutation succeeded before finalizing Action/Case.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.action import (
    Action,
    ActionStatus,
    ExecutionAttempt,
    ExecutionStatus,
    ExecutionOutbox,
    OutboxStatus,
)
from app.domain.decision import RecoveryAction
from app.domain.events import AuditEvent
from app.domain.provider import (
    FetchPaymentLinkRequest,
    FetchPaymentRequest,
    ProviderExecutionResult,
    ProviderOutcomeStatus,
    RetrySafety,
)
from app.domain.recovery_case import RecoveryCase, CaseStatus
from app.domain.state_machine import CaseStateMachine
from app.interfaces.provider import PaymentProviderAdapter

logger = logging.getLogger("ariv.services.reconciliation")


class ReconciliationService:
    """
    Reconciles ambiguous or UNKNOWN execution outcomes against the payment provider.
    Never blindly retries a financial mutation.
    Selects the read capability corresponding to the exact mutating operation.
    """

    @classmethod
    async def reconcile_action(
        cls,
        session: AsyncSession,
        action: Action,
        attempt: ExecutionAttempt,
        outbox: ExecutionOutbox,
        case: RecoveryCase,
        provider_adapter: PaymentProviderAdapter,
    ) -> ProviderExecutionResult:
        """
        Inspects provider state for an action in UNKNOWN status using capability-specific reconciliation.
        - GENERATE_PAYMENT_LINK -> fetch_payment_link
        - RETRY_NOW / payment mutation -> fetch_payment
        - CANCEL_PAYMENT_LINK -> fetch_payment_link & verify status
        """
        logger.info(
            "Initiating capability-specific reconciliation for Action %s (Type=%s, Attempt=%d)",
            action.id,
            action.action_type.value,
            attempt.attempt_number,
        )

        # Extract provider resource ID if available
        resource_id = attempt.provider_request_id or (
            attempt.attempt_metadata.get("id")
            if isinstance(attempt.attempt_metadata, dict)
            else None
        )

        if not resource_id:
            logger.warning(
                "No provider resource ID available for Action %s reconciliation. Keeping UNKNOWN for manual review.",
                action.id,
            )
            return ProviderExecutionResult(
                status=ProviderOutcomeStatus.UNKNOWN,
                provider=provider_adapter.provider_name,
                error_code="RECONCILIATION_PENDING",
                error_reason="Missing provider resource ID for automatic query",
                retry_safety=RetrySafety.UNKNOWN_RETRY_RISK,
            )

        # Capability-specific dispatch
        if action.action_type == RecoveryAction.GENERATE_PAYMENT_LINK:
            req = FetchPaymentLinkRequest(link_id=resource_id)
            result = await provider_adapter.fetch_payment_link(req)
        elif action.action_type in (RecoveryAction.RETRY_NOW, RecoveryAction.RETRY_LATER):
            req = FetchPaymentRequest(payment_id=resource_id)
            result = await provider_adapter.fetch_payment(req)
        elif action.action_type == RecoveryAction.CANCEL_PAYMENT_LINK:
            req = FetchPaymentLinkRequest(link_id=resource_id)
            result = await provider_adapter.fetch_payment_link(req)
            if result.status == ProviderOutcomeStatus.SUCCEEDED:
                # Must specifically verify the link is in cancelled state
                if result.provider_status != "cancelled":
                    result = ProviderExecutionResult(
                        status=ProviderOutcomeStatus.FAILED,
                        provider=provider_adapter.provider_name,
                        provider_request_id=result.provider_request_id,
                        provider_resource_id=result.provider_resource_id,
                        provider_status=result.provider_status,
                        error_code="CANCELLATION_UNCONFIRMED",
                        error_reason=f"Payment link status is '{result.provider_status}', expected 'cancelled'",
                        retry_safety=RetrySafety.NOT_RETRIABLE,
                    )
        else:
            req = FetchPaymentRequest(payment_id=resource_id)
            result = await provider_adapter.fetch_payment(req)

        audit_details = {
            "action_id": str(action.id),
            "attempt_id": str(attempt.id),
            "resource_id": resource_id,
            "action_type": action.action_type.value,
            "reconciled_status": result.status.value,
            "provider_status": result.provider_status,
        }

        if result.status == ProviderOutcomeStatus.SUCCEEDED:
            logger.info("Reconciliation confirmed SUCCESS for Action %s", action.id)
            attempt.status = ExecutionStatus.SUCCEEDED
            attempt.finished_at = datetime.now(timezone.utc)
            action.status = ActionStatus.SUCCEEDED
            outbox.status = OutboxStatus.COMPLETED
            outbox.dispatched = True
            outbox.dispatched_at = datetime.now(timezone.utc)

            # Reconcile Case state via State Machine if not already terminal
            if case.status in (CaseStatus.OPEN, CaseStatus.RISK_ASSESSED, CaseStatus.PENDING_APPROVAL):
                try:
                    CaseStateMachine.transition_to(case, CaseStatus.RECOVERED)
                except Exception as exc:
                    logger.warning("Could not transition case %s to RECOVERED: %s", case.id, exc)

            audit_details["reconciliation_result"] = "CONFIRMED_SUCCESS"

        elif result.status == ProviderOutcomeStatus.FAILED:
            logger.warning("Reconciliation confirmed FAILURE for Action %s", action.id)
            attempt.status = ExecutionStatus.FAILED
            attempt.finished_at = datetime.now(timezone.utc)
            action.status = ActionStatus.FAILED
            outbox.status = OutboxStatus.FAILED
            audit_details["reconciliation_result"] = "CONFIRMED_FAILURE"

        else:
            logger.warning("Reconciliation remains UNKNOWN for Action %s", action.id)
            audit_details["reconciliation_result"] = "STILL_UNKNOWN"

        audit = AuditEvent(
            case_id=case.id,
            event_type="EXECUTION_RECONCILED",
            details=audit_details,
        )
        session.add(audit)
        await session.flush()
        return result
