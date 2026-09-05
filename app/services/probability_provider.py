import logging
from typing import List, Tuple, Any
from app.core.config import settings

logger = logging.getLogger("ariv.services.probability_provider")


class ProbabilityProvider:
    """Estimate recovery probability for a candidate action with truthful provenance.

    Rules:
    - If there are >= 5 genuine matching historical cases for the candidate action:
        returns empirical success rate (successes / matching_total) with provenance ["empirical_history"]
    - Otherwise:
        returns deterministic prior from settings.ECONOMIC_DETERMINISTIC_PRIOR (default 0.6)
        with provenance ["deterministic_prior"]

    Strict prohibitions:
    - Never use LLM confidence as recovery probability.
    - Never return fake semantic probability (no "semantic_history" or 0.5 placeholder).
    - Only claim provenances that are actually computed and used.
    """

    MIN_HISTORICAL_MATCHES = 5

    @classmethod
    def estimate(cls, action: Any, context: Any) -> Tuple[float, List[str]]:
        action_name = action.value if hasattr(action, "value") else str(action)
        cases = getattr(context, "historical_cases", []) or []

        matching_total = 0
        matching_successes = 0

        for case in cases:
            if isinstance(case, dict):
                c_action = case.get("action_type") or case.get("action")
                c_outcome = case.get("outcome_status") or case.get("outcome")
            else:
                c_action = getattr(case, "action_type", None) or getattr(case, "action", None)
                c_outcome = getattr(case, "outcome_status", None) or getattr(case, "outcome", None)

            c_act_str = c_action.value if hasattr(c_action, "value") else str(c_action or "")
            if c_act_str.upper() == action_name.upper():
                matching_total += 1
                outcome_str = str(c_outcome or "").upper()
                if outcome_str in ("RECOVERED", "SUCCESS", "PAID"):
                    matching_successes += 1

        # Branch 1: Empirical history (only if >= MIN_HISTORICAL_MATCHES genuine matches)
        if matching_total >= cls.MIN_HISTORICAL_MATCHES:
            empirical_prob = matching_successes / matching_total
            return max(0.0, min(1.0, float(empirical_prob))), ["empirical_history"]

        # Branch 2: Deterministic prior fallback
        prior = float(getattr(settings, "ECONOMIC_DETERMINISTIC_PRIOR", 0.6))
        return max(0.0, min(1.0, prior)), ["deterministic_prior"]

    def __call__(self, action: Any, context: Any) -> Tuple[float, List[str]]:
        return self.estimate(action, context)
