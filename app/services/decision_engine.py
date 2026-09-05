"""
app/services/decision_engine.py

Decision Engine Service for ARIV.
Executes the full Intelligence -> Memory -> Policy -> Governed Execution pipeline.
"""

import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.recovery_case import RecoveryCase, CaseStatus
from app.domain.classification import RecoveryClassification
from app.domain.decision import DecisionRecord, PolicyStatus, AutonomyLevel
from app.domain.schemas import DecisionContext, DecisionProposal
from app.services.baseline import DeterministicBaseline
from app.services.agent import AgentRuntime
from app.services.policy import PolicyEngine
from app.interfaces.knowledge import TenantAwareKnowledgeRetriever
from app.domain.state_machine import CaseStateMachine
from app.services.activity import ActivityService, OperationalEventType
from app.services.outbox import OutboxService
from app.services.execution_worker import ExecutionWorker
from app.infrastructure.adapters import get_razorpay_adapter
from app.services.telegram import TelegramNotifier

logger = logging.getLogger("ariv.services.decision")


class DecisionEngineService:

    @classmethod
    async def execute_decision_cycle(
        cls,
        session: AsyncSession,
        case: RecoveryCase,
        classification: RecoveryClassification,
        raw_payload: Optional[dict] = None,
    ):
        """
        Executes the full Intelligence -> Policy -> Persistence -> Governed Outbox pipeline.
        """
        logger.info(f"Starting Decision Engine for Case {case.id}")

        # 1. Deterministic Baseline
        baseline_action = DeterministicBaseline.decide(
            domain=case.domain,
            category=classification.failure_category,
            retryability=classification.retryability,
        )

        # 2. Qdrant Context Assembly (Tenant Isolated)
        retriever = TenantAwareKnowledgeRetriever(tenant_id=str(case.tenant_id))
        historical_cases = []
        try:
            from app.core.config import settings
            query_vector = [0.0] * settings.EMBEDDING_DIMENSION
            historical_cases = await retriever.search_historical_cases(query_vector)
            await ActivityService.record_event(
                session=session,
                event_type=OperationalEventType.MEMORY_RETRIEVED,
                message=f"🔎 Recovery Memory: Found {len(historical_cases)} similar historical cases",
                case_id=case.id,
                tenant_id=case.tenant_id,
                details={"matches_count": len(historical_cases)},
            )
        except Exception as e:
            logger.warning("Recovery memory lookup failed (non-fatal): %s", e)

        # 3. Decision Context Assembly
        amount_major = float(case.amount_minor or 0) / 100.0
        context = DecisionContext(
            case_id=str(case.id),
            tenant_id=str(case.tenant_id),
            domain=case.domain,
            amount=amount_major,
            currency="INR",
            failure_category=classification.failure_category,
            retryability=classification.retryability,
            recoverability=classification.recoverability,
            time_since_failure_seconds=0,
            intervention_count=0,
            baseline_action=baseline_action,
            historical_cases=historical_cases,
        )

        await ActivityService.record_event(
            session=session,
            event_type=OperationalEventType.RECOVERY_CONTEXT_BUILT,
            message="🧩 Recovery context assembled (Payment + Failure + Tenant Memory)",
            case_id=case.id,
            tenant_id=case.tenant_id,
        )

        # 4. Agentic Intelligence (Proposal)
        proposal: DecisionProposal = await AgentRuntime.propose_decision(context)

        await ActivityService.record_event(
            session=session,
            event_type=OperationalEventType.DECISION_CREATED,
            message=f"🤖 ARIV Decision: {proposal.recommended_action.value} (Confidence: {proposal.confidence*100:.0f}%, Expected: ₹{proposal.expected_irv:.2f})",
            case_id=case.id,
            tenant_id=case.tenant_id,
            details={
                "action": proposal.recommended_action.value,
                "confidence": proposal.confidence,
                "expected_irv": proposal.expected_irv,
                "reason": proposal.reason,
            },
        )

        # 5. Policy Gate (Safety Firewall)
        policy_status, autonomy_level, rejection_reason = PolicyEngine.evaluate(
            proposal=proposal,
            domain=case.domain,
            category=classification.failure_category,
        )

        # If rejected, override action to Baseline or safe stop
        final_action = proposal.recommended_action
        if policy_status == PolicyStatus.REJECTED:
            logger.warning(f"AI Proposal {final_action.value} REJECTED. Reverting to baseline {baseline_action.value}")
            final_action = baseline_action

        # 6. Record Decision Record
        decision_record = DecisionRecord(
            case_id=case.id,
            tenant_id=case.tenant_id,
            proposed_action=final_action,
            baseline_action=baseline_action,
            ai_confidence=proposal.confidence,
            expected_irv=proposal.expected_irv,
            policy_status=policy_status,
            autonomy_level=autonomy_level,
            rejection_reason=rejection_reason,
            provenance={
                "knowledge_refs": proposal.knowledge_refs,
                "llm_reason": proposal.reason,
                "original_ai_action": proposal.recommended_action.value if policy_status == PolicyStatus.REJECTED else None,
            },
        )
        session.add(decision_record)
        await session.flush()

        # 7. Policy Outcome Handling & Governed Execution
        if policy_status == PolicyStatus.REJECTED:
            await ActivityService.record_event(
                session=session,
                event_type=OperationalEventType.POLICY_BLOCKED,
                message=f"🚫 Policy Firewall BLOCKED {proposal.recommended_action.value}: {rejection_reason}",
                case_id=case.id,
                tenant_id=case.tenant_id,
                details={"rejection_reason": rejection_reason, "baseline": baseline_action.value},
            )
            try:
                await TelegramNotifier.notify_policy_blocked(case=case, action=None, reason=rejection_reason)
            except Exception as e:
                logger.warning("Telegram notification failed (non-fatal): %s", e)

        elif policy_status == PolicyStatus.NEEDS_REVIEW or autonomy_level == AutonomyLevel.HUMAN_APPROVAL:
            CaseStateMachine.transition_to(case, CaseStatus.PENDING_APPROVAL)
            await ActivityService.record_event(
                session=session,
                event_type=OperationalEventType.POLICY_APPROVED,
                message=f"🛡️ Policy evaluated: Human approval required before dispatching {final_action.value}",
                case_id=case.id,
                tenant_id=case.tenant_id,
                details={"autonomy": "HUMAN_APPROVAL"},
            )

        elif policy_status == PolicyStatus.APPROVED:
            await ActivityService.record_event(
                session=session,
                event_type=OperationalEventType.POLICY_APPROVED,
                message=f"🛡️ Policy Firewall APPROVED {final_action.value} (Autonomy: {autonomy_level.value})",
                case_id=case.id,
                tenant_id=case.tenant_id,
                details={"autonomy": autonomy_level.value},
            )

            # FULL_AUTO execution path via Outbox & ExecutionWorker
            if autonomy_level == AutonomyLevel.FULL_AUTO:
                outbox_payload = {
                    "amount": case.amount_minor or 10000,
                    "currency": case.context.get("currency", "INR") if case.context else "INR",
                    "description": f"ARIV Autonomous Recovery - Case {str(case.id)[:8]}",
                    "customer_email": case.context.get("customer_email") if case.context else None,
                    "customer_phone": case.context.get("customer_phone") if case.context else None,
                    "customer_name": case.context.get("customer_name") if case.context else None,
                }

                action, outbox = await OutboxService.create_authorized_action(
                    session=session,
                    case_id=case.id,
                    tenant_id=case.tenant_id,
                    decision_id=decision_record.id,
                    action_type=final_action,
                    payload=outbox_payload,
                )

                await ActivityService.record_event(
                    session=session,
                    event_type=OperationalEventType.ACTION_AUTHORIZED,
                    message=f"🔒 Recovery action {final_action.value} authorized and queued in Execution Outbox",
                    case_id=case.id,
                    action_id=action.id,
                    tenant_id=case.tenant_id,
                )

                # Attempt immediate governed execution via ExecutionWorker
                adapter = get_razorpay_adapter()
                if adapter:
                    try:
                        worker = ExecutionWorker(provider_adapter=adapter)
                        await worker.process_outbox_item(session, outbox)
                    except Exception as e:
                        logger.error("Outbox item execution failed: %s", e)

        await session.flush()
        logger.info(f"Decision Engine completed for Case {case.id}. Status: {case.status.value}")
