#!/usr/bin/env python3
"""Temporal transition module.

Provides the frozen deterministic finite‑state transition matrix and base recovery
probabilities used by the Phase 3 temporal decision layer. This module simply
exposes the data defined in ``temporal_state.py`` under the names expected by
the decision layer:

- ``ObservableState`` – enum of observable system states.
- ``TRANSITION_MATRIX`` – dict mapping a source ``ObservableState`` to a dict of
  destination ``ObservableState`` probabilities for a single 30‑minute interval.
- ``STATE_BASE_RECOVERY_PROB`` – base recovery probability for each observable
  state (simulation assumptions).
"""

from .temporal_state import (
    ObservableState,
    state_transition_probabilities,
    STATE_BASE_RECOVERY_PROB,
)

# Alias with the name used by the temporal_layer implementation.
TRANSITION_MATRIX = state_transition_probabilities
