#!/usr/bin/env python3
"""temporal_layer.py

Deterministic temporal decision wrapper for Phase 3.
It uses a frozen finite‑state transition model (temporal_state.py) and
canonical configuration constants (temporal_config.py).
The wrapper never accesses hidden future information.
"""

from enum import Enum, auto
from dataclasses import dataclass
from typing import Tuple, Dict

from app.services.policy import PolicyEngine
from app.domain.decision import RecoveryAction, PolicyStatus
from app.domain.schemas import DecisionProposal
from app.domain.schemas import DecisionContext

# Canonical config
from app.services.temporal_config import (
    EVALUATION_INTERVAL_MINUTES,
    MAX_WAIT_DURATION_MINUTES,
    MAX_WAIT_STEPS,
)

# Deterministic transition model
from app.services.temporal_transition import (
    ObservableState,
    TRANSITION_MATRIX,
    STATE_BASE_RECOVERY_PROB,
)

# ---------------------------------------------------------------------------
# TemporalDecision – actions considered by the wrapper.
# ---------------------------------------------------------------------------
class TemporalDecision(Enum):
    ACT_NOW = auto()
    RETRY_LATER = auto()
    WAIT = auto()
    NUDGE = auto()
    STOP_RECOVERY = auto()

# ---------------------------------------------------------------------------
# Deterministic EV model (same as before, but without hidden truth).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TemporalValueModel:
    """Pure‑function model for computing expected monetary value.

    All inputs are public – no hidden truth is consulted.
    """

    amount_at_risk: float
    base_recovery_probability: float  # probability without any waiting
    delay_cost_per_interval: float = 0.0
    waiting_cost_per_interval: float = 0.0
    max_wait_steps: int = MAX_WAIT_STEPS

    def _costs(self, steps: int) -> Tuple[float, float]:
        """Return total delay and waiting costs for *steps* intervals."""
        total_delay = self.delay_cost_per_interval * steps * EVALUATION_INTERVAL_MINUTES
        total_wait = self.waiting_cost_per_interval * steps * EVALUATION_INTERVAL_MINUTES
        return total_delay, total_wait

    def expected_value_for_wait(self, wait_steps: int) -> float:
        """EV after waiting *wait_steps* intervals.

        The recovery probability stays the base probability; only costs increase.
        """
        prob = self.base_recovery_probability
        total_delay, total_wait = self._costs(wait_steps)
        return self.amount_at_risk * prob - total_delay - total_wait

    def expected_value(self, decision: TemporalDecision, wait_steps: int = 0) -> float:
        if decision == TemporalDecision.ACT_NOW:
            return self.amount_at_risk * self.base_recovery_probability
        if decision == TemporalDecision.RETRY_LATER:
            return self.expected_value_for_wait(1)
        if decision == TemporalDecision.WAIT:
            return self.expected_value_for_wait(wait_steps)
        if decision == TemporalDecision.NUDGE:
            prob = min(1.0, self.base_recovery_probability + 0.02)
            return self.amount_at_risk * prob
        if decision == TemporalDecision.STOP_RECOVERY:
            return 0.0
        raise ValueError(f"Unsupported TemporalDecision: {decision}")

# ---------------------------------------------------------------------------
# Helper to compute the best non‑WAIT EV for a given observable state.
# ---------------------------------------------------------------------------
def _best_non_wait_ev(state: ObservableState, amount: float, delay_cost: float, waiting_cost: float) -> float:
    base_prob = STATE_BASE_RECOVERY_PROB[state]
    model = TemporalValueModel(
        amount_at_risk=amount,
        base_recovery_probability=base_prob,
        delay_cost_per_interval=delay_cost,
        waiting_cost_per_interval=waiting_cost,
    )
    candidates = [
        model.expected_value(TemporalDecision.ACT_NOW),
        model.expected_value(TemporalDecision.RETRY_LATER),
        model.expected_value(TemporalDecision.NUDGE),
    ]
    return max(candidates)

# ---------------------------------------------------------------------------
# Main wrapper used by the Phase 3 harness.
# ---------------------------------------------------------------------------
def evaluate_temporal_decision(
    context: DecisionContext,
    economic_action: RecoveryAction,
    economic_probability: float,
    delay_cost_per_interval: float = 0.01,
    waiting_cost_per_interval: float = 0.005,
) -> Tuple[RecoveryAction, TemporalDecision]:
    """Select a temporal decision based on deterministic EV calculations.

    The decision layer sees only the public context and the frozen transition
    probabilities. It never inspects hidden future trajectories.
    """
    # Determine current observable state from route_health if available.
    # Safely handle route_health which may be a dict or a simple value.
    route_health_raw = getattr(context, "route_health", None)
    if isinstance(route_health_raw, dict):
        route_health = route_health_raw
    else:
        route_health = {}
    state_name = route_health.get("state", "DEGRADED")
    try:
        current_state = ObservableState(state_name)
    except ValueError:
        current_state = ObservableState.DEGRADED

    base_model = TemporalValueModel(
        amount_at_risk=context.amount,
        base_recovery_probability=economic_probability,
        delay_cost_per_interval=delay_cost_per_interval,
        waiting_cost_per_interval=waiting_cost_per_interval,
    )

    # Non‑WAIT EVs using economic_probability.
    non_wait_evs = {
        TemporalDecision.ACT_NOW: base_model.expected_value(TemporalDecision.ACT_NOW),
        TemporalDecision.RETRY_LATER: base_model.expected_value(TemporalDecision.RETRY_LATER),
        TemporalDecision.NUDGE: base_model.expected_value(TemporalDecision.NUDGE),
        TemporalDecision.STOP_RECOVERY: base_model.expected_value(TemporalDecision.STOP_RECOVERY),
    }
    best_ev = max(non_wait_evs.values())
    best_action = {
        ev: td for td, ev in non_wait_evs.items() if ev == best_ev
    }[best_ev]
    best_temporal = {
        TemporalDecision.ACT_NOW: TemporalDecision.ACT_NOW,
        TemporalDecision.RETRY_LATER: TemporalDecision.RETRY_LATER,
        TemporalDecision.NUDGE: TemporalDecision.NUDGE,
        TemporalDecision.STOP_RECOVERY: TemporalDecision.STOP_RECOVERY,
    }[best_action]

    # Evaluate WAIT options using frozen transition model.
    distribution: Dict[ObservableState, float] = {current_state: 1.0}
    for step in range(1, MAX_WAIT_STEPS + 1):
        # Multi‑step propagation using deterministic TRANSITION_MATRIX
        new_dist: Dict[ObservableState, float] = {}
        for src_state, src_prob in distribution.items():
            for dst_state, trans_prob in TRANSITION_MATRIX.get(src_state, {}).items():
                new_dist[dst_state] = new_dist.get(dst_state, 0.0) + src_prob * trans_prob
        distribution = new_dist

        # Compute expected EV after waiting 'step' intervals.
        ev_wait = 0.0
        for dst_state, prob_state in distribution.items():
            ev_wait += prob_state * _best_non_wait_ev(
                dst_state,
                amount=context.amount,
                delay_cost=delay_cost_per_interval,
                waiting_cost=waiting_cost_per_interval,
            )
        total_delay, total_wait = base_model._costs(step)
        ev_wait -= total_delay + total_wait
        if ev_wait > best_ev:
            best_ev = ev_wait
            best_temporal = TemporalDecision.WAIT
            best_action = economic_action

    # Policy enforcement
    # Convert domain and failure_category to proper enums if they are strings, with fallback defaults
    from app.domain.recovery_case import RecoveryDomain
    from app.domain.classification import FailureCategory
    try:
        domain_enum = (
            context.domain if isinstance(context.domain, RecoveryDomain) else RecoveryDomain(context.domain)
        )
    except Exception:
        domain_enum = RecoveryDomain.B2C
    try:
        category_enum = (
            context.failure_category if isinstance(context.failure_category, FailureCategory) else FailureCategory(context.failure_category)
        )
    except Exception:
        category_enum = FailureCategory.UNKNOWN
    p_status, _, _ = PolicyEngine.evaluate(
        proposal=DecisionProposal(recommended_action=best_action),
        domain=domain_enum,
        category=category_enum,
        route_health=context.route_health if isinstance(context.route_health, dict) else {},
    )
    if p_status not in (PolicyStatus.APPROVED, PolicyStatus.NEEDS_REVIEW):
        best_action = RecoveryAction.STOP_RECOVERY
        best_temporal = TemporalDecision.STOP_RECOVERY

    return best_action, best_temporal
