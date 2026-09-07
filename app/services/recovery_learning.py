"""
app/services/recovery_learning.py

Phase 3: Adaptive recovery learning with Dirichlet-smoothed, corridor-aware,
provider-confirmed memory.

Replaces the corridor-blind / unsmoothed frozen-memory injection and fixes
root causes RC-2a and RC-2b:

- RC-2a (corridor-blind probability boost): memory is partitioned by
  ``(domain, failure_category, corridor)``. Recovery precedents from one payment
  corridor can never inflate the probability of the same action on a different
  corridor (e.g. RETRY_LATER precedents on the healthy corridor must not beat a
  route-aware GPL on the degraded corridor).
- RC-2b (p(STOP) collapses to 0 → hard-fraud flips to futile GPL): empirical
  rates are Dirichlet-smoothed toward the deterministic prior with beta > 0 so
  the probability is NEVER 0; a minimum support is required before experience may
  override the prior at all; and STOP_RECOVERY is a frozen action whose
  probability is always the prior (by construction STOP is "never recovered", so
  its own "FAILED" outcomes must not depress it).

Only provider-confirmed terminal outcomes (`RECOVERED/PAID/SUCCESS` = success,
otherwise `FAILED/CANCELLED/EXPIRED/...` = attempt) are learned. Provisional
statuses (`PENDING/IN_PROGRESS/QUEUED/RETRYING/...`) never touch the store, which
prevents the memory from learning from our own speculative interventions.

The learner is a drop-in for ``ProbabilityProvider`` in
``EconomicOptimizer.rank_candidates`` (object with ``.estimate(action, context)``).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from app.core.config import settings
from app.domain.decision import RecoveryAction

logger = logging.getLogger("ariv.services.recovery_learning")

# Provider-confirmed terminal outcome families.
CONFIRMED_SUCCESS_OUTCOMES = frozenset({"RECOVERED", "SUCCESS", "PAID"})
CONFIRMED_ATTEMPT_OUTCOMES = frozenset({
    "FAILED", "CANCELLED", "EXPIRED", "DECLINED", "NOT_RECOVERED",
    "STOPPED", "EXHAUSTED", "TERMINAL_FAILURE", "BLOCKED",
})
# Outcome values that are still in flight or speculative intervention states.
UNCONFIRMED_OUTCOMES = frozenset({
    "PENDING", "IN_PROGRESS", "PROPOSED", "QUEUED", "RETRYING",
    "PROCESSING", "SUBMITTED", "REQUESTED", "SCHEDULED", "WAITING",
})

# Actions whose probability is never learned from their own outcomes.
# STOP_RECOVERY is the terminal action: it is "not recovered" by construction,
# so counting its own failures would fabricate a false p(STOP)≈0 (RC-2b).
FROZEN_ACTIONS = frozenset({RecoveryAction.STOP_RECOVERY})


def _norm_action(action: Any) -> str:
    if hasattr(action, "name"):
        return action.name
    if hasattr(action, "value"):
        return action.value
    return str(action)


def _prior() -> float:
    return float(getattr(settings, "ECONOMIC_DETERMINISTIC_PRIOR", 0.6))


class RecoveryLearningService:
    """Dirichlet-smoothed, corridor-aware, provider-confirmed recovery memory."""

    def __init__(
        self,
        beta: Optional[float] = None,
        min_support: Optional[int] = None,
        prior: Optional[float] = None,
    ) -> None:
        self.beta = float(beta if beta is not None else getattr(settings, "RECOVERY_LEARNING_BETA", 4.0))
        self.min_support = int(min_support if min_support is not None
                               else getattr(settings, "RECOVERY_LEARNING_MIN_SUPPORT", 5))
        self.prior = float(prior if prior is not None else _prior())
        # memory[key][action_name] = {"total": n, "successes": s}
        self._memory: Dict[Tuple, Dict[str, Dict[str, int]]] = {}

    # ------------------------------------------------------------------
    # Memory mutation
    # ------------------------------------------------------------------

    @staticmethod
    def _provider_confirmed_status(outcome: Any) -> Optional[str]:
        """Return a normalized confirmed outcome (success/attempt) or None if unconfirmed."""
        if outcome is None:
            return None
        out = str(outcome).strip().upper()
        if out in CONFIRMED_SUCCESS_OUTCOMES:
            return "success"
        if out in CONFIRMED_ATTEMPT_OUTCOMES:
            return "attempt"
        if out in UNCONFIRMED_OUTCOMES:
            return None
        return None

    def record_outcome(
        self,
        domain: Any,
        failure_category: Any,
        corridor: Optional[str],
        action: Any,
        outcome: Any,
    ) -> bool:
        """Record a provider-confirmed terminal outcome for an action in a corridor key.

        Returns True if the outcome was recorded, False if it was ignored
        (unconfirmed status, or a frozen action like STOP_RECOVERY).
        """
        act = _norm_action(action)
        if act in FROZEN_ACTIONS:
            logger.debug("Refusing to learn probability from terminal action %s", act)
            return False

        kind = self._provider_confirmed_status(outcome)
        if kind is None:
            return False

        key = self._key(domain, failure_category, corridor)
        bucket = self._memory.setdefault(key, {}).setdefault(act, {"total": 0, "successes": 0})
        bucket["total"] += 1
        if kind == "success":
            bucket["successes"] += 1
        return True

    def record_from_case(self, case: Dict[str, Any]) -> bool:
        """Convenience: record from a case-like dict with keys domain,
        failure_category, corridor (optional) and any action/outcome naming."""
        domain = case.get("domain")
        category = case.get("failure_category")
        corridor = case.get("corridor")
        action = case.get("action_type") or case.get("action")
        outcome = case.get("outcome_status") or case.get("outcome")
        return self.record_outcome(domain, category, corridor, action, outcome)

    # ------------------------------------------------------------------
    # Estimation (drop-in for ProbabilityProvider)
    # ------------------------------------------------------------------

    def estimate(self, action: Any, context: Any) -> Tuple[float, list]:
        act = _norm_action(action)

        if act in FROZEN_ACTIONS:
            return max(0.0, min(1.0, self.prior)), ["deterministic_prior"]

        key = self._context_key(context)
        bucket = self._memory.get(key, {}).get(act)
        if bucket is None or bucket["total"] < self.min_support:
            return max(0.0, min(1.0, self.prior)), ["deterministic_prior"]

        n = bucket["total"]
        s = bucket["successes"]
        # Dirichlet smoothing toward the deterministic prior: never 0.
        prob = (s + self.beta * self.prior) / (n + self.beta)
        prob = max(0.0, min(1.0, prob))
        return prob, ["empirical_history_smoothed"]

    def __call__(self, action: Any, context: Any) -> Tuple[float, list]:
        return self.estimate(action, context)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def reset(self) -> None:
        self._memory = {}

    def summary(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for (domain, category, corridor), actions in self._memory.items():
            out[f"{domain}|{category}|{corridor}"] = {
                act: dict(stats) for act, stats in actions.items()
            }
        return out

    @property
    def memory(self) -> Dict[Tuple, Dict[str, Dict[str, int]]]:
        return self._memory

    def _key(self, domain: Any, failure_category: Any, corridor: Any) -> Tuple:
        d = getattr(domain, "value", domain) or "UNKNOWN"
        c = getattr(failure_category, "value", failure_category) or "UNKNOWN"
        return (str(d).upper(), str(c).upper(), str(corridor or "") or None)

    def _context_key(self, context: Any) -> Tuple:
        domain = getattr(context, "domain", None)
        category = getattr(context, "failure_category", None)
        route_health = getattr(context, "route_health", None) or {}
        corridor = route_health.get("corridor") or route_health.get("corridor_id")
        return self._key(domain, category, corridor)


__all__ = [
    "RecoveryLearningService",
    "CONFIRMED_SUCCESS_OUTCOMES",
    "CONFIRMED_ATTEMPT_OUTCOMES",
    "UNCONFIRMED_OUTCOMES",
    "FROZEN_ACTIONS",
]