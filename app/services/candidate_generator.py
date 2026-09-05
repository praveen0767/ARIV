from typing import List, Optional

from app.domain.decision import RecoveryAction
from app.domain.recovery_case import RecoveryDomain
from app.domain.classification import FailureCategory
from app.domain.schemas import DecisionContext, DecisionProposal
from app.services.baseline import DeterministicBaseline


class CandidateGenerator:
    """Generate a small, context-aware set of realistic candidate actions (maximum 5).

    Sources candidates from:
    1. AI proposal recommended_action
    2. AI proposal candidate_actions
    3. Deterministic baseline action
    4. Business/domain eligible fallback actions

    Deduplicates and enforces domain/failure category eligibility rules.
    """

    MAX_CANDIDATES = 5

    @classmethod
    def is_eligible(cls, action: RecoveryAction, context: DecisionContext) -> bool:
        """Check basic domain and classification eligibility rules."""
        if not isinstance(action, RecoveryAction):
            return False

        # Non-retriable failures cannot have retry actions
        if context.failure_category == FailureCategory.NON_RETRIABLE:
            if action in (RecoveryAction.RETRY_NOW, RecoveryAction.RETRY_LATER):
                return False

        # Employee payroll domain cannot generate customer payment links
        if context.domain == RecoveryDomain.EMPLOYEE:
            if action == RecoveryAction.GENERATE_PAYMENT_LINK:
                return False

        # Systemic degradation: suppress immediate retries on degraded or critical routes
        if context.route_health and context.route_health.get("status") in ("DEGRADED", "CRITICAL"):
            if action == RecoveryAction.RETRY_NOW:
                return False

        return True

    @classmethod
    def generate_candidates(
        cls,
        context: DecisionContext,
        ai_proposal: Optional[DecisionProposal] = None,
    ) -> List[RecoveryAction]:
        raw_candidates: List[RecoveryAction] = []

        # 1. AI recommended action
        if ai_proposal and ai_proposal.recommended_action:
            raw_candidates.append(ai_proposal.recommended_action)

        # 2. AI candidate actions
        if ai_proposal and ai_proposal.candidate_actions:
            raw_candidates.extend(ai_proposal.candidate_actions)

        # 3. Deterministic baseline action
        baseline = context.baseline_action
        if not baseline:
            baseline = DeterministicBaseline.decide(
                domain=context.domain,
                category=context.failure_category,
                retryability=context.retryability,
            )
        if baseline:
            raw_candidates.append(baseline)

        # 4. Standard business-eligible candidate pool based on context
        standard_pool = [
            RecoveryAction.GENERATE_PAYMENT_LINK,
            RecoveryAction.SEND_REMINDER,
            RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE,
            RecoveryAction.RETRY_LATER,
            RecoveryAction.STOP_RECOVERY,
        ]
        raw_candidates.extend(standard_pool)

        # Deduplicate while preserving order and filtering by eligibility
        seen = set()
        final_candidates: List[RecoveryAction] = []
        for act in raw_candidates:
            if act not in seen and cls.is_eligible(act, context):
                seen.add(act)
                final_candidates.append(act)
                if len(final_candidates) >= cls.MAX_CANDIDATES:
                    break

        if not final_candidates:
            final_candidates = [RecoveryAction.STOP_RECOVERY]

        return final_candidates
