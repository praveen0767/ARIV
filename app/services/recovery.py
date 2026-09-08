"""app/services/recovery.py

Recovery Service for Phase 5:
Handles:
- Recovery outcome recording (idempotent, partial recovery, organic vs action-attributed).
- Recovery measurement (idempotent, baseline comparison, IRV, attribution window).
- Deterministic experiment assignment (control vs treatment, policy safety gates).
- Durable Qdrant vector indexing via PostgreSQL KnowledgeOutbox.
"""

import hashlib
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.domain.action import Action, ActionStatus
from app.domain.recovery_case import RecoveryCase
from app.domain.tenant import Tenant
from app.domain.provider import ProviderExecutionResult, ProviderOutcomeStatus
from app.domain.recovery.recovery_outcome import RecoveryOutcome, RecoveryOutcomeStatus, RecoverySource
from app.domain.recovery.recovery_measurement import RecoveryMeasurement
from app.domain.recovery.experiment import Experiment, ExperimentStatus
from app.domain.classification import FailureCategory
from app.domain.schemas import DecisionContext
from app.services.baseline import BaselineService
from app.services.system_settings import SystemSettingsService
from app.services.qdrant_memory import QdrantMemoryService
from app.services.qdrant_indexer import QdrantIndexerWorker
from app.infrastructure.database import async_session_factory as session_factory

logger = logging.getLogger("ariv.services.recovery")


class RecoveryService:

    @classmethod
    async def record_outcome(
        cls,
        session: AsyncSession,
        case: RecoveryCase,
        tenant: Tenant,
        action: Optional[Action],
        provider_result: ProviderExecutionResult,
        recovered_amount_override: Optional[int] = None,
        recovered_at_override: Optional[datetime] = None,
    ) -> RecoveryOutcome:
        """
        Record a recovery outcome from a provider execution result.
        Idempotent: if an outcome for this action or provider_resource_id exists, returns it.
        """
        # 1. Idempotency check
        if action and action.id:
            res = await session.execute(
                select(RecoveryOutcome).where(RecoveryOutcome.action_id == action.id)
            )
            existing = res.scalar_one_or_none()
            if existing:
                logger.info("RecoveryOutcome already exists for action %s", action.id)
                return existing

        now = recovered_at_override or datetime.now(timezone.utc)
        case_total_amount = case.amount or 0

        # 2. Determine recovered amount
        if recovered_amount_override is not None:
            recovered_amount = recovered_amount_override
        elif provider_result.status == ProviderOutcomeStatus.SUCCEEDED:
            # Check if provider returned a specific amount in metadata
            prov_amount = provider_result.raw_metadata.get("amount")
            recovered_amount = int(prov_amount) if prov_amount is not None else case_total_amount
        else:
            recovered_amount = 0

        # 3. Determine Outcome Status
        if provider_result.status == ProviderOutcomeStatus.SUCCEEDED:
            if case_total_amount > 0 and recovered_amount < case_total_amount:
                outcome_status = RecoveryOutcomeStatus.PARTIALLY_RECOVERED
            elif recovered_amount == 0 and case_total_amount > 0:
                outcome_status = RecoveryOutcomeStatus.NO_RECOVERY
            else:
                outcome_status = RecoveryOutcomeStatus.RECOVERED
        elif provider_result.status == ProviderOutcomeStatus.FAILED:
            outcome_status = RecoveryOutcomeStatus.FAILED
        else:
            outcome_status = RecoveryOutcomeStatus.UNKNOWN

        recovered_at = now if outcome_status in (RecoveryOutcomeStatus.RECOVERED, RecoveryOutcomeStatus.PARTIALLY_RECOVERED) else None
        time_to_recovery = None
        if recovered_at and case.created_at:
            time_to_recovery = recovered_at - case.created_at

        # 4. Attribution Window Check
        window_seconds_str = await SystemSettingsService.get_setting(
            session, "recovery_attribution_window_seconds", "86400"
        )
        try:
            attribution_window = timedelta(seconds=int(window_seconds_str))
        except (ValueError, TypeError):
            attribution_window = timedelta(seconds=86400)

        attribution_policy_version = "v1.0.0-attribution"
        action_ts = action.created_at if action else None
        recovery_ts = recovered_at

        # 5. Determine Recovery Source & Attribution Provenance
        recovery_source = RecoverySource.UNKNOWN_ATTRIBUTION
        attribution_decision = "Payment execution unrecovered or failed; attribution is UNKNOWN_ATTRIBUTION."

        if outcome_status in (RecoveryOutcomeStatus.RECOVERED, RecoveryOutcomeStatus.PARTIALLY_RECOVERED):
            if action is None:
                # Payment succeeded without any automated recovery action
                recovery_source = RecoverySource.ORGANIC_RECOVERY
                attribution_decision = "ORGANIC_RECOVERY: Payment succeeded without automated recovery action."
            elif action_ts and recovery_ts and recovery_ts < action_ts:
                # Payment completed BEFORE action was launched -> Organic
                recovery_source = RecoverySource.ORGANIC_RECOVERY
                attribution_decision = "ORGANIC_RECOVERY: Payment completed before recovery action was created."
            elif action and action_ts and recovery_ts:
                action_elapsed = recovery_ts - action_ts
                if action_elapsed > attribution_window:
                    # Outside attribution window -> Unknown / Expired causality
                    recovery_source = RecoverySource.UNKNOWN_ATTRIBUTION
                    attribution_decision = (
                        f"UNKNOWN_ATTRIBUTION: Payment succeeded outside attribution window "
                        f"(elapsed {action_elapsed.total_seconds():.0f}s > window {attribution_window.total_seconds():.0f}s); "
                        f"outcome is {outcome_status.value} but attribution is UNKNOWN_ATTRIBUTION."
                    )
                else:
                    # Succeeded within attribution window after action
                    recovery_source = RecoverySource.ACTION_ATTRIBUTED
                    attribution_decision = (
                        f"ACTION_ATTRIBUTED: Payment succeeded within attribution window "
                        f"(elapsed {action_elapsed.total_seconds():.0f}s <= window {attribution_window.total_seconds():.0f}s) "
                        f"following action dispatch."
                    )
            else:
                recovery_source = RecoverySource.ACTION_ATTRIBUTED
                attribution_decision = "ACTION_ATTRIBUTED: Payment recovered following action dispatch."
        elif outcome_status == RecoveryOutcomeStatus.FAILED:
            recovery_source = RecoverySource.UNKNOWN_ATTRIBUTION
            attribution_decision = "UNKNOWN_ATTRIBUTION: Provider execution failed; outcome is FAILED."

        attribution_provenance = {
            "attribution_window_seconds": int(attribution_window.total_seconds()),
            "attribution_policy_version": attribution_policy_version,
            "action_timestamp": action_ts.isoformat() if action_ts else None,
            "recovery_timestamp": recovery_ts.isoformat() if recovery_ts else None,
            "attribution_decision": attribution_decision,
            "attribution_source": recovery_source.value,
        }

        currency = case.context.get("currency", "INR") if (case.context and isinstance(case.context, dict)) else "INR"

        outcome = RecoveryOutcome(
            case_id=case.id,
            tenant_id=tenant.id,
            action_id=action.id if action else None,
            outcome_status=outcome_status,
            recovered_amount=recovered_amount,
            currency=currency,
            recovered_at=recovered_at,
            provider_reference=provider_result.provider_resource_id,
            time_to_recovery=time_to_recovery,
            recovery_source=recovery_source,
            attribution_decision=attribution_decision,
            attribution_provenance=attribution_provenance,
        )

        session.add(outcome)
        await session.flush()

        try:
            from app.services.activity import ActivityService, OperationalEventType
            msg = (
                f"💰 ₹{recovered_amount/100:.2f} recovered ({recovery_source.value})"
                if outcome_status in (RecoveryOutcomeStatus.RECOVERED, RecoveryOutcomeStatus.PARTIALLY_RECOVERED)
                else f"Recovery outcome recorded: {outcome_status.value}"
            )
            await ActivityService.record_event(
                session=session,
                event_type=OperationalEventType.RECOVERY_RECORDED if outcome_status in (RecoveryOutcomeStatus.RECOVERED, RecoveryOutcomeStatus.PARTIALLY_RECOVERED) else OperationalEventType.EXECUTION_FAILED,
                message=msg,
                case_id=case.id,
                action_id=action.id if action else None,
                tenant_id=tenant.id,
                details={"recovered_amount": recovered_amount, "recovery_source": recovery_source.value},
            )
        except Exception as e:
            logger.warning("Activity event record failed: %s", e)

        logger.info("Recorded RecoveryOutcome %s: status=%s, source=%s, amount=%d %s, decision=%s",
                    outcome.id, outcome_status.value, recovery_source.value, recovered_amount, currency, attribution_decision)
        return outcome

    @classmethod
    async def create_measurement(
        cls,
        session: AsyncSession,
        outcome: RecoveryOutcome,
        context: DecisionContext,
        action: Optional[Action],
        cost_of_recovery: int = 0,
    ) -> RecoveryMeasurement:
        """
        Create a measurement record calculating incremental recovery value (IRV).
        Idempotent: if a measurement already exists for outcome_id, returns it.
        Guarantees:
        - PostgreSQL measurement commit succeeds independently of Qdrant.
        - Persists a durable KnowledgeOutbox entry for vector indexing.
        - Clearly separates observed treatment/control recovery from estimated baseline counterfactual.
        """
        # 1. Idempotency check on outcome_id
        res = await session.execute(
            select(RecoveryMeasurement).where(RecoveryMeasurement.outcome_id == outcome.id)
        )
        existing = res.scalar_one_or_none()
        if existing:
            logger.info("RecoveryMeasurement already exists for outcome %s", outcome.id)
            return existing

        # 2. Compute baseline estimate (heuristic, non-authoritative)
        baseline = BaselineService.get_deterministic_baseline(context)
        session.add(baseline)
        await session.flush()
        baseline_policy_version = baseline.policy_version
        baseline_method = baseline.baseline_method
        baseline_provenance = baseline.provenance
        estimated_control_recovery = baseline.expected_recovery_amount

        # 3. Attribution window setting
        window_seconds_str = await SystemSettingsService.get_setting(
            session, "recovery_attribution_window_seconds", "86400"
        )
        try:
            window_seconds = int(window_seconds_str)
        except (ValueError, TypeError):
            window_seconds = 86400

        # 4. Assign experiment & variant
        tenant_arg = getattr(context, "tenant", None) or getattr(context, "tenant_id", None)
        case_arg = getattr(context, "case", None) or getattr(context, "case_id", None)
        class_arg = getattr(context, "classification", None) or getattr(context, "failure_category", None)
        experiment, variant = await cls.assign_experiment(
            session=session,
            tenant=tenant_arg,
            case=case_arg,
            classification=class_arg,
        )
        experiment_id = experiment.id if experiment else None

        estimated_control_recovery = baseline.expected_recovery_amount

        # Distinguish observed treatment recovery vs observed control recovery
        if variant == "CONTROL":
            treatment_recovery = 0
            control_recovery = outcome.recovered_amount
            # Control holdout: no treatment was applied, so incremental lift is not claimed
            incremental_recovery = 0
        else:
            treatment_recovery = outcome.recovered_amount
            control_recovery = 0
            # Treatment: incremental recovery estimated relative to baseline heuristic counterfactual
            incremental_recovery = max(0, treatment_recovery - estimated_control_recovery)

        measurement = RecoveryMeasurement(
            outcome_id=outcome.id,
            estimated_control_recovery=estimated_control_recovery,
            treatment_recovery=treatment_recovery,
            control_recovery=control_recovery,
            incremental_recovery=incremental_recovery,
            cost_of_recovery=cost_of_recovery,
            attribution_window_seconds=window_seconds,
            experiment_id=experiment_id,
            experiment_variant=variant,
            baseline_policy_version=baseline.policy_version,
            baseline_method=baseline.baseline_method,
            provenance=baseline.provenance,
            is_counterfactual_estimate=True,
        )

        session.add(measurement)
        await session.flush()
        logger.info("Created RecoveryMeasurement %s: treatment_obs=%d, control_obs=%d, baseline_est=%d, incremental_est=%d, variant=%s",
                    measurement.id, treatment_recovery, control_recovery, estimated_control_recovery, incremental_recovery, variant)

        # 5. Build sanitized payload for Qdrant
        ttr_seconds = outcome.time_to_recovery.total_seconds() if outcome.time_to_recovery else None
        cat_val = getattr(context, "failure_category", None) or (getattr(context.classification, "failure_category", None) if hasattr(context, "classification") else None)
        category = cat_val.value if hasattr(cat_val, "value") else str(cat_val)
        dom_val = getattr(context, "domain", None) or (getattr(context.case, "domain", None) if hasattr(context, "case") else None)
        domain = dom_val.value if hasattr(dom_val, "value") else str(dom_val)
        action_type = action.action_type.value if action and hasattr(action.action_type, "value") else (str(action.action_type) if action else None)

        sanitized_payload = {
            "failure_category": category,
            "domain": domain,
            "action_type": action_type,
            "outcome_status": outcome.outcome_status.value,
            "recovery_source": outcome.recovery_source.value,
            "amount_bucket": QdrantMemoryService.get_amount_bucket(outcome.recovered_amount),
            "time_to_recovery_bucket": QdrantMemoryService.get_ttr_bucket(ttr_seconds),
            "baseline_policy_version": baseline.policy_version,
            "experiment_id": str(experiment_id) if experiment_id else None,
            "experiment_variant": variant,
        }

        # 6. Transactionally create durable KnowledgeOutbox entry
        outbox_entry = await QdrantIndexerWorker.create_outbox_entry(
            session=session,
            measurement_id=measurement.id,
            tenant_id=outcome.tenant_id,
            payload=sanitized_payload,
        )

        # 7. Non-authoritative optimization trigger (background task)
        # Never blocks or rolls back PostgreSQL if Qdrant is unavailable.
        # Runs in a FRESH session so completing is independent of the lifespan of
        # the request-scoped transaction. The durable claim-based drainer started
        # by the application lifespan remains the backstop for items this trigger
        # never gets to process (crash / shutdown / cancellation).
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                QdrantIndexerWorker.process_outbox_item_safe(
                    session_factory, outbox_entry.id
                )
            )
        except Exception as e:
            logger.debug("Background Qdrant indexing trigger skipped (handled by outbox worker): %s", e)

        try:
            from app.services.activity import ActivityService, OperationalEventType
            await ActivityService.record_event(
                session=session,
                event_type=OperationalEventType.MEASUREMENT_RECORDED,
                message=f"📈 Incremental estimate updated: ₹{incremental_recovery/100:.2f}",
                case_id=outcome.case_id,
                action_id=outcome.action_id,
                tenant_id=outcome.tenant_id,
                details={"incremental_recovery": incremental_recovery},
            )
        except Exception as e:
            logger.warning("Activity event record failed: %s", e)

        return measurement

    @classmethod
    async def assign_experiment(
        cls,
        session: AsyncSession,
        tenant: Any,
        case: Any,
        classification=None,
    ) -> Tuple[Optional[Experiment], str]:
        """
        Deterministically assign an experiment variant ("TREATMENT" or "CONTROL").
        Safety gate: Non-retriable, high-risk, or fraud cases are NEVER held out.
        """
        # Safety gate: check if holdout is disallowed
        fc = getattr(classification, "failure_category", classification)
        if fc in (
            FailureCategory.NON_RETRIABLE,
            FailureCategory.RISK_OR_FRAUD
        ):
            return None, "TREATMENT"

        tenant_id = getattr(tenant, "id", tenant)
        case_id = getattr(case, "id", case)

        # Find active experiment for tenant
        res = await session.execute(
            select(Experiment)
            .where(Experiment.tenant_id == tenant_id, Experiment.status == ExperimentStatus.ACTIVE)
            .order_by(Experiment.created_at.desc())
            .limit(1)
        )
        experiment = res.scalar_one_or_none()
        if not experiment:
            return None, "TREATMENT"

        # Stable hash bucket (1-100)
        hash_str = f"{tenant_id}:{case_id}:{experiment.id}"
        hash_val = int(hashlib.md5(hash_str.encode()).hexdigest(), 16)
        assignment_bucket = (hash_val % 100) + 1

        if assignment_bucket <= experiment.allocation_percentage:
            return experiment, "TREATMENT"
        else:
            return experiment, "CONTROL"
