"""
app/services/decision_engine.py

Decision Engine Service for ARIV.
Executes the full Intelligence -> Memory -> Economic Optimization -> Policy -> Governed Execution pipeline.
"""

import logging
import hashlib
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.recovery_case import RecoveryCase, CaseStatus
from app.domain.classification import RecoveryClassification
from app.domain.decision import DecisionRecord, PolicyStatus, AutonomyLevel, RecoveryAction
from app.domain.schemas import DecisionContext, DecisionProposal
from app.services.baseline import DeterministicBaseline
from app.services.economic_optimizer import EconomicOptimizer
from app.services.agent import AgentRuntime
from app.services.policy import PolicyEngine
from app.interfaces.knowledge import TenantAwareKnowledgeRetriever
from app.services.embedding import EmbeddingService
from app.services.candidate_generator import CandidateGenerator
from app.services.probability_provider import ProbabilityProvider
from app.services.systemic_intelligence import SystemicIntelligenceService
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
        Executes the full Intelligence -> Memory -> Economic Optimization -> Policy -> Governed Execution pipeline.
        """
        logger.info(f"Starting Decision Engine for Case {case.id}")

        # 1. Deterministic Baseline
        baseline_action = DeterministicBaseline.decide(
            domain=case.domain,
            category=classification.failure_category,
            retryability=classification.retryability,
        )
        amount_major = float(case.amount_minor or 0) / 100.0

        # 2. Systemic Payment Corridor & Route Health Intelligence
        corridor = SystemicIntelligenceService.detect_corridor(case)
        SystemicIntelligenceService.record_signal(
            corridor=corridor,
            tenant_id=str(case.tenant_id),
            is_failure=True,
            category=classification.failure_category.value if classification.failure_category else "UNKNOWN",
            amount=amount_major,
        )
        route_health = SystemicIntelligenceService.analyze_route_health(
            corridor=corridor,
            tenant_id=str(case.tenant_id),
        )

        # 3. Context-Dependent Qdrant Retrieval (Tenant Isolated, No Zero-Vectors)
        retriever = TenantAwareKnowledgeRetriever(tenant_id=str(case.tenant_id))
        historical_cases = []
        canonical_context = (
            f"domain:{case.domain.value if hasattr(case.domain, 'value') else case.domain} "
            f"category:{classification.failure_category.value if classification.failure_category else 'none'} "
            f"retryability:{classification.retryability.value if classification.retryability else 'none'} "
            f"amount:{amount_major:.2f} "
            f"baseline:{baseline_action.value if hasattr(baseline_action, 'value') else baseline_action} "
            f"route:{corridor}"
        )
        query_vector = EmbeddingService.embed_text(canonical_context)

        try:
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

        # 4. Decision Context Assembly (Injects Qdrant Evidence & Route Health into AI Context)
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
            route_health=route_health,
        )

        await ActivityService.record_event(
            session=session,
            event_type=OperationalEventType.RECOVERY_CONTEXT_BUILT,
            message=f"🧩 Recovery context assembled (Payment + Corridor {route_health.get('status')} + Tenant Memory)",
            case_id=case.id,
            tenant_id=case.tenant_id,
        )

        # 5. Agentic Intelligence (Proposal with Diagnosis & Candidate Actions)
        proposal: DecisionProposal
        proposal, ai_stripped = await AgentRuntime._propose_decision_with_audit(context)

        await ActivityService.record_event(
            session=session,
            event_type=OperationalEventType.DECISION_CREATED,
            message=f"🤖 ARIV AI Proposal: {proposal.recommended_action.value} (Confidence: {proposal.confidence*100:.0f}%)",
            case_id=case.id,
            tenant_id=case.tenant_id,
            details={
                "recommended_action": proposal.recommended_action.value,
                "candidate_actions": [a.value for a in proposal.candidate_actions],
                "confidence": proposal.confidence,
                "reason": proposal.reason,
            },
        )

        # 5. Candidate Generation (AI actions + Baseline + Business Eligibility, max 5)
        candidates = CandidateGenerator.generate_candidates(context=context, ai_proposal=proposal)

        # 6. Economic Optimization & Multi-Candidate ENR Ranking
        # Order-neutral tie-break: the AI cannot steer which candidate wins an ENR
        # tie through recommendation/insertion order.
        ranked_candidates = EconomicOptimizer.rank_candidates(
            candidates=candidates,
            context=context,
            probability_provider=ProbabilityProvider,
        )

        # 7. Policy Gate Iteration over Ranked Candidates
        # DecisionEngine iterates ranked candidates; PolicyEngine evaluates safety boundary.
        selected_candidate = None
        selected_policy_status = PolicyStatus.REJECTED
        selected_autonomy_level = AutonomyLevel.SUGGESTION_ONLY
        selected_rejection_reason = "No candidate approved by policy"
        evaluated_policy_records = []

        for cand in ranked_candidates:
            cand_action = cand["action"]
            eval_proposal = DecisionProposal(
                recommended_action=cand_action,
                candidate_actions=[cand_action],
                reason=proposal.reason,
                confidence=proposal.confidence,
                expected_irv=cand["expected_net_recovery"],
                knowledge_refs=proposal.knowledge_refs,
            )

            p_status, p_autonomy, p_reason = PolicyEngine.evaluate(
                proposal=eval_proposal,
                domain=case.domain,
                category=classification.failure_category,
                route_health=route_health,
            )

            evaluated_policy_records.append({
                "action": cand_action.value if hasattr(cand_action, "value") else str(cand_action),
                "expected_net_recovery": cand["expected_net_recovery"],
                "recovery_probability": cand["recovery_probability"],
                "policy_status": p_status.value if hasattr(p_status, "value") else str(p_status),
                "autonomy_level": p_autonomy.value if hasattr(p_autonomy, "value") else str(p_autonomy),
                "rejection_reason": p_reason,
            })

            if p_status in (PolicyStatus.APPROVED, PolicyStatus.NEEDS_REVIEW):
                selected_candidate = cand
                selected_policy_status = p_status
                selected_autonomy_level = p_autonomy
                selected_rejection_reason = p_reason
                break

        # If all candidates rejected, fall back safely to STOP_RECOVERY
        if not selected_candidate:
            logger.warning("All candidates rejected by PolicyEngine. Falling back safely to STOP_RECOVERY.")
            stop_prob, stop_prov = ProbabilityProvider.estimate(RecoveryAction.STOP_RECOVERY, context)
            stop_enr = EconomicOptimizer.compute_expected_net_recovery(
                probability=stop_prob,
                recoverable_amount=context.amount,
                operational_cost=0.0,
                risk_penalty=0.0,
            )
            selected_candidate = {
                "action": RecoveryAction.STOP_RECOVERY,
                "recovery_probability": stop_prob,
                "probability_provenance": stop_prov,
                "recoverable_amount": context.amount,
                "operational_cost": 0.0,
                "risk_penalty": 0.0,
                "expected_net_recovery": stop_enr,
            }
            selected_policy_status = PolicyStatus.APPROVED
            selected_autonomy_level = AutonomyLevel.FULL_AUTO
            selected_rejection_reason = "All candidates rejected by policy; stopped recovery safely."

        final_action: RecoveryAction = selected_candidate["action"]

        # 8. Authoritative Provenance Construction (AI, Qdrant, Economic, Policy, Systemic)
        provenance = {
            "ai": {
                "diagnosis": proposal.diagnosis,
                "recommended_action": proposal.recommended_action.value if proposal.recommended_action else None,
                "candidate_actions": [a.value if hasattr(a, "value") else str(a) for a in proposal.candidate_actions],
                "confidence": proposal.confidence,
                "reason": proposal.reason,
                "knowledge_refs": proposal.knowledge_refs,
                "authority_boundary": {
                    "advisory_only": True,
                    "financial_authority_fields_stripped": ai_stripped.get("financial", []) if isinstance(ai_stripped, dict) else [],
                    "non_advisory_fields_stripped": ai_stripped.get("all", []) if isinstance(ai_stripped, dict) else [],
                },
            },
            "qdrant": {
                "query_vector_dimension": len(query_vector),
                "matches_count": len(historical_cases),
                "canonical_context_hash": hashlib.sha256(canonical_context.encode("utf-8")).hexdigest()[:16],
                "embedding_provenance": EmbeddingService.get_provenance(),
            },
            "economic": {
                "ranked_candidates": [
                    {
                        "action": c["action"].value if hasattr(c["action"], "value") else str(c["action"]),
                        "recovery_probability": c["recovery_probability"],
                        "probability_provenance": c["probability_provenance"],
                        "recoverable_amount": c["recoverable_amount"],
                        "operational_cost": c["operational_cost"],
                        "risk_penalty": c["risk_penalty"],
                        "expected_net_recovery": c["expected_net_recovery"],
                    }
                    for c in ranked_candidates
                ],
                "selected_enr": selected_candidate["expected_net_recovery"],
                "selected_probability": selected_candidate["recovery_probability"],
                "selected_provenance": selected_candidate["probability_provenance"],
            },
            "policy": {
                "evaluated_candidates": evaluated_policy_records,
                "final_status": selected_policy_status.value if hasattr(selected_policy_status, "value") else str(selected_policy_status),
                "final_autonomy": selected_autonomy_level.value if hasattr(selected_autonomy_level, "value") else str(selected_autonomy_level),
                "rejection_reason": selected_rejection_reason,
            },
            "systemic": {
                "corridor": route_health.get("corridor"),
                "status": route_health.get("status"),
                "degradation_score": route_health.get("degradation_score"),
                "failure_rate": route_health.get("failure_rate"),
                "sample_count": route_health.get("sample_count"),
                "recommended_mitigation": route_health.get("recommended_mitigation"),
            },
        }

        # 9. Record Authoritative DecisionRecord
        decision_record = DecisionRecord(
            case_id=case.id,
            tenant_id=case.tenant_id,
            proposed_action=final_action,
            baseline_action=baseline_action,
            ai_confidence=proposal.confidence,
            expected_irv=selected_candidate["expected_net_recovery"],
            policy_status=selected_policy_status,
            autonomy_level=selected_autonomy_level,
            rejection_reason=selected_rejection_reason,
            provenance=provenance,
        )
        session.add(decision_record)
        await session.flush()

        # 10. Policy Outcome Handling & Governed Execution
        if selected_policy_status == PolicyStatus.REJECTED:
            await ActivityService.record_event(
                session=session,
                event_type=OperationalEventType.POLICY_BLOCKED,
                message=f"🚫 Policy Firewall BLOCKED {final_action.value}: {selected_rejection_reason}",
                case_id=case.id,
                tenant_id=case.tenant_id,
                details={"rejection_reason": selected_rejection_reason, "baseline": baseline_action.value},
            )
            try:
                await TelegramNotifier.notify_policy_blocked(case=case, action=None, reason=selected_rejection_reason)
            except Exception as e:
                logger.warning("Telegram notification failed (non-fatal): %s", e)

        elif selected_policy_status == PolicyStatus.NEEDS_REVIEW or selected_autonomy_level == AutonomyLevel.HUMAN_APPROVAL:
            CaseStateMachine.transition_to(case, CaseStatus.PENDING_APPROVAL)
            await ActivityService.record_event(
                session=session,
                event_type=OperationalEventType.POLICY_APPROVED,
                message=f"🛡️ Policy evaluated: Human approval required before dispatching {final_action.value}",
                case_id=case.id,
                tenant_id=case.tenant_id,
                details={"autonomy": "HUMAN_APPROVAL", "enr": selected_candidate["expected_net_recovery"]},
            )

        elif selected_policy_status == PolicyStatus.APPROVED:
            await ActivityService.record_event(
                session=session,
                event_type=OperationalEventType.POLICY_APPROVED,
                message=f"🛡️ Policy Firewall APPROVED {final_action.value} (Autonomy: {selected_autonomy_level.value}, ENR: ₹{selected_candidate['expected_net_recovery']:.2f})",
                case_id=case.id,
                tenant_id=case.tenant_id,
                details={"autonomy": selected_autonomy_level.value, "enr": selected_candidate["expected_net_recovery"]},
            )

            # FULL_AUTO execution path via Outbox & ExecutionWorker (skip outbox for STOP_RECOVERY)
            if selected_autonomy_level == AutonomyLevel.FULL_AUTO and final_action != RecoveryAction.STOP_RECOVERY:
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
        logger.info(f"Decision Engine completed for Case {case.id}. Final Action: {final_action.value}, Status: {case.status.value}")
