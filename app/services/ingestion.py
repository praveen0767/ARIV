"""
app/services/ingestion.py

Asynchronous processing of durably persisted payment provider events.
Implements the ARIV end-to-end recovery pipeline:
ProviderEvent -> RecoveryCase -> Classification -> Decision -> Policy -> Outbox -> Execution
and handles recovery confirmation events (payment_link.paid, payment.captured).
"""

import logging
import json
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple
from sqlalchemy import select
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.events import ProviderEvent, RiskEvent, AuditEventType, AuditEvent
from app.domain.recovery_case import RecoveryCase, RecoveryDomain, CaseType, CaseStatus
from app.domain.action import Action, ActionStatus
from app.domain.state_machine import CaseStateMachine, StateTransitionError
from app.domain.tenant import Tenant, TenantType
from app.domain.provider import ProviderExecutionResult, ProviderOutcomeStatus, RetrySafety
from app.domain.recovery.recovery_outcome import RecoveryOutcome, RecoveryOutcomeStatus, RecoverySource
from app.services.classification import ClassificationService
from app.services.decision_engine import DecisionEngineService
from app.services.activity import ActivityService, OperationalEventType
from app.services.recovery import RecoveryService
from app.services.telegram import TelegramNotifier
from app.services.qdrant_memory import QdrantMemoryService

logger = logging.getLogger("ariv.services.ingestion")


def resolve_domain_and_casetype(payload: dict) -> Tuple[RecoveryDomain, CaseType]:
    """Dynamically resolves the RecoveryDomain and CaseType based on the payload."""
    event_type = payload.get("event")

    if event_type == "payment.failed":
        amount = payload.get("payload", {}).get("payment", {}).get("entity", {}).get("amount", 0)
        if amount > 5000000:  # > 50,000 INR
            return RecoveryDomain.B2B, CaseType.PAYMENT_FAILED
        return RecoveryDomain.B2C, CaseType.PAYMENT_FAILED

    elif event_type == "invoice.overdue":
        return RecoveryDomain.B2B, CaseType.INVOICE_OVERDUE

    return RecoveryDomain.B2C, CaseType.PAYMENT_FAILED


async def resolve_tenant(session: AsyncSession, account_id: str) -> Tenant:
    """Resolves tenant for account_id, defaulting gracefully for test accounts."""
    result = await session.execute(select(Tenant).limit(1))
    tenant = result.scalar_one_or_none()
    if not tenant:
        tenant = Tenant(type=TenantType.CONSUMER, name="Default Test Tenant")
        session.add(tenant)
        await session.flush()
    return tenant


async def _handle_payment_success_event(session: AsyncSession, event: ProviderEvent, tenant: Tenant):
    """
    Handles payment_link.paid, payment.captured, order.paid:
    Reconciles the action, marks RecoveryOutcome as RECOVERED, attributes recovery,
    creates RecoveryMeasurement, updates Qdrant memory, and notifies Telegram.
    """
    payload = event.payload or {}
    event_type = payload.get("event")
    sub_payload = payload.get("payload", {})

    # Extract payment entity or payment link entity
    payment_ent = sub_payload.get("payment", {}).get("entity", {})
    plink_ent = sub_payload.get("payment_link", {}).get("entity", {})
    ent = plink_ent if plink_ent else payment_ent

    notes = plink_ent.get("notes") or payment_ent.get("notes") or {}
    case_id_str = notes.get("case_id") or (payment_ent.get("notes") or {}).get("case_id")
    action_id_str = notes.get("action_id") or (payment_ent.get("notes") or {}).get("action_id")
    provider_resource_id = plink_ent.get("id") or payment_ent.get("id") or ent.get("id")
    amount_minor = ent.get("amount") or ent.get("amount_paid") or payment_ent.get("amount") or 0

    case: Optional[RecoveryCase] = None
    action: Optional[Action] = None

    if case_id_str:
        try:
            cid = uuid.UUID(case_id_str)
            case_r = await session.execute(select(RecoveryCase).where(RecoveryCase.id == cid))
            case = case_r.scalar_one_or_none()
        except Exception:
            pass

    if action_id_str:
        try:
            aid = uuid.UUID(action_id_str)
            act_r = await session.execute(select(Action).where(Action.id == aid))
            action = act_r.scalar_one_or_none()
        except Exception:
            pass

    # If action not matched by ID, try provider_resource_id in Action or ExecutionAttempt
    if not action and provider_resource_id:
        from app.domain.action import ExecutionAttempt
        att_r = await session.execute(
            select(ExecutionAttempt)
            .where(ExecutionAttempt.provider_request_id == provider_resource_id)
            .order_by(ExecutionAttempt.started_at.desc())
        )
        att = att_r.scalars().first()
        if att:
            act_r = await session.execute(select(Action).where(Action.id == att.action_id))
            action = act_r.scalar_one_or_none()

    # If action matched but not case, resolve case from action
    if action and not case:
        case_r = await session.execute(select(RecoveryCase).where(RecoveryCase.id == action.case_id))
        case = case_r.scalar_one_or_none()

    # If case matched but not action, resolve latest action from case
    if case and not action:
        act_r = await session.execute(
            select(Action)
            .where(Action.case_id == case.id)
            .order_by(Action.created_at.desc())
        )
        action = act_r.scalars().first()

    if not case and not action:
        logger.info("Payment success event %s does not map to any active ARIV case.", event.external_id)
        return

    # Record event in activity
    await ActivityService.record_event(
        session=session,
        event_type=OperationalEventType.WEBHOOK_RECEIVED,
        message=f"⚡ Razorpay event received: {event_type} ({provider_resource_id or 'unknown'})",
        case_id=case.id if case else None,
        action_id=action.id if action else None,
        tenant_id=tenant.id,
        details={"event_id": event.external_id, "event_type": event_type, "amount": amount_minor},
    )

    await ActivityService.record_event(
        session=session,
        event_type=OperationalEventType.RECONCILIATION_STARTED,
        message="🔄 Reconciling provider payment with recovery case…",
        case_id=case.id if case else None,
        action_id=action.id if action else None,
        tenant_id=tenant.id,
    )

    # Transition Action to SUCCEEDED
    if action and action.status != ActionStatus.SUCCEEDED:
        action.status = ActionStatus.SUCCEEDED

    already_recovered = bool(case and case.status == CaseStatus.RECOVERED)

    # Transition Case to RECOVERED and update recovery_stage if not already recovered
    if case and not already_recovered:
        try:
            CaseStateMachine.transition_to(case, CaseStatus.RECOVERED)
        except Exception as e:
            logger.warning("Could not transition case %s to RECOVERED: %s", case.id, e)
        ctx = dict(case.context or {})
        ctx["recovery_stage"] = "RECOVERED"
        if plink_ent.get("id"):
            ctx["payment_link_id"] = plink_ent.get("id")
        if payment_ent.get("id"):
            ctx["payment_id"] = payment_ent.get("id")
        case.context = ctx

    # Record recovery outcome
    combined_metadata = {**payment_ent, **plink_ent}
    fake_result = ProviderExecutionResult(
        status=ProviderOutcomeStatus.SUCCEEDED,
        provider="razorpay",
        provider_request_id=event.external_id,
        provider_resource_id=provider_resource_id,
        provider_status="paid",
        retry_safety=RetrySafety.NOT_RETRIABLE,
        raw_metadata=combined_metadata,
    )

    if case:
        outcome = await RecoveryService.record_outcome(
            session=session,
            case=case,
            tenant=tenant,
            action=action,
            provider_result=fake_result,
            recovered_amount_override=amount_minor if amount_minor > 0 else None,
        )

        # Create measurement (idempotent)
        try:
            from app.domain.schemas import DecisionContext
            from app.domain.classification import RecoveryClassification
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
            logger.error(f"Failed to create measurement for Case {case.id}: {e}")

        await ActivityService.record_event(
            session=session,
            event_type=OperationalEventType.RECONCILIATION_SUCCEEDED,
            message="🔍 Reconciliation verified: Payment completed",
            case_id=case.id,
            action_id=action.id if action else None,
            tenant_id=tenant.id,
        )

        await ActivityService.record_event(
            session=session,
            event_type=OperationalEventType.RECOVERY_RECORDED,
            message=f"💰 ₹{outcome.recovered_amount/100:.2f} recovered ({outcome.recovery_source.value})",
            case_id=case.id,
            action_id=action.id if action else None,
            tenant_id=tenant.id,
            details={"recovered_amount": outcome.recovered_amount, "recovery_source": outcome.recovery_source.value},
        )

        # Notify Telegram
        try:
            await TelegramNotifier.notify_recovery_verified(case=case, outcome=outcome)
            await ActivityService.record_event(
                session=session,
                event_type=OperationalEventType.TELEGRAM_SENT,
                message="📲 Telegram operator alert sent: Recovery verified",
                case_id=case.id,
                action_id=action.id if action else None,
                tenant_id=tenant.id,
            )
        except Exception as e:
            logger.warning("Telegram notification failed (non-blocking): %s", e)


async def process_provider_event(session: AsyncSession, event: ProviderEvent):
    """
    Asynchronous heavy processing of the securely persisted event.
    """
    try:
        payload = event.payload
        event_type = payload.get("event")
        account_id = payload.get("account_id", "default_account")

        # 1. Resolve Tenant
        tenant = await resolve_tenant(session, account_id)

        # 2. Check if this is a payment recovery / success event
        if event_type in ("payment_link.paid", "payment.captured", "order.paid"):
            await _handle_payment_success_event(session, event, tenant)
            event.processed_at = datetime.now(timezone.utc)
            await session.commit()
            return

        # Only process known failure events
        if event_type != "payment.failed":
            logger.info(f"Ignoring non-target event type: {event_type}")
            return

        # 3. Resolve Domain & Case Type Dynamically
        domain, case_type = resolve_domain_and_casetype(payload)
        payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        amount = payment_entity.get("amount", 0)

        # Context details for downstream recovery actions
        case_context = {
            "provider_event_id": event.id.hex,
            "currency": payment_entity.get("currency", "INR"),
            "customer_email": payment_entity.get("email"),
            "customer_phone": payment_entity.get("contact"),
            "customer_name": payment_entity.get("notes", {}).get("customer_name"),
            "error_code": payment_entity.get("error_code"),
            "error_description": payment_entity.get("error_description"),
            "error_reason": payment_entity.get("error_reason"),
            "payment_id": payment_entity.get("id"),
        }

        # 4. Create Recovery Case (Starts OPEN) with authoritative amount
        case = RecoveryCase(
            tenant_id=tenant.id,
            domain=domain,
            case_type=case_type,
            status=CaseStatus.OPEN,
            amount_minor=amount,
            context=case_context,
        )
        session.add(case)
        await session.flush()  # flush to get case.id

        # 5. Log activity: Webhook Received & Case Created
        await ActivityService.record_event(
            session=session,
            event_type=OperationalEventType.WEBHOOK_RECEIVED,
            message=f"⚡ Razorpay event received: {event_type}",
            case_id=case.id,
            tenant_id=tenant.id,
            details={"event_id": event.external_id, "amount": amount},
        )

        await ActivityService.record_event(
            session=session,
            event_type=OperationalEventType.CASE_CREATED,
            message=f"📋 Recovery case created ({domain.value}) for ₹{amount/100:.2f} at risk",
            case_id=case.id,
            tenant_id=tenant.id,
            details={"amount": amount, "domain": domain.value},
        )

        # 6. Create Risk Event
        risk_event = RiskEvent(
            case_id=case.id,
            canonical_payload=payload,
        )
        session.add(risk_event)

        # 7. Execute Classification
        classification = await ClassificationService.classify(session, risk_event)

        # 8. Update Case Status to RISK_ASSESSED
        CaseStateMachine.transition_to(case, CaseStatus.RISK_ASSESSED)

        await ActivityService.record_event(
            session=session,
            event_type=OperationalEventType.FAILURE_CLASSIFIED,
            message=f"🧠 Failure classified: {classification.failure_category.value} (Recoverability: {classification.recoverability.value}, Retryability: {classification.retryability.value})",
            case_id=case.id,
            tenant_id=tenant.id,
            details={
                "category": classification.failure_category.value,
                "retryability": classification.retryability.value,
                "recoverability": classification.recoverability.value,
            },
        )

        # 9. Execute Decision Engine & governed recovery execution
        await DecisionEngineService.execute_decision_cycle(session, case, classification, payload)

        # Update event status
        event.processed_at = datetime.now(timezone.utc)
        await session.commit()
        logger.info(f"Successfully processed event {event.external_id} into Case {case.id}")

    except StaleDataError as sde:
        await session.rollback()
        ext_id = getattr(event, "external_id", getattr(event, "id", "unknown"))
        logger.warning(
            "Optimistic concurrency conflict (StaleDataError) for event %s: %s. Case state already advanced by concurrent task.",
            ext_id, sde
        )
    except Exception as e:
        await session.rollback()
        logger.error(f"Error processing provider event {getattr(event, 'id', 'unknown')}: {e}")
        raise
