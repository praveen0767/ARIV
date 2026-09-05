import logging
from app.domain.schemas import DecisionProposal
from app.domain.decision import RecoveryAction, AutonomyLevel, PolicyStatus
from app.domain.recovery_case import RecoveryDomain
from app.domain.classification import FailureCategory

logger = logging.getLogger("ariv.services.policy")

class PolicyEngine:
    """
    The deterministic safety gate.
    The AI proposes; the Policy Engine disposes.
    """
    
    @classmethod
    def evaluate(cls, proposal: DecisionProposal, domain: RecoveryDomain, category: FailureCategory) -> tuple[PolicyStatus, AutonomyLevel, str]:
        """
        Validates the AI's proposed action against strict safety policies.
        Returns: (Status, Autonomy Level required, Rejection Reason if any)
        """
        action = proposal.recommended_action
        
        # 1. Global Safety Policy
        if category == FailureCategory.NON_RETRIABLE and action in (RecoveryAction.RETRY_NOW, RecoveryAction.RETRY_LATER):
            logger.warning("Policy Reject: AI proposed retry on NON_RETRIABLE category.")
            return PolicyStatus.REJECTED, AutonomyLevel.SUGGESTION_ONLY, "Cannot retry non-retriable failure."
            
        # 2. Domain Policies
        if domain == RecoveryDomain.B2B:
            # B2B restricts automated financial actions (e.g. RETRY_NOW)
            if action in (RecoveryAction.RETRY_NOW, RecoveryAction.RETRY_LATER):
                return PolicyStatus.NEEDS_REVIEW, AutonomyLevel.HUMAN_APPROVAL, "B2B domain requires human approval for retries."
        
        if domain == RecoveryDomain.EMPLOYEE:
            if action == RecoveryAction.GENERATE_PAYMENT_LINK:
                return PolicyStatus.REJECTED, AutonomyLevel.SUGGESTION_ONLY, "Payment links prohibited for employee payroll."

        # 3. Action specific constraints
        if action == RecoveryAction.STOP_RECOVERY:
            # Always allowed to stop
            return PolicyStatus.APPROVED, AutonomyLevel.FULL_AUTO, None
            
        # Safe default: Approved for FULL_AUTO
        return PolicyStatus.APPROVED, AutonomyLevel.FULL_AUTO, None
