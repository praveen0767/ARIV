#!/usr/bin/env python3
"""Canonical configuration constants for the deterministic Phase‑3 temporal model.
All temporal services import from this file – no duplication.
"""

# Discrete evaluation interval (minutes)
EVALUATION_INTERVAL = 30
# Alias for backward compatibility / expected name
EVALUATION_INTERVAL_MINUTES = EVALUATION_INTERVAL
# Maximum total wait duration (minutes)
MAX_WAIT_DURATION = 120
# Alias for expected name
MAX_WAIT_DURATION_MINUTES = MAX_WAIT_DURATION
# Maximum number of wait steps (derived from above)
MAX_WAIT_STEPS = 4
# Cost incurred per wait step (operational cost units)
WAIT_COST_PER_STEP = 0.05
