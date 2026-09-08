"""app/services/dashboard.py

Service layer for ARIV Phase 6 Recovery Dashboard & Buildathon Product Experience.
Provides:
- Aggregated KPI metrics & recovery funnel (observed vs estimated).
- Action performance analytics.
- Full case detail with structured decision explanation, policy boundary, execution status, and audit timeline.
- Tenant-isolated similar recovery case retrieval from Qdrant memory.
- Deterministic, idempotent sandbox demo seeding under explicit DEMO_MODE.
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc, cast, String
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.domain.tenant import Tenant
from app.domain.recovery_case import RecoveryCase, CaseStatus, CaseType, RecoveryDomain
from app.domain.classification import RecoveryClassification, FailureCategory, Retryability, Recoverability
from app.domain.decision import DecisionRecord, RecoveryAction, PolicyStatus, AutonomyLevel
from app.domain.action import Action, ActionStatus, ExecutionAttempt, ExecutionStatus
from app.domain.provider import ProviderExecutionResult, ProviderOutcomeStatus, RetrySafety
from app.domain.recovery.recovery_outcome import RecoveryOutcome, RecoveryOutcomeStatus, RecoverySource
from app.domain.recovery.recovery_measurement import RecoveryMeasurement
from app.services.embedding import EmbeddingService
from app.services.qdrant_memory import QdrantMemoryService
from app.services.recovery import RecoveryService
from app.services.activity import ActivityService

logger = logging.getLogger("ariv.services.dashboard")


def _make_decision_context(case, tenant, classification, baseline_action=RecoveryAction.GENERATE_PAYMENT_LINK):
    from app.domain.schemas import DecisionContext
    return DecisionContext(
        case_id=str(case.id),
        tenant_id=str(tenant.id),
        domain=case.domain,
        amount=float(case.amount_minor or 0) / 100.0,
        currency="INR",
        failure_category=classification.failure_category,
        retryability=classification.retryability,
        recoverability=classification.recoverability,
        time_since_failure_seconds=0,
        intervention_count=0,
        baseline_action=baseline_action,
    )


class DashboardService:


    @classmethod
    async def get_dashboard_data(cls, session: AsyncSession, tenant: Tenant) -> Dict[str, Any]:
        """
        Aggregate top KPIs, visual funnel steps, action performance, and recent cases for tenant.
        Strictly tenant-scoped. Distinguishes observed recovery from estimated counterfactuals.
        """
        # 1. Query all cases for tenant
        cases_res = await session.execute(
            select(RecoveryCase).where(RecoveryCase.tenant_id == tenant.id).order_by(desc(RecoveryCase.created_at))
        )
        cases = list(cases_res.scalars().all())
        case_ids = [c.id for c in cases]

        total_cases_count = len(cases)
        revenue_at_risk = sum(c.amount or 0 for c in cases)

        if not case_ids:
            return {
                "tenant_id": str(tenant.id),
                "kpis": {
                    "revenue_at_risk": 0,
                    "eligible_recovery": 0,
                    "attempted_recovery": 0,
                    "recovered_revenue": 0,
                    "estimated_incremental_recovery": 0,
                    "recovery_rate_pct": 0.0,
                    "is_estimate": True,
                    "label": "ESTIMATE",
                },
                "funnel": [
                    {"stage": "Revenue At Risk", "amount": 0, "count": 0, "badge": "OBSERVED"},
                    {"stage": "Eligible", "amount": 0, "count": 0, "badge": "OBSERVED"},
                    {"stage": "Actioned", "amount": 0, "count": 0, "badge": "OBSERVED"},
                    {"stage": "Recovered", "amount": 0, "count": 0, "badge": "OBSERVED"},
                    {"stage": "Incremental Estimate", "amount": 0, "count": 0, "badge": "ESTIMATE"},
                ],
                "action_performance": [],
                "recent_cases": [],
                "recent_activity": await ActivityService.get_recent_activity(session=session, tenant_id=tenant.id, limit=20),
            }

        # 2. Query outcomes
        outcomes_res = await session.execute(
            select(RecoveryOutcome).where(RecoveryOutcome.tenant_id == tenant.id)
        )
        outcomes = list(outcomes_res.scalars().all())
        outcomes_by_case = {o.case_id: o for o in outcomes}

        recovered_outcomes = [
            o for o in outcomes
            if o.outcome_status in (RecoveryOutcomeStatus.RECOVERED, RecoveryOutcomeStatus.PARTIALLY_RECOVERED)
        ]
        recovered_revenue = sum(o.recovered_amount for o in recovered_outcomes)
        recovered_count = len(recovered_outcomes)

        # 3. Query measurements
        meas_res = await session.execute(
            select(RecoveryMeasurement)
            .select_from(RecoveryMeasurement)
            .join(RecoveryOutcome, RecoveryMeasurement.outcome_id == RecoveryOutcome.id)
            .where(RecoveryOutcome.tenant_id == tenant.id)
        )
        measurements = list(meas_res.scalars().all())
        incremental_estimate = sum(m.incremental_recovery for m in measurements)
        observed_treatment = sum(m.treatment_recovery for m in measurements)
        observed_control = sum(m.control_recovery for m in measurements)

        # 4. Query actions
        actions_res = await session.execute(
            select(Action).options(selectinload(Action.attempts)).where(Action.tenant_id == tenant.id)
        )
        actions = list(actions_res.scalars().all())
        actioned_case_ids = {a.case_id for a in actions if a.status != ActionStatus.CANCELLED}
        actioned_cases = [c for c in cases if c.id in actioned_case_ids]
        actioned_amount = sum(c.amount or 0 for c in actioned_cases)
        actioned_count = len(actioned_cases)

        # Eligible cases (non-terminal / allowed recovery)
        eligible_cases = [
            c for c in cases
            if c.status not in (CaseStatus.CLOSED, CaseStatus.FAILED)
        ]
        eligible_amount = sum(c.amount or 0 for c in eligible_cases)
        eligible_count = len(eligible_cases)

        recovery_rate_pct = round((recovered_revenue / revenue_at_risk * 100.0), 1) if revenue_at_risk > 0 else 0.0

        # 5. Action Performance Breakdown
        action_stats: Dict[str, Dict[str, Any]] = {}
        for act in actions:
            act_type = act.action_type.value if hasattr(act.action_type, "value") else str(act.action_type)
            if act_type not in action_stats:
                action_stats[act_type] = {
                    "action_type": act_type,
                    "cases": 0,
                    "attempts": 0,
                    "successes": 0,
                    "failures": 0,
                    "recovered_amount": 0,
                    "estimated_incremental_value": 0,
                }
            action_stats[act_type]["cases"] += 1
            action_stats[act_type]["attempts"] += len(act.attempts) if act.attempts else 1
            if act.status == ActionStatus.SUCCEEDED:
                action_stats[act_type]["successes"] += 1
            elif act.status == ActionStatus.FAILED:
                action_stats[act_type]["failures"] += 1

            # Match outcome & measurement
            outcome = outcomes_by_case.get(act.case_id)
            if outcome and outcome.outcome_status in (RecoveryOutcomeStatus.RECOVERED, RecoveryOutcomeStatus.PARTIALLY_RECOVERED):
                action_stats[act_type]["recovered_amount"] += outcome.recovered_amount

        # Compute failure rate
        action_performance_list = []
        for a_type, stats in action_stats.items():
            total = stats["successes"] + stats["failures"]
            stats["failure_rate_pct"] = round((stats["failures"] / total * 100.0), 1) if total > 0 else 0.0
            action_performance_list.append(stats)

        # 6. Recent cases formatted
        recent_cases = []
        for c in cases[:15]:
            outcome = outcomes_by_case.get(c.id)
            recent_cases.append({
                "case_id": str(c.id),
                "domain": c.domain.value if hasattr(c.domain, "value") else str(c.domain),
                "case_type": c.case_type.value if hasattr(c.case_type, "value") else str(c.case_type),
                "status": c.status.value if hasattr(c.status, "value") else str(c.status),
                "amount_minor": c.amount or 0,
                "outcome_status": outcome.outcome_status.value if outcome else "PENDING",
                "recovered_amount_minor": outcome.recovered_amount if outcome else 0,
                "recovery_source": outcome.recovery_source.value if outcome else "UNKNOWN",
                "created_at": c.created_at.isoformat() if c.created_at else None,
            })

        return {
            "tenant_id": str(tenant.id),
            "kpis": {
                "revenue_at_risk": revenue_at_risk,
                "eligible_recovery": eligible_amount,
                "attempted_recovery": actioned_amount,
                "recovered_revenue": recovered_revenue,
                "estimated_incremental_recovery": incremental_estimate,
                "observed_treatment_recovery": observed_treatment,
                "observed_control_recovery": observed_control,
                "recovery_rate_pct": recovery_rate_pct,
                "is_estimate": True,
                "label": "ESTIMATE",
            },
            "funnel": [
                {"stage": "Revenue At Risk", "amount": revenue_at_risk, "count": total_cases_count, "badge": "OBSERVED"},
                {"stage": "Eligible", "amount": eligible_amount, "count": eligible_count, "badge": "OBSERVED"},
                {"stage": "Actioned", "amount": actioned_amount, "count": actioned_count, "badge": "OBSERVED"},
                {"stage": "Recovered", "amount": recovered_revenue, "count": recovered_count, "badge": "OBSERVED"},
                {"stage": "Incremental Estimate", "amount": incremental_estimate, "count": len(measurements), "badge": "ESTIMATE"},
            ],
            "action_performance": action_performance_list,
            "recent_cases": recent_cases,
            "recent_activity": await ActivityService.get_recent_activity(session=session, tenant_id=tenant.id, limit=20),
        }

    @classmethod
    async def get_case_list(
        cls,
        session: AsyncSession,
        tenant: Tenant,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List recovery cases for tenant with filtering and pagination."""
        query = select(RecoveryCase).where(RecoveryCase.tenant_id == tenant.id)
        if status:
            try:
                c_status = CaseStatus(status)
                query = query.where(RecoveryCase.status == c_status)
            except ValueError:
                pass
        query = query.order_by(desc(RecoveryCase.created_at)).offset(offset).limit(limit)

        result = await session.execute(query)
        cases = list(result.scalars().all())

        case_ids = [c.id for c in cases]
        outcomes_by_case = {}
        if case_ids:
            outcomes_res = await session.execute(
                select(RecoveryOutcome).where(RecoveryOutcome.case_id.in_(case_ids))
            )
            for o in outcomes_res.scalars().all():
                outcomes_by_case[o.case_id] = o

        items = []
        for c in cases:
            outcome = outcomes_by_case.get(c.id)
            items.append({
                "case_id": str(c.id),
                "tenant_id": str(c.tenant_id),
                "domain": c.domain.value if hasattr(c.domain, "value") else str(c.domain),
                "case_type": c.case_type.value if hasattr(c.case_type, "value") else str(c.case_type),
                "status": c.status.value if hasattr(c.status, "value") else str(c.status),
                "amount_minor": c.amount or 0,
                "outcome_status": outcome.outcome_status.value if outcome else "PENDING",
                "recovered_amount_minor": outcome.recovered_amount if outcome else 0,
                "recovery_source": outcome.recovery_source.value if outcome else "UNKNOWN",
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            })
        return items

    @classmethod
    async def get_full_case_detail(
        cls, session: AsyncSession, tenant: Tenant, case_id: uuid.UUID
    ) -> Optional[Dict[str, Any]]:
        """
        Perform a single, efficient tenant-scoped backend aggregation for a case.
        Includes failure intelligence, decision proposal, policy gate status,
        execution attempts, recovery attribution, and chronological audit timeline.
        """
        # 1. Fetch case with tenant isolation
        case_res = await session.execute(
            select(RecoveryCase).where(
                RecoveryCase.id == case_id,
                RecoveryCase.tenant_id == tenant.id
            )
        )
        case = case_res.scalar_one_or_none()
        if not case:
            return None

        # 2. Fetch Classification
        class_res = await session.execute(
            select(RecoveryClassification).where(RecoveryClassification.case_id == case.id)
        )
        classification = class_res.scalar_one_or_none()

        # 3. Fetch Decision Record
        dec_res = await session.execute(
            select(DecisionRecord).where(DecisionRecord.case_id == case.id).order_by(desc(DecisionRecord.timestamp))
        )
        decision = dec_res.scalars().first()

        # 4. Fetch Action
        act_res = await session.execute(
            select(Action).where(Action.case_id == case.id).order_by(desc(Action.created_at))
        )
        action = act_res.scalars().first()

        # 5. Fetch Execution Attempts
        attempts = []
        if action:
            att_res = await session.execute(
                select(ExecutionAttempt).where(ExecutionAttempt.action_id == action.id).order_by(ExecutionAttempt.attempt_number)
            )
            attempts = list(att_res.scalars().all())

        # 6. Fetch Outcome
        out_res = await session.execute(
            select(RecoveryOutcome).where(RecoveryOutcome.case_id == case.id)
        )
        outcome = out_res.scalar_one_or_none()

        # 7. Fetch Measurement
        measurement = None
        if outcome:
            m_res = await session.execute(
                select(RecoveryMeasurement).where(RecoveryMeasurement.outcome_id == outcome.id)
            )
            measurement = m_res.scalar_one_or_none()

        # 8. Build structured, non-chain-of-thought decision explanation
        cat_name = classification.failure_category.value if classification else "TRANSIENT_TECHNICAL"
        rec_name = classification.recoverability.value if classification else "HIGH"
        act_name = decision.proposed_action.value if decision else (action.action_type.value if action else "RETRY_NOW")
        pol_status = decision.policy_status.value if decision else "APPROVED"
        rejection_reason = decision.rejection_reason if decision else None

        if pol_status == "APPROVED":
            structured_explanation = (
                f"Payment failure was classified as {cat_name} with {rec_name} recoverability. "
                f"{act_name} was proposed by ARIV intelligence and APPROVED by PolicyEngine "
                f"under active tenant safety bounds."
            )
        elif pol_status == "REJECTED":
            structured_explanation = (
                f"Payment failure was classified as {cat_name}. Proposed action {act_name} "
                f"was REJECTED by PolicyEngine: {rejection_reason}. System safely halted recovery."
            )
        else:
            structured_explanation = (
                f"Payment failure classified as {cat_name}. Action {act_name} "
                f"requires human approval per tenant policy constraints."
            )

        # 9. Assemble chronological audit timeline
        timeline = []
        if case.created_at:
            timeline.append({
                "stage": "CASE_CREATED",
                "timestamp": case.created_at.isoformat(),
                "status": "COMPLETED",
                "description": f"Payment failure registered. Amount at risk: ₹{case.amount / 100:.2f}."
            })
        if classification:
            timeline.append({
                "stage": "CLASSIFIED",
                "timestamp": classification.timestamp.isoformat() if classification.timestamp else case.created_at.isoformat(),
                "status": "COMPLETED",
                "description": f"Classified as {classification.failure_category.value} (Retryability: {classification.retryability.value}, Recoverability: {classification.recoverability.value})."
            })
        if decision:
            timeline.append({
                "stage": "AI_PROPOSAL",
                "timestamp": decision.timestamp.isoformat(),
                "status": "COMPLETED",
                "description": f"ARIV proposed action: {decision.proposed_action.value} (Confidence: {int((decision.ai_confidence or 0.85) * 100)}%)."
            })
            timeline.append({
                "stage": "POLICY_EVALUATION",
                "timestamp": decision.timestamp.isoformat(),
                "status": decision.policy_status.value,
                "description": f"PolicyEngine evaluated proposal: {decision.policy_status.value}. Autonomy: {decision.autonomy_level.value}."
            })
        if action:
            timeline.append({
                "stage": "ACTION_AUTHORIZED",
                "timestamp": action.created_at.isoformat(),
                "status": action.status.value,
                "description": f"Action {action.action_type.value} authorized and queued into transactional outbox."
            })
            for att in attempts:
                att_desc = f"Provider attempt #{att.attempt_number} ({att.status.value}). Request ID: {att.provider_request_id or 'N/A'}."
                if att.attempt_metadata and isinstance(att.attempt_metadata, dict) and att.attempt_metadata.get("short_url"):
                    att_desc += f" Payment link: {att.attempt_metadata.get('short_url')}."
                timeline.append({
                    "stage": f"EXECUTION_ATTEMPT_{att.attempt_number}",
                    "timestamp": att.started_at.isoformat(),
                    "status": att.status.value,
                    "description": att_desc,
                })
        persisted_context = dict(case.context or {})
        payment_link_url = persisted_context.get("payment_link_url")
        provider_res_id = persisted_context.get("payment_link_id")
        recovery_stage = persisted_context.get("recovery_stage")

        if attempts:
            for att in reversed(attempts):
                if not payment_link_url and att.attempt_metadata and isinstance(att.attempt_metadata, dict):
                    if att.attempt_metadata.get("short_url"):
                        payment_link_url = att.attempt_metadata.get("short_url")
                if not provider_res_id and att.provider_request_id:
                    provider_res_id = att.provider_request_id

        if not recovery_stage and payment_link_url and (not outcome or outcome.outcome_status != RecoveryOutcomeStatus.RECOVERED):
            recovery_stage = "WAITING_FOR_PAYMENT"

        if recovery_stage == "WAITING_FOR_PAYMENT" and (not outcome or outcome.outcome_status != RecoveryOutcomeStatus.RECOVERED):
            timeline.append({
                "stage": "WAITING_FOR_PAYMENT",
                "timestamp": attempts[-1].finished_at.isoformat() if (attempts and attempts[-1].finished_at) else (action.updated_at or action.created_at).isoformat() if action else case.created_at.isoformat(),
                "status": "WAITING_FOR_PAYMENT",
                "description": f"Payment Link active ({provider_res_id or 'Generated'}). Waiting for customer payment.",
            })

        if outcome:
            rec_ts = outcome.recovered_at or outcome.created_at
            timeline.append({
                "stage": "RECOVERY_OUTCOME",
                "timestamp": rec_ts.isoformat(),
                "status": outcome.outcome_status.value,
                "description": f"Outcome: {outcome.outcome_status.value}. Recovered: ₹{outcome.recovered_amount / 100:.2f}. Source: {outcome.recovery_source.value}."
            })
        if measurement:
            timeline.append({
                "stage": "MEASUREMENT_ATTRIBUTED",
                "timestamp": measurement.measurement_at.isoformat() if measurement.measurement_at else outcome.created_at.isoformat(),
                "status": "COMPLETED",
                "description": f"Measurement recorded. Incremental Recovery Estimate: ₹{measurement.incremental_recovery / 100:.2f} (ESTIMATE)."
            })

        # 10. Fetch similar cases from Qdrant memory (tenant-isolated!)
        similar_cases = []
        try:
            embed_text = f"domain:{case.domain} category:{cat_name} action:{act_name} outcome:{outcome.outcome_status.value if outcome else 'UNKNOWN'}"
            query_vec = EmbeddingService.embed_text(embed_text)
            raw_memories = await QdrantMemoryService.search_memories(
                tenant_id=str(tenant.id),
                query_vector=query_vec,
                limit=4,
            )
            for m in raw_memories:
                # Sanitize: never return secret or cross-tenant data
                similar_cases.append({
                    "measurement_id": m.get("measurement_id"),
                    "failure_category": m.get("failure_category", "UNKNOWN"),
                    "domain": m.get("domain", "B2C"),
                    "action_type": m.get("action_type", "NONE"),
                    "outcome_status": m.get("outcome_status", "UNKNOWN"),
                    "recovery_source": m.get("recovery_source", "UNKNOWN"),
                    "amount_bucket": m.get("amount_bucket", "medium"),
                    "time_to_recovery_bucket": m.get("time_to_recovery_bucket", "fast"),
                })
        except Exception as e:
            logger.warning("Qdrant similar cases lookup skipped: %s", e)

        # 11. Authoritative recent activities for this case
        activities = []
        try:
            activities = await ActivityService.get_recent_activity(session=session, tenant_id=tenant.id, case_id=case.id, limit=30)
        except Exception as e:
            logger.warning("Case activities lookup skipped: %s", e)

        # 12. Persisted economic ENR ranking (recorded at decision time by the
        # decision engine). Purely surfaced here — never recomputed or inferred.
        decision_prov = dict(decision.provenance or {}) if decision else {}
        economic_prov = decision_prov.get("economic") or {}
        policy_prov = decision_prov.get("policy") or {}
        ranked_candidates = list(economic_prov.get("ranked_candidates") or [])
        selected_enr = economic_prov.get("selected_enr")
        selected_probability = economic_prov.get("selected_probability")
        selected_provenance = list(economic_prov.get("selected_provenance") or [])
        policy_evaluations = list(policy_prov.get("evaluated_candidates") or [])
        economic_available = bool(ranked_candidates)

        return {
            "case": {
                "id": str(case.id),
                "tenant_id": str(case.tenant_id),
                "domain": case.domain.value if hasattr(case.domain, "value") else str(case.domain),
                "case_type": case.case_type.value if hasattr(case.case_type, "value") else str(case.case_type),
                "status": case.status.value if hasattr(case.status, "value") else str(case.status),
                "amount_minor": case.amount or 0,
                "created_at": case.created_at.isoformat() if case.created_at else None,
                "updated_at": case.updated_at.isoformat() if case.updated_at else None,
                "context": persisted_context,
                "recovery_stage": recovery_stage,
            },
            "classification": {
                "failure_category": cat_name,
                "retryability": classification.retryability.value if classification else "LATER_RETRY_POSSIBLE",
                "recoverability": rec_name,
                "taxonomy_version": classification.taxonomy_version if classification else "1.0",
                "explanation": f"Classified as {cat_name} based on gateway failure signals.",
            },
            "decision": {
                "proposed_action": act_name,
                "baseline_action": decision.baseline_action.value if decision else "RETRY_NOW",
                "ai_confidence": decision.ai_confidence if decision else 0.88,
                "policy_status": pol_status,
                "autonomy_level": decision.autonomy_level.value if decision else "FULL_AUTO",
                "rejection_reason": rejection_reason,
                "structured_explanation": structured_explanation,
                "policy_version": "v1.0.0-safety",
            },
            "economic": {
                "available": economic_available,
                "method": economic_prov.get("ranking_method") or "ENR",
                "ranked_candidates": ranked_candidates,
                "selected_enr": selected_enr,
                "selected_probability": selected_probability,
                "selected_provenance": selected_provenance,
                "policy_evaluations": policy_evaluations,
                "expected_irv": decision.expected_irv if decision else None,
            },
            "execution": {
                "action_type": act_name,
                "status": action.status.value if action else "NONE",
                "provider": "razorpay_sandbox",
                "provider_request_id": provider_res_id or (attempts[0].provider_request_id if attempts else None),
                "provider_resource_id": provider_res_id,
                "provider_reference": provider_res_id,
                "payment_link_url": payment_link_url,
                "recovery_stage": recovery_stage,
                "attempt_count": len(attempts),
                "is_unknown": (attempts[-1].status == ExecutionStatus.UNKNOWN) if attempts else False,
            },
            "recovery": {
                "outcome_status": outcome.outcome_status.value if outcome else "PENDING",
                "recovered_amount_minor": outcome.recovered_amount if outcome else 0,
                "recovery_source": outcome.recovery_source.value if outcome else "UNKNOWN",
                "attribution_source": outcome.recovery_source.value if outcome else "UNKNOWN",
                "attribution_decision": outcome.attribution_decision if outcome else "Pending evaluation",
                "attribution_window_seconds": outcome.attribution_provenance.get("attribution_window_seconds", 86400) if (outcome and outcome.attribution_provenance) else 86400,
                "recovered_at": outcome.recovered_at.isoformat() if (outcome and outcome.recovered_at) else None,
                "provider_reference": provider_res_id,
            },
            "measurement": {
                "treatment_recovery_minor": measurement.treatment_recovery if measurement else 0,
                "control_recovery_minor": measurement.control_recovery if measurement else 0,
                "estimated_control_recovery_minor": measurement.estimated_control_recovery if measurement else 0,
                "incremental_recovery_minor": measurement.incremental_recovery if measurement else 0,
                "baseline_method": "deterministic_heuristic",
                "is_counterfactual_estimate": True,
                "label": "ESTIMATE",
            } if measurement else None,
            "timeline": timeline,
            "similar_cases": similar_cases,
            "activities": activities,
        }

    @classmethod
    async def get_similar_cases(
        cls, session: AsyncSession, tenant: Tenant, case_id: uuid.UUID
    ) -> List[Dict[str, Any]]:
        """Retrieve similar past recovery cases for this case, strictly tenant-isolated."""
        detail = await cls.get_full_case_detail(session, tenant, case_id)
        if not detail:
            return []
        return detail.get("similar_cases", [])

    @classmethod
    async def seed_demo_cases(cls, session: AsyncSession, tenant: Tenant) -> Dict[str, Any]:

        """
        Seed 4 deterministic sandbox demo cases.

        Security:
        - Only available when settings.DEMO_MODE is True.
        - HMAC-authenticated & tenant-scoped.
        - Idempotent: checks for existing demo cases; returns existing records without duplication.
        - Clearly tagged with context={"is_demo": True}.
        """
        if not settings.DEMO_MODE:
            raise PermissionError("Demo mode is disabled on this environment.")

        # Idempotency check: check if demo cases already exist for this tenant
        existing_res = await session.execute(
            select(RecoveryCase).where(
                RecoveryCase.tenant_id == tenant.id,
                cast(RecoveryCase.context["is_demo"], String) == "true"
            )
        )
        existing = list(existing_res.scalars().all())
        if existing:
            logger.info("Demo cases already seeded for tenant %s (count=%d)", tenant.id, len(existing))
            return {
                "status": "already_seeded",
                "seeded_count": len(existing),
                "case_ids": [str(c.id) for c in existing],
                "message": "Demo cases already exist for this tenant.",
            }

        now = datetime.now(timezone.utc)
        seeded_ids = []

        # -------------------------------------------------------------------
        # Scenario 1: Successful Payment Link (Action Attributed)
        # -------------------------------------------------------------------
        c1 = RecoveryCase(
            tenant_id=tenant.id,
            domain=RecoveryDomain.B2C,
            case_type=CaseType.PAYMENT_FAILED,
            status=CaseStatus.RECOVERED,
            amount_minor=15000,  # ₹150.00
            context={"is_demo": True, "scenario": "CUSTOMER_PAYMENT_LINK_SUCCESS", "currency": "INR"},
            created_at=now - timedelta(hours=2),
        )
        session.add(c1)
        await session.flush()
        seeded_ids.append(str(c1.id))

        cl1 = RecoveryClassification(
            case_id=c1.id,
            failure_category=FailureCategory.CUSTOMER_ACTION_REQUIRED,
            retryability=Retryability.REQUIRES_NEW_METHOD,
            recoverability=Recoverability.HIGH,
            timestamp=now - timedelta(hours=2, minutes=1),
        )
        session.add(cl1)

        d1 = DecisionRecord(
            case_id=c1.id,
            tenant_id=tenant.id,
            proposed_action=RecoveryAction.GENERATE_PAYMENT_LINK,
            baseline_action=RecoveryAction.GENERATE_PAYMENT_LINK,
            ai_confidence=0.92,
            policy_status=PolicyStatus.APPROVED,
            autonomy_level=AutonomyLevel.FULL_AUTO,
            timestamp=now - timedelta(hours=1, minutes=58),
        )
        session.add(d1)
        await session.flush()

        a1 = Action(
            case_id=c1.id,
            tenant_id=tenant.id,
            decision_id=d1.id,
            action_type=RecoveryAction.GENERATE_PAYMENT_LINK,
            status=ActionStatus.SUCCEEDED,
            created_at=now - timedelta(hours=1, minutes=55),
        )
        session.add(a1)
        await session.flush()

        att1 = ExecutionAttempt(
            action_id=a1.id,
            attempt_number=1,
            status=ExecutionStatus.SUCCEEDED,
            provider_request_id="plink_demo_sandbox_001",
            started_at=now - timedelta(hours=1, minutes=50),
            finished_at=now - timedelta(hours=1, minutes=49),
        )
        session.add(att1)

        prov1 = ProviderExecutionResult(
            status=ProviderOutcomeStatus.SUCCEEDED,
            provider="razorpay",
            provider_resource_id="plink_demo_sandbox_001",
            retry_safety=RetrySafety.SAFE_TO_RETRY,
            raw_metadata={"amount": 15000},
        )
        rec_time1 = now - timedelta(hours=1)
        o1 = await RecoveryService.record_outcome(
            session=session,
            case=c1,
            tenant=tenant,
            action=a1,
            provider_result=prov1,
            recovered_at_override=rec_time1,
        )

        context1 = _make_decision_context(c1, tenant, cl1)

        await RecoveryService.create_measurement(
            session=session,
            outcome=o1,
            context=context1,
            action=a1,
            cost_of_recovery=20,
        )

        # -------------------------------------------------------------------
        # Scenario 2: Terminal Non-Retriable (Policy Engine Rejection)
        # -------------------------------------------------------------------
        c2 = RecoveryCase(
            tenant_id=tenant.id,
            domain=RecoveryDomain.B2C,
            case_type=CaseType.PAYMENT_FAILED,
            status=CaseStatus.FAILED,
            amount_minor=25000,  # ₹250.00
            context={"is_demo": True, "scenario": "TERMINAL_NON_RETRIABLE_REJECTED", "currency": "INR"},
            created_at=now - timedelta(hours=3),
        )
        session.add(c2)
        await session.flush()
        seeded_ids.append(str(c2.id))

        cl2 = RecoveryClassification(
            case_id=c2.id,
            failure_category=FailureCategory.NON_RETRIABLE,
            retryability=Retryability.BLOCKED,
            recoverability=Recoverability.LOW,
            timestamp=now - timedelta(hours=2, minutes=59),
        )
        session.add(cl2)

        d2 = DecisionRecord(
            case_id=c2.id,
            tenant_id=tenant.id,
            proposed_action=RecoveryAction.RETRY_NOW,
            baseline_action=RecoveryAction.STOP_RECOVERY,
            ai_confidence=0.45,
            policy_status=PolicyStatus.REJECTED,
            autonomy_level=AutonomyLevel.SUGGESTION_ONLY,
            rejection_reason="Cannot retry non-retriable failure.",
            timestamp=now - timedelta(hours=2, minutes=58),
        )
        session.add(d2)

        prov2 = ProviderExecutionResult(
            status=ProviderOutcomeStatus.FAILED,
            provider="razorpay",
            retry_safety=RetrySafety.NOT_RETRIABLE,
            error_code="PAYMENT_DECLINED",
        )
        await RecoveryService.record_outcome(
            session=session,
            case=c2,
            tenant=tenant,
            action=None,
            provider_result=prov2,
        )

        # -------------------------------------------------------------------
        # Scenario 3: Provider Degradation & Reconciliation Case
        # -------------------------------------------------------------------
        c3 = RecoveryCase(
            tenant_id=tenant.id,
            domain=RecoveryDomain.B2C,
            case_type=CaseType.PAYMENT_FAILED,
            status=CaseStatus.RECOVERED,
            amount_minor=12000,  # ₹120.00
            context={"is_demo": True, "scenario": "PROVIDER_TIMEOUT_RECONCILED", "currency": "INR"},
            created_at=now - timedelta(hours=4),
        )
        session.add(c3)
        await session.flush()
        seeded_ids.append(str(c3.id))

        cl3 = RecoveryClassification(
            case_id=c3.id,
            failure_category=FailureCategory.PROVIDER_DEGRADATION,
            retryability=Retryability.LATER_RETRY_POSSIBLE,
            recoverability=Recoverability.MEDIUM,
            timestamp=now - timedelta(hours=3, minutes=59),
        )
        session.add(cl3)

        d3 = DecisionRecord(
            case_id=c3.id,
            tenant_id=tenant.id,
            proposed_action=RecoveryAction.RETRY_LATER,
            baseline_action=RecoveryAction.RETRY_LATER,
            ai_confidence=0.88,
            policy_status=PolicyStatus.APPROVED,
            autonomy_level=AutonomyLevel.FULL_AUTO,
            timestamp=now - timedelta(hours=3, minutes=57),
        )
        session.add(d3)
        await session.flush()

        a3 = Action(
            case_id=c3.id,
            tenant_id=tenant.id,
            decision_id=d3.id,
            action_type=RecoveryAction.RETRY_LATER,
            status=ActionStatus.SUCCEEDED,
            created_at=now - timedelta(hours=3, minutes=50),
        )
        session.add(a3)
        await session.flush()

        # First attempt timed out (UNKNOWN)
        att3a = ExecutionAttempt(
            action_id=a3.id,
            attempt_number=1,
            status=ExecutionStatus.UNKNOWN,
            provider_request_id="pay_degrade_003_to",
            started_at=now - timedelta(hours=3, minutes=45),
            finished_at=now - timedelta(hours=3, minutes=44),
        )
        session.add(att3a)

        # Reconciliation succeeded
        att3b = ExecutionAttempt(
            action_id=a3.id,
            attempt_number=2,
            status=ExecutionStatus.SUCCEEDED,
            provider_request_id="pay_degrade_003_reconciled",
            started_at=now - timedelta(hours=3, minutes=10),
            finished_at=now - timedelta(hours=3, minutes=9),
        )
        session.add(att3b)

        prov3 = ProviderExecutionResult(
            status=ProviderOutcomeStatus.SUCCEEDED,
            provider="razorpay",
            provider_resource_id="pay_degrade_003_reconciled",
            retry_safety=RetrySafety.SAFE_TO_RETRY,
            raw_metadata={"amount": 12000},
        )
        o3 = await RecoveryService.record_outcome(
            session=session,
            case=c3,
            tenant=tenant,
            action=a3,
            provider_result=prov3,
            recovered_at_override=now - timedelta(hours=3, minutes=5),
        )
        context3 = _make_decision_context(c3, tenant, cl3)
        await RecoveryService.create_measurement(
            session=session,
            outcome=o3,
            context=context3,
            action=a3,
            cost_of_recovery=15,
        )

        # -------------------------------------------------------------------
        # Scenario 4: Organic Recovery (Customer paid before action was taken)
        # -------------------------------------------------------------------
        c4 = RecoveryCase(
            tenant_id=tenant.id,
            domain=RecoveryDomain.B2B,
            case_type=CaseType.INVOICE_OVERDUE,
            status=CaseStatus.RECOVERED,
            amount_minor=50000,  # ₹500.00
            context={"is_demo": True, "scenario": "ORGANIC_RECOVERY_BEFORE_ACTION", "currency": "INR"},
            created_at=now - timedelta(hours=5),
        )
        session.add(c4)
        await session.flush()
        seeded_ids.append(str(c4.id))

        cl4 = RecoveryClassification(
            case_id=c4.id,
            failure_category=FailureCategory.TRANSIENT_TECHNICAL,
            retryability=Retryability.IMMEDIATE_RETRY_POSSIBLE,
            recoverability=Recoverability.HIGH,
            timestamp=now - timedelta(hours=4, minutes=58),
        )
        session.add(cl4)

        prov4 = ProviderExecutionResult(
            status=ProviderOutcomeStatus.SUCCEEDED,
            provider="razorpay",
            provider_resource_id="inv_organic_004",
            retry_safety=RetrySafety.SAFE_TO_RETRY,
            raw_metadata={"amount": 50000},
        )
        # Customer paid without automated recovery action
        o4 = await RecoveryService.record_outcome(
            session=session,
            case=c4,
            tenant=tenant,
            action=None,
            provider_result=prov4,
            recovered_at_override=now - timedelta(hours=4, minutes=30),
        )
        context4 = _make_decision_context(c4, tenant, cl4)

        await RecoveryService.create_measurement(
            session=session,
            outcome=o4,
            context=context4,
            action=None,
        )
        await session.commit()
        logger.info("Successfully seeded 4 demo scenarios for tenant %s", tenant.id)
        return {
            "status": "seeded",
            "seeded_count": len(seeded_ids),
            "case_ids": seeded_ids,
            "message": "Successfully seeded 4 deterministic sandbox demo scenarios.",
        }
