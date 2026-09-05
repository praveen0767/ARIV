from app.domain.decision import RecoveryAction
from app.domain.schemas import DecisionContext
from app.domain.recovery.baseline_decision import BaselineDecision
from app.domain.classification import FailureCategory, Retryability
from app.domain.recovery_case import RecoveryDomain

class DeterministicBaseline:
    """
    Deterministic baseline engine mapping domain, failure_category, and retryability
    to a baseline RecoveryAction.
    """
    @staticmethod
    def decide(
        domain: RecoveryDomain = None,
        category: FailureCategory = None,
        retryability: Retryability = None,
        failure_category: FailureCategory = None
    ) -> RecoveryAction:
        cat = category or failure_category
        if cat == FailureCategory.TRANSIENT_TECHNICAL and retryability == Retryability.LATER_RETRY_POSSIBLE:
            return RecoveryAction.RETRY_LATER
        elif cat == FailureCategory.TRANSIENT_TECHNICAL and retryability == Retryability.IMMEDIATE_RETRY_POSSIBLE:
            return RecoveryAction.RETRY_NOW
        elif domain == RecoveryDomain.B2B and cat == FailureCategory.UNKNOWN:
            return RecoveryAction.ESCALATE_TO_HUMAN
        elif cat == FailureCategory.NON_RETRIABLE or retryability == Retryability.BLOCKED:
            return RecoveryAction.STOP_RECOVERY
        elif cat == FailureCategory.CUSTOMER_ACTION_REQUIRED:
            return RecoveryAction.GENERATE_PAYMENT_LINK
        elif cat == FailureCategory.PAYMENT_METHOD_PROBLEM:
            return RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE
        elif cat == FailureCategory.UNKNOWN:
            return RecoveryAction.ESCALATE_TO_HUMAN
        return RecoveryAction.STOP_RECOVERY

class BaselineService:
    """
    Deterministic baseline policy representing what ARIV would do 
    without the adaptive AI decision layer.
    """
    
    CURRENT_POLICY_VERSION = "v1.0.0-baseline"
    BASELINE_METHOD = "deterministic_heuristic"
    PROVENANCE = "heuristic: 5% of case amount for retriable actions, 0 for STOP_RECOVERY; unvalidated estimate, not an empirical counterfactual"
    
    @classmethod
    def get_deterministic_baseline(cls, context: DecisionContext) -> BaselineDecision:
        """
        Returns the baseline decision for a given context using DeterministicBaseline.
        DecisionContext stores failure_category, retryability, and domain as top-level fields.
        Labeled explicitly as an unvalidated heuristic estimate.
        """
        # Access fields directly or from nested objects for compatibility with StubContext
        category = getattr(context, "failure_category", None) or (getattr(context.classification, "failure_category", None) if hasattr(context, "classification") else None) or FailureCategory.UNKNOWN
        retryability = getattr(context, "retryability", None) or (getattr(context.classification, "retryability", None) if hasattr(context, "classification") else None) or Retryability.BLOCKED
        domain = getattr(context, "domain", None) or (getattr(context.case, "domain", None) if hasattr(context, "case") else None) or RecoveryDomain.B2C
        case_id = getattr(context, "case_id", None) or (getattr(context.case, "id", None) if hasattr(context, "case") else None)

        baseline_action = DeterministicBaseline.decide(
            domain=domain,
            category=category,
            retryability=retryability,
        )

        # Baseline expected recovery: 5% heuristic for retriable actions, 0 for STOP_RECOVERY
        expected_recovery = 0
        case_amount = getattr(context, "amount", None) or (getattr(context.case, "amount", 0) if hasattr(context, "case") else 0) or 0
        if baseline_action != RecoveryAction.STOP_RECOVERY and case_amount:
            expected_recovery = int(case_amount * 0.05)

        return BaselineDecision(
            case_id=case_id,
            baseline_action=baseline_action,
            policy_version=cls.CURRENT_POLICY_VERSION,
            expected_recovery_amount=expected_recovery,
            baseline_method=cls.BASELINE_METHOD,
            provenance=cls.PROVENANCE,
            is_estimate=True,
        )

