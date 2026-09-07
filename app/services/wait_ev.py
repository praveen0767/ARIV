#!/usr/bin/env python3
"""wait_ev.py

Phase 4: finite-horizon expected-value model for the WAIT recovery action.

Why a real model (root cause RC-4/#4): the Phase-3 temporal EV keeps the recovery
probability flat while waiting (`prob = base`), so WAIT only ever adds cost and
never wins on economics — it effectively cannot be selected. This module gives
WAIT a defensible expected future value derived from the SAME frozen corridor
state-transition process already used by the temporal layer:

    p_wait(k) = base + max(0, env(k) - env(0)) * (1 - base)

where ``env(k)`` is the expected environment readiness (sum over the finite-horizon
state distribution of ``STATE_BASE_RECOVERY_PROB``) after ``k`` intervals. Intuition:

- If the corridor is already HEALTHY, ``env(k) == env(0)`` and the uplift is 0 —
  waiting on a healthy corridor adds cost and never helps (no spurious WAIT).
- If the corridor is DEGRADED/CRITICAL and trending back to HEALTHY, waiting
  accrues real option value: the action is only attempted once the blocker has a
  chance to clear, and the uplift is bounded by your own success deficit
  ``(1 - base)`` — waiting cannot manufacture certainty.
- Costs (delay + waiting, per interval) are subtracted, and the optimal step ``k``
  in the finite horizon ``[0, MAX_WAIT_STEPS]`` is chosen deterministically.

Design rules:
- Deterministic, public-input only (no hidden future truth).
- Does not modify any existing Phase-3 temporal module or committed artifact:
  this is a NEW model consumed by the Phase-12 A6 (+wait) variant.
- No benchmark tuning: all parameters inherit the frozen corridor transition
  matrix / config constants.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from app.domain.schemas import DecisionContext
from app.domain.decision import RecoveryAction
from app.services.temporal_config import EVALUATION_INTERVAL_MINUTES, MAX_WAIT_STEPS
from app.services.temporal_state import ObservableState, STATE_BASE_RECOVERY_PROB, state_transition_probabilities


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _state_from_route_health(route_health: Any) -> ObservableState:
    """Resolve the observable corridor state from route_health, defaulting to DEGRADED."""
    raw = route_health if isinstance(route_health, dict) else {}
    state_name = raw.get("state") or raw.get("status")
    if isinstance(state_name, ObservableState):
        return state_name
    if state_name is not None:
        try:
            return ObservableState(str(state_name).upper())
        except ValueError:
            pass
    return ObservableState.DEGRADED


@dataclass(frozen=True)
class WaitDecisionModel:
    """Deterministic finite-horizon EV model for the WAIT action.

    Attributes:
        amount_at_risk: Recoverable monetary amount (INR).
        base_recovery_probability: Provider-owned probability of recovery now.
        current_state: Observable corridor state at decision time.
        delay_cost_per_interval: Monetary delay cost per interval (INR/minute).
        waiting_cost_per_interval: Monetary waiting cost per interval (INR/minute).
        horizon: Maximum number of wait intervals to consider (finite horizon).
    """

    amount_at_risk: float
    base_recovery_probability: float
    current_state: ObservableState = ObservableState.DEGRADED
    delay_cost_per_interval: float = 0.01
    waiting_cost_per_interval: float = 0.005
    horizon: int = MAX_WAIT_STEPS

    # ------------------------------------------------------------------
    # Environment model (frozen transition process)
    # ------------------------------------------------------------------

    def env_recovery_probability(self, steps: int) -> float:
        """Expected environment readiness after *steps* transition intervals."""
        dist: Dict[ObservableState, float] = {self.current_state: 1.0}
        for _ in range(max(0, int(steps))):
            new_dist: Dict[ObservableState, float] = defaultdict(float)
            for src, src_p in dist.items():
                for dst, trans_p in state_transition_probabilities.get(src, {}).items():
                    new_dist[dst] += src_p * trans_p
            dist = dict(new_dist)
        return sum(p * STATE_BASE_RECOVERY_PROB[s] for s, p in dist.items())

    # ------------------------------------------------------------------
    # Waiting EV
    # ------------------------------------------------------------------

    def recovery_probability_after_wait(self, steps: int) -> float:
        """Recovery probability if the same action is attempted *steps* intervals later.

        Uplift is proportional to how much the corridor itself recovers over the
        horizon, scaled by the residual failure risk ``(1 - base)``.
        """
        base = _clamp01(self.base_recovery_probability)
        env_now = self.env_recovery_probability(0)
        env_later = self.env_recovery_probability(steps)
        uplift = max(0.0, env_later - env_now)
        return _clamp01(base + uplift * (1.0 - base))

    def _total_wait_cost(self, steps: int) -> float:
        per_interval = (self.delay_cost_per_interval + self.waiting_cost_per_interval) * EVALUATION_INTERVAL_MINUTES
        return per_interval * steps

    def act_now_ev(self) -> float:
        return self.amount_at_risk * _clamp01(self.base_recovery_probability)

    def wait_ev(self, steps: int) -> float:
        if steps <= 0:
            return self.act_now_ev()
        return self.amount_at_risk * self.recovery_probability_after_wait(steps) - self._total_wait_cost(steps)

    # ------------------------------------------------------------------
    # Optimal decision
    # ------------------------------------------------------------------

    def optimal(self) -> Tuple[int, float]:
        """Return ``(best_steps, best_ev)``; ``best_steps == 0`` means act now."""
        best_steps = 0
        best_ev = self.act_now_ev()
        for k in range(1, max(0, self.horizon) + 1):
            ev = self.wait_ev(k)
            if ev > best_ev:
                best_steps, best_ev = k, ev
        return best_steps, best_ev

    def should_wait(self) -> bool:
        return self.optimal()[0] > 0


def evaluate_wait_recommendation(
    context: DecisionContext,
    economic_action: RecoveryAction,
    economic_probability: float,
    delay_cost_per_interval: float = 0.01,
    waiting_cost_per_interval: float = 0.005,
) -> Tuple[RecoveryAction, bool, int, float]:
    """Public-input helper for the A6 (+wait) variant.

    Returns ``(economic_action, should_wait, optimal_steps, wait_ev_at_optimal)``.
    The returned action is still the economically-selected action; the caller may
    defer its execution by ``optimal_steps`` intervals when ``should_wait`` is True.
    """
    state = _state_from_route_health(getattr(context, "route_health", None))
    model = WaitDecisionModel(
        amount_at_risk=getattr(context, "amount", 0.0) or 0.0,
        base_recovery_probability=economic_probability,
        current_state=state,
        delay_cost_per_interval=delay_cost_per_interval,
        waiting_cost_per_interval=waiting_cost_per_interval,
    )
    steps, ev = model.optimal()
    return economic_action, steps > 0, steps, ev


__all__ = [
    "WaitDecisionModel",
    "evaluate_wait_recommendation",
    "_state_from_route_health",
]