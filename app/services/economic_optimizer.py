import logging
from typing import Iterable, List, Dict, Any
from app.core.config import settings
from app.domain.decision import RecoveryAction

logger = logging.getLogger("ariv.services.economic_optimizer")

# Deterministic kick order for ENR ties. The LLM never gets to steer decisions
# through candidate ordering: when expected net recoveries tie, the ranking is
# resolved by a fixed, insertion-order-independent preference (auditable
# baseline action first, then customer-driven low-friction actions, retries
# and human escalation lower, STOP_RECOVERY last).
DETERMINISTIC_TIE_BREAK = "deterministic_priority"
LEGACY_TIE_BREAK = "preserve_order"

_TIE_BREAK_TIERS: Dict[Any, int] = {
    RecoveryAction.GENERATE_PAYMENT_LINK: 1,
    RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE: 2,
    RecoveryAction.SEND_REMINDER: 3,
    RecoveryAction.RETRY_LATER: 4,
    RecoveryAction.WAIT: 5,
    RecoveryAction.RETRY_NOW: 5,
    RecoveryAction.ESCALATE_TO_HUMAN: 6,
    RecoveryAction.STOP_RECOVERY: 7,
}


class EconomicOptimizer:
    """Utility for computing expected net recovery (ENR) and ranking candidate recovery actions.

    ENR formula:
        expected_net_recovery = recovery_probability * recoverable_amount - operational_cost - risk_penalty

    Candidates are ranked in descending order of expected_net_recovery.

    Tie breaks:
    - ``deterministic_priority`` (default): ENR ties are resolved by a fixed,
      insertion-order-independent preference (deterministic baseline action first,
      then low-friction customer actions). The AI cannot influence which candidate
      wins a tie through recommendation/candidate ordering.
    - ``preserve_order`` (legacy): stable sort keeps the original candidate order
      for tied ENRs. Used ONLY by frozen legacy benchmark/ablation harnesses to
      keep committed artifacts bit-for-bit reproducible.
    """

    @staticmethod
    def compute_expected_net_recovery(
        probability: float,
        recoverable_amount: float,
        operational_cost: float = 0.0,
        risk_penalty: float = 0.0,
    ) -> float:
        """Return the Expected Net Recovery (ENR).

        Args:
            probability: Probability of successful recovery (0.0 to 1.0).
            recoverable_amount: Monetary amount that could be recovered.
            operational_cost: Direct operational/channel cost of attempting recovery.
            risk_penalty: Risk penalty for customer friction, chargeback risk, or retry penalties.
        """
        prob = max(0.0, min(1.0, float(probability)))
        amt = max(0.0, float(recoverable_amount))
        op_cost = max(0.0, float(operational_cost))
        risk = max(0.0, float(risk_penalty))
        return round((prob * amt) - op_cost - risk, 4)

    @classmethod
    def rank_candidates(
        cls,
        candidates: Iterable[Any],
        context: Any,
        probability_provider: Any = None,
        operational_cost: float = None,
        risk_penalty: float = None,
        tie_break: str = DETERMINISTIC_TIE_BREAK,
    ) -> List[Dict[str, Any]]:
        """Rank candidate actions by Expected Net Recovery descending.

        Args:
            candidates: Iterable of RecoveryAction values.
            context: DecisionContext providing amount and other metadata.
            probability_provider: Callable(action, context) or object with .estimate(action, context).
            operational_cost: Optional override for operational cost (defaults to config: 10.0).
            risk_penalty: Optional override for risk penalty (defaults to config: 5.0).
            tie_break: "deterministic_priority" (default, order-neutral) or "preserve_order" (legacy).

        Returns:
            List of dicts sorted descending by expected_net_recovery. Each dict contains:
                action, recovery_probability, probability_provenance,
                recoverable_amount, operational_cost, risk_penalty, expected_net_recovery.
        """
        if operational_cost is None:
            operational_cost = float(getattr(settings, "ECONOMIC_OPERATIONAL_COST", 10.0))
        if risk_penalty is None:
            risk_penalty = float(getattr(settings, "ECONOMIC_RISK_PENALTY", 5.0))

        recoverable_amount = float(getattr(context, "amount", 0.0) or 0.0)

        ranked: List[Dict[str, Any]] = []
        for action in candidates:
            if hasattr(probability_provider, "estimate"):
                prob, provenance = probability_provider.estimate(action, context)
            elif callable(probability_provider):
                prob, provenance = probability_provider(action, context)
            else:
                prob = float(getattr(settings, "ECONOMIC_DETERMINISTIC_PRIOR", 0.6))
                provenance = ["deterministic_prior"]

            enr = cls.compute_expected_net_recovery(
                probability=prob,
                recoverable_amount=recoverable_amount,
                operational_cost=operational_cost,
                risk_penalty=risk_penalty,
            )

            ranked.append({
                "action": action,
                "recovery_probability": prob,
                "probability_provenance": provenance,
                "recoverable_amount": recoverable_amount,
                "operational_cost": operational_cost,
                "risk_penalty": risk_penalty,
                "expected_net_recovery": enr,
            })

        if tie_break == LEGACY_TIE_BREAK:
            # Legacy: stable sort -> tied ENRs keep candidate insertion order.
            # Used ONLY by frozen legacy benchmark/ablation harnesses.
            ranked.sort(key=lambda x: x["expected_net_recovery"], reverse=True)
        else:
            # Order-neutral: tie ENRs by a deterministic, insertion-order-
            # independent preference so the AI cannot win ties via ordering.
            baseline_action = getattr(context, "baseline_action", None)
            if not isinstance(baseline_action, RecoveryAction):
                baseline_action = None

            def _tie_priority(item: Dict[str, Any]) -> int:
                action = item["action"]
                if baseline_action is not None and action == baseline_action:
                    return 0
                return _TIE_BREAK_TIERS.get(action, 90)

            ranked.sort(key=lambda x: (-x["expected_net_recovery"], _tie_priority(x)))
        return ranked
