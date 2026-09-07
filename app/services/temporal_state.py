#!/usr/bin/env python3
"""temporal_state.py

Deterministic finite‑state transition model used by the Phase 3 temporal decision layer.
All probabilities are frozen, documented, and not tuned after evaluation.
"""

from enum import Enum
from typing import Dict

class ObservableState(Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    CUSTOMER_ACTION_PENDING = "CUSTOMER_ACTION_PENDING"
    EXPIRING = "EXPIRING"

# Transition probabilities for a single 30‑minute interval.
# Each source state maps to a dict of destination states with probabilities summing to 1.0.
state_transition_probabilities: Dict[ObservableState, Dict[ObservableState, float]] = {
    ObservableState.HEALTHY: {ObservableState.HEALTHY: 1.0},
    ObservableState.DEGRADED: {
        ObservableState.HEALTHY: 0.2,
        ObservableState.DEGRADED: 0.7,
        ObservableState.CRITICAL: 0.1,
    },
    ObservableState.CRITICAL: {
        ObservableState.HEALTHY: 0.1,
        ObservableState.DEGRADED: 0.3,
        ObservableState.CRITICAL: 0.6,
    },
    ObservableState.CUSTOMER_ACTION_PENDING: {
        ObservableState.CUSTOMER_ACTION_PENDING: 0.8,
        ObservableState.DEGRADED: 0.2,
    },
    ObservableState.EXPIRING: {
        ObservableState.EXPIRING: 0.5,
        ObservableState.CRITICAL: 0.5,
    },
}

# Base recovery probabilities per observable state (simulation assumptions).
STATE_BASE_RECOVERY_PROB = {
    ObservableState.HEALTHY: 0.95,
    ObservableState.DEGRADED: 0.5,
    ObservableState.CRITICAL: 0.2,
    ObservableState.CUSTOMER_ACTION_PENDING: 0.4,
    ObservableState.EXPIRING: 0.3,
}
