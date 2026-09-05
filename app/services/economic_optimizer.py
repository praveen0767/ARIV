import logging
from typing import Iterable, List, Dict, Any
from app.core.config import settings

logger = logging.getLogger("ariv.services.economic_optimizer")


class EconomicOptimizer:
    """Utility for computing expected net recovery (ENR) and ranking candidate recovery actions.

    ENR formula:
        expected_net_recovery = recovery_probability * recoverable_amount - operational_cost - risk_penalty

    Candidates are ranked in descending order of expected_net_recovery.
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
        probability_provider: Any,
        operational_cost: float = None,
        risk_penalty: float = None,
    ) -> List[Dict[str, Any]]:
        """Rank candidate actions by Expected Net Recovery descending.

        Args:
            candidates: Iterable of RecoveryAction values.
            context: DecisionContext providing amount and other metadata.
            probability_provider: Callable(action, context) or object with .estimate(action, context).
            operational_cost: Optional override for operational cost (defaults to config: 10.0).
            risk_penalty: Optional override for risk penalty (defaults to config: 5.0).

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

        ranked.sort(key=lambda x: x["expected_net_recovery"], reverse=True)
        return ranked
