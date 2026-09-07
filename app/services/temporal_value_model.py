#!/usr/bin/env python3
"""temporal_value_model.py

Deterministic expected‑value model used by the temporal decision layer.
All parameters are public; no hidden truth is accessed.
"""

from dataclasses import dataclass
from enum import Enum

# Configuration constants (must match temporal_layer)
EVALUATION_INTERVAL_MINUTES: int = 30
MAX_WAIT_STEPS: int = 4

class TemporalDecision(Enum):
    ACT_NOW = 1
    RETRY_LATER = 2
    WAIT = 3
    NUDGE = 4
    STOP_RECOVERY = 5

@dataclass(frozen=True)
class TemporalValueModel:
    amount_at_risk: float
    base_recovery_probability: float
    delay_cost_per_interval: float = 0.0
    waiting_cost_per_interval: float = 0.0
    max_wait_steps: int = MAX_WAIT_STEPS

    def expected_value_for_wait(self, wait_steps: int) -> float:
        prob = self.base_recovery_probability
        total_delay = self.delay_cost_per_interval * wait_steps * EVALUATION_INTERVAL_MINUTES
        total_wait = self.waiting_cost_per_interval * wait_steps * EVALUATION_INTERVAL_MINUTES
        return self.amount_at_risk * prob - total_delay - total_wait

    def expected_value(self, decision: TemporalDecision, wait_steps: int = 0) -> float:
        if decision == TemporalDecision.ACT_NOW:
            return self.amount_at_risk * self.base_recovery_probability
        if decision == TemporalDecision.RETRY_LATER:
            return self.expected_value_for_wait(1)
        if decision == TemporalDecision.WAIT:
            return self.expected_value_for_wait(wait_steps)
        if decision == TemporalDecision.NUDGE:
            prob = self.base_recovery_probability
            return self.amount_at_risk * prob
        if decision == TemporalDecision.STOP_RECOVERY:
            return 0.0
        raise ValueError(f"Unsupported TemporalDecision: {decision}")
