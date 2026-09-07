#!/usr/bin/env python3
"""temporal_decision_engine.py

Implements deterministic temporal decision logic for Phase 3.

Design decisions (as per approved plan):
- Discrete time intervals (`EVALUATION_INTERVAL = 30` minutes)
- Maximum wait duration of 2 hours (`MAX_WAIT_DURATION = 120` minutes)
- Up to `MAX_WAIT_STEPS = 4` wait intervals.
- No stochastic elements – all calculations are deterministic.

The engine evaluates whether waiting (deferring the recovery action) yields a higher
expected monetary value than executing the candidate action immediately.

The simple deterministic model:
- Immediate expected value (EV_now) = p * amount - operational_cost
- Waiting improves the success probability by a fixed increment per interval
  (`PROB_IMPROVEMENT_PER_STEP = 0.10`).
- Each wait interval incurs a waiting cost (`WAIT_COST_PER_STEP = operational_cost * 0.10`).
- The engine will wait while the projected EV after waiting exceeds EV_now and
  while steps remaining > 0.

The engine is lightweight and deterministic, suitable for large‑scale offline
benchmarks.
"""

from __future__ import annotations

from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional

from app.domain.decision import RecoveryAction
from app.domain.schemas import DecisionContext
from app.services.economic_optimizer import EconomicOptimizer
from app.services.probability_provider import ProbabilityProvider

# ---------------------------------------------------------------------------
# Configuration Constants (must match approved design decisions)
# ---------------------------------------------------------------------------
EVALUATION_INTERVAL_MINUTES: int = 30  # 30‑minute discrete interval
MAX_WAIT_DURATION_MINUTES: int = 120   # 2 hours total allowed wait
MAX_WAIT_STEPS: int = 4               # 4 intervals of 30 min each

# Deterministic per‑step adjustments
PROB_IMPROVEMENT_PER_STEP: float = 0.0  # No probability uplift
WAIT_COST_PER_STEP_FACTOR: float = 0.10   # 10% of operational cost per wait step


class TemporalDecision(Enum):
    """Possible actions for the temporal engine.

    - EXECUTE: Perform the candidate recovery action now.
    - WAIT: Defer execution for one interval and re‑evaluate.
    """

    EXECUTE = auto()
    WAIT = auto()


@dataclass
class TemporalState:
    """Tracks the evolving state while waiting.

    Attributes:
        steps_remaining: How many wait intervals are still allowed.
        cumulative_wait_cost: Total cost incurred by waiting so far.
        current_probability: Current estimated recovery probability.
    """

    steps_remaining: int = MAX_WAIT_STEPS
    cumulative_wait_cost: float = 0.0
    current_probability: float = 0.0

    def advance(self, operational_cost: float) -> None:
        """Advance one wait step, updating probability and cost.

        The probability improvement is capped at 1.0. The waiting cost for the
        interval is a deterministic fraction of the operational cost.
        """
        # Improve probability
        self.current_probability = min(1.0, self.current_probability + PROB_IMPROVEMENT_PER_STEP)
        # Incur waiting cost
        self.cumulative_wait_cost += operational_cost * WAIT_COST_PER_STEP_FACTOR
        # Decrement steps
        self.steps_remaining -= 1


class TemporalDecisionEngine:
    """Deterministic engine that decides between WAIT and EXECUTE.

    The engine uses a simple deterministic model: if waiting (with the
    deterministic probability boost) yields a higher expected value than
    executing now, it returns ``TemporalDecision.WAIT``; otherwise ``EXECUTE``.
    """

    def __init__(self, operational_cost: float):
        self.operational_cost = operational_cost

    def evaluate(self, context: DecisionContext, candidate_action: RecoveryAction,
                 base_probability: float) -> TemporalDecision:
        """Return the first decision (WAIT or EXECUTE) based on EV comparison.

        The method is deterministic and does not involve any randomness.
        """
        # Immediate expected value
        ev_now = self._expected_value(base_probability, context.amount, self.operational_cost)

        # Projected value after a single wait step
        projected_prob = min(1.0, base_probability + PROB_IMPROVEMENT_PER_STEP)
        projected_cost = self.operational_cost * (1.0 + WAIT_COST_PER_STEP_FACTOR)
        ev_wait = self._expected_value(projected_prob, context.amount, projected_cost)

        if ev_wait > ev_now and MAX_WAIT_STEPS > 0:
            return TemporalDecision.WAIT
        return TemporalDecision.EXECUTE

    def execute_with_wait(self, context: DecisionContext, candidate_action: RecoveryAction,
                          base_probability: float) -> tuple[RecoveryAction, float, int, float]:
        """Execute the full waiting loop.

        Returns a tuple of:
        - final_action (RecoveryAction)
        - final_probability (float)
        - total_wait_steps (int)
        - total_wait_cost (float)
        """
        state = TemporalState(steps_remaining=MAX_WAIT_STEPS,
                              cumulative_wait_cost=0.0,
                              current_probability=base_probability)
        # Loop while waiting improves EV and steps remain
        while state.steps_remaining > 0:
            ev_now = self._expected_value(state.current_probability, context.amount, self.operational_cost + state.cumulative_wait_cost)
            # Simulate one more wait step to see if EV improves
            next_prob = min(1.0, state.current_probability + PROB_IMPROVEMENT_PER_STEP)
            next_cost = self.operational_cost + state.cumulative_wait_cost + self.operational_cost * WAIT_COST_PER_STEP_FACTOR
            ev_next = self._expected_value(next_prob, context.amount, next_cost)
            if ev_next > ev_now:
                state.advance(self.operational_cost)
            else:
                break
        # After waiting, execute the candidate action
        final_ev = self._expected_value(state.current_probability, context.amount,
                                        self.operational_cost + state.cumulative_wait_cost)
        # The actual monetary outcome (net) will be handled by the outer harness;
        # we return the derived values for accounting.
        return candidate_action, state.current_probability, MAX_WAIT_STEPS - state.steps_remaining, state.cumulative_wait_cost

    @staticmethod
    def _expected_value(prob: float, amount: float, cost: float) -> float:
        """Simple deterministic expected monetary value.

        EV = prob * amount - cost
        """
        return prob * amount - cost


# ---------------------------------------------------------------------------
# Helper function used by the Phase‑3 harness
# ---------------------------------------------------------------------------
def evaluate_temporal_decision(context: DecisionContext, candidate_action: RecoveryAction) -> tuple[RecoveryAction, float, int, float]:
    """Convenience wrapper used by the Phase 3 benchmark harness.

    It obtains the base recovery probability from the existing ProbabilityProvider,
    then runs the deterministic waiting logic.

    Returns:
        (final_action, final_probability, wait_steps, wait_cost)
    """
    # Base probability from the shared provider (deterministic)
    base_prob = ProbabilityProvider.probability(candidate_action, context)
    engine = TemporalDecisionEngine(operational_cost=context.operational_cost if hasattr(context, 'operational_cost') else 0.0)
    # Execute with possible waiting
    return engine.execute_with_wait(context, candidate_action, base_prob)

"""
End of temporal_decision_engine.py
"""
