#!/usr/bin/env python3
"""temporal_oracle.py

Provides a *oracle* implementation used only during evaluation to compute the
optimal temporal decision given full hidden future trajectory. The oracle is **never**
used by the production decision path – it is called exclusively from the Phase 3
benchmark harness for regret calculation.

The oracle receives the same public ``DecisionContext`` plus a hidden future
snapshot (the hidden truth) and returns the best possible ``TemporalDecision``
and the associated expected monetary value. Because the hidden future is
deterministic (generated via common random numbers), the oracle can compute the
true optimal wait steps by examining the exact time when a recovery would occur.
"""

from typing import Tuple

from app.services.temporal_layer import TemporalDecision, TemporalValueModel
from app.domain.schemas import DecisionContext

# The hidden future payload structure is defined in ``scripts.run_judge_benchmark``
# as part of the case record under the key ``hidden``. It contains:
#   - ``recovery_time_minutes``: minutes after failure when recovery actually
#     becomes possible (may be None if never recovers).
#   - ``final_outcome``: boolean indicating whether recovery ultimately succeeds.

def oracle_optimal_temporal_decision(
    context: DecisionContext,
    hidden_future: dict,
    economic_action,  # type: ignore – same enum as in economic layer
    economic_probability: float,
) -> Tuple[TemporalDecision, float]:
    """Compute the optimal temporal decision using hidden truth.

    Returns a tuple ``(best_temporal, best_ev)`` where ``best_ev`` is the true
    expected monetary value (including any delay/wait costs) based on the hidden
    recovery time.
    """
    # Build the deterministic model with *true* recovery probability derived
    # from hidden outcome. If hidden indicates guaranteed recovery after a certain
    # wait, we treat the probability as 1.0 after that wait; otherwise it stays at
    # the base economic probability.
    base_prob = economic_probability
    true_prob = 1.0 if hidden_future.get("final_outcome") else base_prob

    model = TemporalValueModel(
        amount_at_risk=context.amount,
        base_recovery_probability=true_prob,
        delay_cost_per_interval=0.01,
        waiting_cost_per_interval=0.005,
    )

    # Evaluate all decisions similarly to the production wrapper.
    best_ev = -float("inf")
    best_td = TemporalDecision.STOP_RECOVERY

    # Non‑WAIT decisions
    for td in [TemporalDecision.ACT_NOW, TemporalDecision.RETRY_LATER, TemporalDecision.NUDGE, TemporalDecision.STOP_RECOVERY]:
        ev = model.expected_value(td)
        if ev > best_ev:
            best_ev = ev
            best_td = td

    # WAIT – we can look at the hidden ``recovery_time_minutes`` to know the exact
    # moment when recovery becomes possible. Compute the number of discrete steps
    # required (capped by MAX_WAIT_STEPS).
    rec_min = hidden_future.get("recovery_time_minutes")
    if rec_min is not None:
        steps_needed = min(
            model.max_wait_steps,
            max(1, int(rec_min // model.max_wait_steps * model.max_wait_steps))
        )
        # In practice we simply evaluate all allowed steps and pick the best.
        for steps in range(1, model.max_wait_steps + 1):
            ev = model.expected_value(TemporalDecision.WAIT, wait_steps=steps)
            if ev > best_ev:
                best_ev = ev
                best_td = TemporalDecision.WAIT
    return best_td, best_ev
