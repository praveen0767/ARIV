#!/usr/bin/env python3
"""tests/test_phase3_temporal.py

Unit tests validating the deterministic temporal model and separation of concerns.
"""

import pytest

from app.services.temporal_value_model import TemporalValueModel
from app.services.temporal_layer import (
    EVALUATION_INTERVAL_MINUTES,
    MAX_WAIT_DURATION_MINUTES,
    MAX_WAIT_STEPS,
    evaluate_temporal_decision,
    TemporalDecision,
)
from app.services.temporal_oracle import oracle_optimal_temporal_decision
from app.domain.decision import RecoveryAction
from app.domain.schemas import DecisionContext
from app.domain.recovery_case import RecoveryDomain
from app.domain.classification import FailureCategory


def make_context(amount: float = 100.0, operational_cost: float = 0.0):
    return DecisionContext(
        case_id="case123",
        tenant_id="tenant123",
        domain=RecoveryDomain.B2C,
        currency="USD",
        amount=amount,
        failure_category=FailureCategory.UNKNOWN,
        route_health={"state": "DEGRADED"},
        operational_cost=operational_cost,
    )


def test_no_probability_uplift():
    model = TemporalValueModel(
        amount_at_risk=100.0,
        base_recovery_probability=0.25,
        delay_cost_per_interval=0.0,
        waiting_cost_per_interval=0.0,
    )
    ev0 = model.expected_value_for_wait(0)
    ev1 = model.expected_value_for_wait(1)
    assert ev0 == ev1


def test_wait_cost_applied():
    model = TemporalValueModel(
        amount_at_risk=100.0,
        base_recovery_probability=0.25,
        delay_cost_per_interval=0.01,
        waiting_cost_per_interval=0.005,
    )
    ev0 = model.expected_value_for_wait(0)
    ev1 = model.expected_value_for_wait(1)
    expected_cost = (0.01 + 0.005) * EVALUATION_INTERVAL_MINUTES
    assert ev1 == pytest.approx(ev0 - expected_cost)


def test_wait_bounds_constants():
    assert EVALUATION_INTERVAL_MINUTES == 30
    assert MAX_WAIT_DURATION_MINUTES == 120
    assert MAX_WAIT_STEPS == 4


def test_oracle_uses_hidden_future():
    context = make_context()
    hidden = {"final_outcome": True}
    best_td, best_ev = oracle_optimal_temporal_decision(
        context,
        hidden_future=hidden,
        economic_action=RecoveryAction.RETRY_LATER,
        economic_probability=0.2,
    )
    assert best_td == TemporalDecision.ACT_NOW
    assert best_ev > 0


def test_evaluate_temporal_decision_wrapper():
    context = make_context(operational_cost=0.01)
    action, td = evaluate_temporal_decision(
        context=context,
        economic_action=RecoveryAction.RETRY_LATER,
        economic_probability=0.2,
        delay_cost_per_interval=0.01,
        waiting_cost_per_interval=0.005,
    )
    assert isinstance(action, RecoveryAction)
    assert isinstance(td, TemporalDecision)
