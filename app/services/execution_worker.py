"""
app/services/execution_worker.py

Durable Outbox Execution Worker for ARIV.
Enforces the 18-point pre-execution safety gate, DB-backed kill switch,
tenant isolation, idempotency, provider dispatch, and outcome reconciliation.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.action import (
    Action,
    ActionStatus,
    ExecutionAttempt,
    ExecutionStatus,
    ExecutionOutbox,
    OutboxStatus,
)
from app.domain.classification import FailureCategory, RecoveryClassification
from app.domain.decision import (
    AutonomyLevel,
    DecisionRecord,
    PolicyStatus,
    RecoveryAction,
)
from app.domain.events import AuditEvent
from app.domain.provider import (
    CreatePaymentLinkRequest,
    ProviderCapability,
    ProviderExecutionResult,
    ProviderOutcomeStatus,
    RetrySafety,
)
from app.domain.recovery_case import CaseStatus, RecoveryCase
from app.domain.schemas import DecisionProposal
from app.domain.state_machine import CaseStateMachine
from app.domain.tenant import Tenant
from app.interfaces.provider import PaymentProviderAdapter
from app.services.execution_control import ExecutionControlService
from app.services.outbox import OutboxService
from app.services.policy import PolicyEngine
from app.services.reconciliation import ReconciliationService
from app.services.recovery import RecoveryService
from app.services.system_settings import SystemSettingsService
from app.services.telegram import TelegramNotifier

logger = logging.getLogger("ariv.services.execution_worker")


class PreflightRejectionError(Exception):
    """Raised when pre-execution revalidation fails."""
    def __init__(self, reason: str, action_status: ActionStatus = ActionStatus.CANCELLED):
        self.reason = reason
        self.action_status = action_status
        super().__init__(f"Preflight check failed: {reason}")


class ExecutionPreflightValidator:
    """
    Authoritative 18-point pre-execution safety validator.
    Evaluated immediately prior to external provider mutation.
    """

    @classmethod
    async def validate(
        cls,
        session: AsyncSession,
        outbox: ExecutionOutbox,
        action: Action,
        case: Optional[RecoveryCase],
        decision: Optional[DecisionRecord],
        tenant: Optional[Tenant],
        provider_adapter: PaymentProviderAdapter,
    ) -> Tuple[bool, Optional[str], ActionStatus]:
        """
        Runs all 18 pre-execution checks in order.
        Returns: (is_valid, rejection_reason, recommended_action_status)
        """
        # 1. Action loaded
        if not action:
            return False, "Action record not found", ActionStatus.FAILED

        # 2. RecoveryCase loaded
        if not case:
            return False, f"RecoveryCase for Action {action.id} not found", ActionStatus.CANCELLED

        # 3. DecisionRecord loaded
        if not decision:
            return False, f"DecisionRecord for Action {action.id} not found", ActionStatus.CANCELLED

        # 4. Tenant loaded
        if not tenant:
            return False, f"Tenant for Action {action.id} not found", ActionStatus.CANCELLED

        # 5. Tenant consistency check across all models
        if not (action.tenant_id == case.tenant_id == decision.tenant_id == tenant.id):
            return (
                False,
                f"Tenant mismatch: action={action.tenant_id}, case={case.tenant_id}, decision={decision.tenant_id}, tenant={tenant.id}",
                ActionStatus.CANCELLED,
            )

        # 6. Case state check: Terminal states cannot execute
        if case.status in (CaseStatus.RECOVERED, CaseStatus.FAILED, CaseStatus.CLOSED):
            return (
                False,
                f"Case is in terminal state ({case.status.value}). Execution forbidden.",
                ActionStatus.SUPERSEDED,
            )

        # 7. Action state check: Must be in an executable state
        if action.status not in (ActionStatus.AUTHORIZED, ActionStatus.QUEUED, ActionStatus.EXECUTING):
            return (
                False,
                f"Action is not in executable state (current: {action.status.value}).",
                ActionStatus.SUPERSEDED,
            )

        # 8. Decision policy status: Must be APPROVED
        if decision.policy_status != PolicyStatus.APPROVED:
            return (
                False,
                f"Decision policy status is not APPROVED ({decision.policy_status.value}).",
                ActionStatus.CANCELLED,
            )

        # 9. Autonomy level check
        if decision.autonomy_level not in (AutonomyLevel.FULL_AUTO, AutonomyLevel.HUMAN_APPROVAL):
            return (
                False,
                f"Autonomy level {decision.autonomy_level.value} does not permit execution.",
                ActionStatus.CANCELLED,
            )

        # 10. Dynamic policy revalidation
        # Fetch current classification to check current safety rules
        class_res = await session.execute(
            select(RecoveryClassification)
            .where(RecoveryClassification.case_id == case.id)
            .order_by(RecoveryClassification.timestamp.desc())
            .limit(1)
        )
        classification = class_res.scalar_one_or_none()
        category = classification.failure_category if isinstance(classification, RecoveryClassification) else FailureCategory.UNKNOWN

        proposal = DecisionProposal(
            recommended_action=action.action_type,
            reason="Preflight policy revalidation",
            confidence=decision.ai_confidence,
            expected_irv=decision.expected_irv,
        )
        pol_status, _, pol_reason = PolicyEngine.evaluate(proposal, case.domain, category)
        if pol_status != PolicyStatus.APPROVED:
            return (
                False,
                f"PolicyEngine revalidation rejected action: {pol_reason}",
                ActionStatus.CANCELLED,
            )

        # 11. Retry budget check
        attempt_count = outbox.attempt_count if getattr(outbox, "attempt_count", None) is not None else 0
        max_retries = outbox.max_retries if getattr(outbox, "max_retries", None) is not None else 3
        if attempt_count > max_retries:
            return (
                False,
                f"Retry budget exceeded: attempt {attempt_count} > max {max_retries}",
                ActionStatus.FAILED,
            )

        # 12. Stopping rules: Non-retriable categories cannot execute retries
        if category == FailureCategory.NON_RETRIABLE and action.action_type in (
            RecoveryAction.RETRY_NOW,
            RecoveryAction.RETRY_LATER,
        ):
            return (
                False,
                "Stopping rule: Non-retriable failure cannot execute retry mutation.",
                ActionStatus.CANCELLED,
            )

        # 13. Check if action has already SUCCEEDED
        if action.status == ActionStatus.SUCCEEDED:
            return False, "Action has already succeeded.", ActionStatus.SUCCEEDED

        # 14. Check DB-backed Global Execution Kill Switch
        is_enabled = await ExecutionControlService.is_execution_enabled(session)
        if not is_enabled:
            return (
                False,
                "Global execution kill switch (execution_enabled) is disabled or unreachable.",
                ActionStatus.CANCELLED,
            )

        # 15. Check existing successful attempt (Idempotency)
        existing_res = await session.execute(
            select(ExecutionAttempt).where(
                ExecutionAttempt.action_id == action.id,
                ExecutionAttempt.status == ExecutionStatus.SUCCEEDED,
            )
        )
        existing_attempt = existing_res.scalar_one_or_none()
        if existing_attempt is not None and isinstance(existing_attempt, ExecutionAttempt):
            return False, "An execution attempt for this action has already succeeded.", ActionStatus.SUCCEEDED

        # 16. Provider capability check.  ARIV currently has one implemented
        # financial mutation: generating a Razorpay payment link.  Every other
        # RecoveryAction remains a valid decision concept but has no execution
        # adapter, scheduler, or communication provider behind it and must not
        # be represented as a successful no-op.
        if action.action_type != RecoveryAction.GENERATE_PAYMENT_LINK:
            return (
                False,
                f"Unsupported execution action: {action.action_type.value}. No provider capability is implemented.",
                ActionStatus.CANCELLED,
            )

        if provider_adapter is None:
            return (
                False,
                "Payment-link provider adapter is unavailable.",
                ActionStatus.CANCELLED,
            )

        return True, None, action.status


class ExecutionWorker:
    """
    Durable Outbox Execution Worker.
    Polls, claims, revalidates, executes via provider adapter, and reconciles outcomes.
    """

    def __init__(
        self,
        worker_id: Optional[str] = None,
        provider_adapter: Optional[PaymentProviderAdapter] = None,
        lease_duration_seconds: int = 30,
        batch_size: int = 10,
    ):
        self.worker_id = worker_id or f"worker_{uuid.uuid4().hex[:8]}"
        self.provider_adapter = provider_adapter
        self.lease_duration_seconds = lease_duration_seconds
        self.batch_size = batch_size

    async def process_outbox_item(
        self,
        session: AsyncSession,
        outbox: ExecutionOutbox,
    ) -> Optional[ProviderExecutionResult]:
        """
        Executes a single claimed outbox record with full preflight revalidation
        and safe outcome handling.
        """
        logger.info(
            "Worker %s processing Outbox %s (Action %s)",
            self.worker_id,
            outbox.id,
            outbox.action_id,
        )

        # 1. Load Action and related entities
        action_res = await session.execute(
            select(Action).where(Action.id == outbox.action_id)
        )
        action = action_res.scalar_one_or_none()

        if not action:
            outbox.status = OutboxStatus.FAILED
            outbox.last_error = "Action not found"
            await session.flush()
            return None

        case_res = await session.execute(
            select(RecoveryCase).where(RecoveryCase.id == action.case_id)
        )
        case = case_res.scalar_one_or_none()

        decision_res = await session.execute(
            select(DecisionRecord).where(DecisionRecord.id == action.decision_id)
        )
        decision = decision_res.scalar_one_or_none()

        tenant_res = await session.execute(
            select(Tenant).where(Tenant.id == action.tenant_id)
        )
        tenant = tenant_res.scalar_one_or_none()

        # 2. Run Authoritative Preflight Revalidation
        is_valid, reason, rec_status = await ExecutionPreflightValidator.validate(
            session=session,
            outbox=outbox,
            action=action,
            case=case,
            decision=decision,
            tenant=tenant,
            provider_adapter=self.provider_adapter,
        )

        if not is_valid:
            logger.warning(
                "Worker %s: Preflight failed for Action %s: %s (Setting status: %s)",
                self.worker_id,
                action.id,
                reason,
                rec_status.value,
            )
            action.status = rec_status
            outbox.status = (
                OutboxStatus.COMPLETED
                if rec_status == ActionStatus.SUCCEEDED
                else OutboxStatus.FAILED
            )
            outbox.last_error = reason

            audit = AuditEvent(
                case_id=case.id if case else None,
                event_type="EXECUTION_PREFLIGHT_BLOCKED",
                details={
                    "action_id": str(action.id),
                    "outbox_id": str(outbox.id),
                    "worker_id": self.worker_id,
                    "reason": reason,
                    "final_action_status": rec_status.value,
                },
            )
            session.add(audit)
            await session.flush()

            # Hook F: Alert on policy/safety rejection (non-blocking)
            if reason and any(k in reason.lower() for k in ["policy", "stopping rule", "safety", "non-retriable", "budget", "autonomy"]):
                try:
                    await TelegramNotifier.notify_policy_blocked(case=case, action=action, reason=reason)
                except Exception as exc:
                    logger.warning("Telegram policy block alert failed (non-fatal): %s", type(exc).__name__)

            return None

        # 3. Create ExecutionAttempt before provider call
        attempt = ExecutionAttempt(
            action_id=action.id,
            attempt_number=outbox.attempt_count,
            status=ExecutionStatus.EXECUTING,
            started_at=datetime.now(timezone.utc),
            attempt_metadata={"worker_id": self.worker_id},
        )
        action.status = ActionStatus.EXECUTING
        session.add(attempt)

        audit_start = AuditEvent(
            case_id=case.id,
            event_type="EXECUTION_ATTEMPT_STARTED",
            details={
                "action_id": str(action.id),
                "attempt_number": outbox.attempt_count,
                "worker_id": self.worker_id,
                "action_type": action.action_type.value,
            },
        )
        session.add(audit_start)
        await session.flush()

        payload_data = outbox.payload or {}
        amount = int(payload_data.get("amount", getattr(case, "amount", 10000) or 10000))
        currency = payload_data.get("currency", "INR")
        description = payload_data.get("description", f"ARIV Recovery - Case {case.id}")

        # Hook A: Alert when action attempt begins (non-blocking)
        try:
            await TelegramNotifier.notify_action_started(
                case=case,
                action=action,
                amount_minor=amount,
                currency=currency,
            )
        except Exception as exc:
            logger.warning("Telegram action started alert failed (non-fatal): %s", type(exc).__name__)

        # 4. Dispatch the only implemented provider mutation.
        if action.action_type == RecoveryAction.GENERATE_PAYMENT_LINK:
            # Prepare stable business idempotency identity (stable across retries of the same Action)
            idempotency_key = f"ariv:action:{action.id}"

            req = CreatePaymentLinkRequest(
                amount=amount,
                currency=currency,
                description=description,
                idempotency_key=idempotency_key,
                customer_name=payload_data.get("customer_name"),
                customer_email=payload_data.get("customer_email"),
                customer_phone=payload_data.get("customer_phone"),
                notes={"case_id": str(case.id), "tenant_id": str(tenant.id), "action_id": str(action.id)},
            )

            result: ProviderExecutionResult = await self.provider_adapter.create_payment_link(req)
        else:  # Defensive fallback; preflight must reject this branch.
            result = ProviderExecutionResult(
                status=ProviderOutcomeStatus.FAILED,
                provider="none",
                error_code="UNSUPPORTED_CAPABILITY",
                error_reason=f"No execution capability is implemented for {action.action_type.value}",
                retry_safety=RetrySafety.NOT_RETRIABLE,
            )

        # 5. Handle Provider Outcome
        now = datetime.now(timezone.utc)
        attempt.finished_at = now
        attempt.provider_request_id = result.provider_request_id

        if result.status == ProviderOutcomeStatus.SUCCEEDED:
            logger.info("Worker %s: Action %s SUCCEEDED", self.worker_id, action.id)
            attempt.status = ExecutionStatus.SUCCEEDED
            attempt.attempt_metadata = result.raw_metadata
            action.status = ActionStatus.SUCCEEDED
            outbox.status = OutboxStatus.COMPLETED
            outbox.dispatched = True
            outbox.dispatched_at = now

            # Differentiate action execution success (e.g. payment link generated)
            # from actual payment recovery (funds confirmed / captured).
            is_payment_completed = result.provider_status in ("paid", "captured")

            if is_payment_completed:
                # Transition RecoveryCase safely via State Machine to terminal RECOVERED
                if case.status in (CaseStatus.OPEN, CaseStatus.RISK_ASSESSED, CaseStatus.PENDING_APPROVAL):
                    try:
                        CaseStateMachine.transition_to(case, CaseStatus.RECOVERED)
                    except Exception as exc:
                        logger.warning("Case %s could not transition to RECOVERED: %s", case.id, exc)

                audit_success = AuditEvent(
                    case_id=case.id,
                    event_type="EXECUTION_SUCCEEDED",
                    details={
                        "action_id": str(action.id),
                        "attempt_number": outbox.attempt_count,
                        "worker_id": self.worker_id,
                        "provider_resource_id": result.provider_resource_id,
                        "recovery_status": "RECOVERED",
                    },
                )
                session.add(audit_success)

                # Record outcome and measurement on confirmed payment
                try:
                    outcome = await RecoveryService.record_outcome(session, case, tenant, action, result)
                    # Create context for measurement
                    from app.domain.schemas import DecisionContext
                    
                    # Fetch classification for context
                    class_res = await session.execute(
                        select(RecoveryClassification)
                        .where(RecoveryClassification.case_id == case.id)
                        .order_by(RecoveryClassification.timestamp.desc())
                        .limit(1)
                    )
                    classification = class_res.scalar_one_or_none()
                    context = DecisionContext(
                        case_id=str(case.id),
                        tenant_id=str(tenant.id),
                        domain=case.domain,
                        amount=float(case.amount_minor or 0) / 100.0,
                        currency=case.context.get("currency", "INR") if (case.context and isinstance(case.context, dict)) else "INR",
                        failure_category=classification.failure_category if classification else None,
                        retryability=classification.retryability if classification else None,
                        recoverability=classification.recoverability if classification else None,
                        time_since_failure_seconds=0,
                        intervention_count=0,
                        baseline_action=None,
                        historical_cases=[],
                        playbook_snippets=[],
                    )
                    await RecoveryService.create_measurement(session, outcome, context, action, cost_of_recovery=0)
                except Exception as e:
                    logger.error(f"Worker {self.worker_id}: Failed to record outcome/measurement for Action {action.id}: {e}")

                # Hook C: Alert when recovery is verified and attributed (non-blocking)
                if "outcome" in locals() and outcome:
                    try:
                        await TelegramNotifier.notify_recovery_verified(
                            case=case,
                            outcome=outcome,
                        )
                    except Exception as exc:
                        logger.warning("Telegram recovery verified alert failed (non-fatal): %s", type(exc).__name__)
            else:
                # Payment link generated successfully; waiting for customer payment
                ctx = dict(case.context or {})
                ctx["recovery_stage"] = "WAITING_FOR_PAYMENT"
                ctx["payment_link_id"] = result.provider_resource_id
                if result.raw_metadata and result.raw_metadata.get("short_url"):
                    ctx["payment_link_url"] = result.raw_metadata.get("short_url")
                case.context = ctx

                audit_link = AuditEvent(
                    case_id=case.id,
                    event_type="EXECUTION_SUCCEEDED",
                    details={
                        "action_id": str(action.id),
                        "attempt_number": outbox.attempt_count,
                        "worker_id": self.worker_id,
                        "provider_resource_id": result.provider_resource_id,
                        "short_url": result.raw_metadata.get("short_url") if result.raw_metadata else None,
                        "recovery_stage": "WAITING_FOR_PAYMENT",
                        "human_readable_message": f"🔗 Payment link created ({result.provider_resource_id}): {result.raw_metadata.get('short_url') if result.raw_metadata else 'Link generated'}. Waiting for customer payment.",
                    },
                )
                session.add(audit_link)

            # Hook B: Alert when recovery action succeeds (e.g. link dispatched) (non-blocking)
            try:
                await TelegramNotifier.notify_action_succeeded(
                    case=case,
                    action=action,
                    provider_resource_id=result.provider_resource_id,
                )
            except Exception as exc:
                logger.warning("Telegram action succeeded alert failed (non-fatal): %s", type(exc).__name__)

        elif result.status == ProviderOutcomeStatus.FAILED:
            logger.warning("Worker %s: Action %s FAILED (%s)", self.worker_id, action.id, result.error_reason)
            attempt.status = ExecutionStatus.FAILED
            attempt.attempt_metadata = {
                "error_code": result.error_code,
                "error_reason": result.error_reason,
            }
            action.status = ActionStatus.FAILED

            if result.retry_safety == RetrySafety.NOT_RETRIABLE or outbox.attempt_count >= outbox.max_retries:
                outbox.status = (
                    OutboxStatus.DEAD_LETTERED
                    if outbox.attempt_count >= outbox.max_retries
                    else OutboxStatus.FAILED
                )
            outbox.last_error = f"{result.error_code}: {result.error_reason}"

            audit_fail = AuditEvent(
                case_id=case.id,
                event_type="EXECUTION_FAILED",
                details={
                    "action_id": str(action.id),
                    "attempt_number": outbox.attempt_count,
                    "worker_id": self.worker_id,
                    "error_code": result.error_code,
                    "error_reason": result.error_reason,
                },
            )
            session.add(audit_fail)
            
            # Record failed outcome
            try:
                await RecoveryService.record_outcome(session, case, tenant, action, result)
            except Exception as e:
                logger.error(f"Worker {self.worker_id}: Failed to record outcome for Action {action.id}: {e}")

            # Hook D: Alert when execution fails (non-blocking)
            try:
                await TelegramNotifier.notify_action_failed(
                    case=case,
                    action=action,
                    reason=result.error_reason or result.error_code or "Provider execution failed",
                )
            except Exception as exc:
                logger.warning("Telegram action failed alert failed (non-fatal): %s", type(exc).__name__)

        elif result.status == ProviderOutcomeStatus.UNKNOWN:
            logger.warning("Worker %s: Action %s UNKNOWN outcome. Triggering reconciliation.", self.worker_id, action.id)
            attempt.status = ExecutionStatus.UNKNOWN
            attempt.attempt_metadata = {
                "error_code": result.error_code,
                "error_reason": result.error_reason,
            }
            action.status = ActionStatus.UNKNOWN
            outbox.last_error = f"UNKNOWN: {result.error_code}"

            audit_unknown = AuditEvent(
                case_id=case.id,
                event_type="EXECUTION_UNKNOWN",
                details={
                    "action_id": str(action.id),
                    "attempt_number": outbox.attempt_count,
                    "worker_id": self.worker_id,
                    "error_code": result.error_code,
                },
            )
            session.add(audit_unknown)
            
            # Record unknown outcome
            try:
                await RecoveryService.record_outcome(session, case, tenant, action, result)
            except Exception as e:
                logger.error(f"Worker {self.worker_id}: Failed to record outcome for Action {action.id}: {e}")

            # Trigger reconciliation immediately if resource_id exists
            await ReconciliationService.reconcile_action(
                session=session,
                action=action,
                attempt=attempt,
                outbox=outbox,
                case=case,
                provider_adapter=self.provider_adapter,
            )

            # Hook E: Alert on UNKNOWN provider state (non-blocking)
            try:
                rec_stat = "COMPLETED" if action.status in (ActionStatus.SUCCEEDED, ActionStatus.FAILED) else "PENDING"
                await TelegramNotifier.notify_action_unknown(
                    case=case,
                    action=action,
                    reconciliation_status=rec_stat,
                )
            except Exception as exc:
                logger.warning("Telegram action unknown alert failed (non-fatal): %s", type(exc).__name__)

        await session.flush()
        return result

    async def poll_once(self, session: AsyncSession) -> int:
        """
        Polls for and processes a batch of claimed outbox items.
        Returns the number of processed items.
        """
        claimed_items = await OutboxService.claim_pending_items(
            session=session,
            worker_id=self.worker_id,
            batch_size=self.batch_size,
            lease_seconds=self.lease_duration_seconds,
        )

        if not claimed_items:
            return 0

        for item in claimed_items:
            try:
                await self.process_outbox_item(session, item)
            except Exception as exc:
                logger.exception("Unexpected error processing Outbox %s: %s", item.id, exc)
                item.last_error = f"Unhandled worker exception: {str(exc)}"

        return len(claimed_items)
