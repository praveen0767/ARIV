"""route_aware_probability.py

Phase 5: corridor / route health as an INPUT to the recovery-probability estimate.

Root cause RC-2a/RC-3: route health was used only as a candidate filter and an
AI-prompt token, never as a probability input, so the economic rank never
'felt' the corridor state — retries were estimated at their nominal probability
even on a DEGRADED/CRITICAL corridor, allowing a memory-boosted RETRY_LATER
(0.8) to beat the route-appropriate GENERATE_PAYMENT_LINK (0.70) on a systemic
outage.

Phase 5 fix (from docs/final-upgrade/ai-root-cause.md §5.3): route health now
*discounts* the ENR of online / network-dependent retry actions.

   p'(action) = p(action) * route_discount(route_health, action)

- The inner estimate comes from the deterministic provider (or the Phase-3
  recovery learner), so LLM never influences the number.
- Only retry-type actions that hit the failed rail are discounted: RETRY_NOW and
  RETRY_LATER. Asynchronous / offline actions (GENERATE_PAYMENT_LINK,
  SEND_REMINDER, REQUEST_PAYMENT_METHOD_UPDATE) and the terminal STOP_RECOVERY
  keep their nominal estimate - on a systemic outage those do not depend on the
  degraded retry rail, which matches the modeled evaluation truth (B2C systemic
  outage: GPL 0.70 vs RETRY_LATER 0.35).
- Deterministic, public-input only, provider-own provenance.

Discount factors are a documented modeling assumption (NOT tuned on held-out
seeds): HEALTHY/OPERATIONAL = 1.0, DEGRADED = 0.55, CRITICAL = 0.15.
"""

from __future__ import annotations

from typing import Any, FrozenSet, Tuple

from app.domain.decision import RecoveryAction

# Actions that depend on the live (retry/authorisation) rail.
ONLINE_RETRY_ACTIONS: FrozenSet[str] = frozenset({"RETRY_NOW", "RETRY_LATER"})

ROUTE_HEALTH_DISCOUNT = {
    "HEALTHY": 1.0,
    "OPERATIONAL": 1.0,
    "DEGRADED": 0.55,
    "CRITICAL": 0.15,
}


def resolve_route_state(route_health: Any) -> str:
    """Return a normalized route-health state token from a route_health value."""
    if not isinstance(route_health, dict):
        return "OPERATIONAL"
    raw = route_health.get("status") or route_health.get("state") or route_health.get("summary") or ""
    token = str(raw).upper().strip()
    if token in ROUTE_HEALTH_DISCOUNT:
        return token
    if "CRITICAL" in token:
        return "CRITICAL"
    if "DEGRADED" in token:
        return "DEGRADED"
    return "OPERATIONAL"


def route_discount(route_health: Any, action: Any) -> float:
    """Return the corridor-state multiplier for an action (public, deterministic)."""
    action_name = action.name if hasattr(action, "name") else str(action)
    action_name = action_name.upper()
    state = resolve_route_state(route_health)
    if action_name not in ONLINE_RETRY_ACTIONS:
        return 1.0
    return ROUTE_HEALTH_DISCOUNT.get(state, 1.0)


class RouteAwareProbabilityProvider:
    """Wraps a deterministic probability provider and discounts online retries
    on degraded corridors. Drop-in for ``EconomicOptimizer.rank_candidates``.

    ``inner_provider`` may be a class with ``.estimate(action, context)``
    (``ProbabilityProvider``) or an instance (``RecoveryLearningService``).
    """

    def __init__(self, inner_provider: Any = None, risk_adjusted: bool = True):
        from app.services.probability_provider import ProbabilityProvider
        self.inner_provider = inner_provider if inner_provider is not None else ProbabilityProvider
        self.risk_adjusted = risk_adjusted

    def estimate(self, action: Any, context: Any) -> Tuple[float, list]:
        provider = self.inner_provider
        if isinstance(provider, type):
            prob, provenance = provider.estimate(action, context)
        elif hasattr(provider, "estimate"):
            prob, provenance = provider.estimate(action, context)
        else:
            prob, provenance = 0.6, ["deterministic_prior"]

        prob = max(0.0, min(1.0, float(prob)))

        if not self.risk_adjusted:
            return prob, provenance + ["route_health_unadjusted"]

        route_health = getattr(context, "route_health", None)
        discount = route_discount(route_health, action)
        adjusted = max(0.0, min(1.0, prob * discount))

        provenance_out = list(provenance)
        state = resolve_route_state(route_health)
        if discount < 1.0:
            provenance_out.append(f"route_health:{state}:x{discount}")
        return adjusted, provenance_out

    def __call__(self, action: Any, context: Any) -> Tuple[float, list]:
        return self.estimate(action, context)


__all__ = [
    "RouteAwareProbabilityProvider",
    "route_discount",
    "resolve_route_state",
    "ROUTE_HEALTH_DISCOUNT",
    "ONLINE_RETRY_ACTIONS",
]