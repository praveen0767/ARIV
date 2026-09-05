import abc
from app.domain.classification import FailureCategory
from app.domain.decision import RecoveryAction
from app.domain.schemas import DecisionContext

class RecoveryProbabilityEstimator(abc.ABC):
    """
    Interface for estimating recovery probability.
    Can be backed by heuristics or an ML model.
    """
    
    @abc.abstractmethod
    def estimate_incremental_probability(
        self,
        context: DecisionContext,
        action: RecoveryAction,
    ) -> float:
        """
        Estimate P(recovery | action, context) - P(recovery | baseline, context)
        """
        pass
    
    @abc.abstractmethod
    def estimate_recovery_probability(
        self,
        context: DecisionContext,
        action: RecoveryAction,
    ) -> float:
        """
        Estimate P(recovery | action, context)
        """
        pass


class HeuristicProbabilityEstimator(RecoveryProbabilityEstimator):
    """
    A basic heuristic implementation of RecoveryProbabilityEstimator.
    """
    
    def estimate_recovery_probability(
        self,
        context: DecisionContext,
        action: RecoveryAction,
    ) -> float:
        category = context.classification.failure_category if context.classification else FailureCategory.UNKNOWN
        
        # Non-retriable failures have zero recovery probability
        if category == FailureCategory.NON_RETRIABLE:
            return 0.0
            
        # Basic heuristics for demonstration
        if action == RecoveryAction.GENERATE_PAYMENT_LINK:
            return 0.15 if category == FailureCategory.INSUFFICIENT_FUNDS else 0.25
        elif action == RecoveryAction.RETRY_LATER:
            return 0.10 if category == FailureCategory.INSUFFICIENT_FUNDS else 0.05
        elif action == RecoveryAction.RETRY_NOW:
            return 0.30 if category == FailureCategory.NETWORK_ERROR else 0.02
        elif action == RecoveryAction.ESCALATE_TO_HUMAN:
            return 0.40
            
        return 0.05

    def estimate_incremental_probability(
        self,
        context: DecisionContext,
        action: RecoveryAction,
    ) -> float:
        from app.services.baseline import BaselineService
        baseline_decision = BaselineService.get_deterministic_baseline(context)
        baseline_prob = self.estimate_recovery_probability(context, baseline_decision.baseline_action)
        action_prob = self.estimate_recovery_probability(context, action)
        
        return max(0.0, action_prob - baseline_prob)
