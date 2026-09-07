"""
tests/test_wait_ev.py

Phase 4: finite-horizon WAIT expected-value model.

Proves WAIT can now win on economics (not ordering) where the corridor is
recovering, and never wastes money where it is not:

- HEALTHY corridor: waiting never helps (zero uplift) -> act now.
- DEGRADED high-value: waiting accrues option value -> WAIT beats ACT_NOW.
- LOW amount: waiting costs dominate -> act now.
- probability uplift is bounded (cannot manufacture certainty).
- environment readiness is monotone along the frozen transition process.
- public-input helper works end-to-end against a DecisionContext.
"""

import pytest

from app.domain.schemas import DecisionContext
from app.domain.decision import RecoveryAction
from app.domain.recovery_case import RecoveryDomain
from app.domain.classification import FailureCategory, Retryability, Recoverability
from app.services.temporal_state import ObservableState
from app.services.wait_ev import WaitDecisionModel, evaluate_wait_recommendation
from app.services.temporal_config import MAX_WAIT_STEPS


def make_context(corridor_state="HEALTHY", amount=100000.0, route_status=None):
    return DecisionContext(
        case_id="case-wait",
        tenant_id="tenant-1",
        domain=RecoveryDomain.B2C,
        amount=amount,
        currency="INR",
        failure_category=FailureCategory.TRANSIENT_TECHNICAL,
        retryability=Retryability.LATER_RETRY_POSSIBLE,
        recoverability=Recoverability.HIGH,
        baseline_action=RecoveryAction.RETRY_LATER,
        route_health={"state": corridor_state, "corridor": "razorpay:card:b2c"},
    )


def test_healthy_corridor_never_waits():
    """Waiting on a healthy corridor yields zero probability uplift -> act now."""
    model = WaitDecisionModel(
        amount_at_risk=100000.0,
        base_recovery_probability=0.5,
        current_state=ObservableState.HEALTHY,
    )
    steps, _ = model.optimal()
    assert steps == 0
    assert model.should_wait() is False
    # uplift is exactly zero for every horizon step
    for k in range(1, MAX_WAIT_STEPS + 1):
        assert model.recovery_probability_after_wait(k) == pytest.approx(0.5)
        assert model.wait_ev(k) < model.act_now_ev()


def test_degraded_high_value_waits():
    """On a resolving degraded corridor with high value, WAIT beats ACT_NOW."""
    model = WaitDecisionModel(
        amount_at_risk=100000.0,
        base_recovery_probability=0.5,
        current_state=ObservableState.DEGRADED,
    )
    steps, ev = model.optimal()
    assert steps > 0
    assert ev > model.act_now_ev()
    assert model.should_wait() is True
    # waiting cannot manufacture certainty
    for k in range(1, MAX_WAIT_STEPS + 1):
        p = model.recovery_probability_after_wait(k)
        assert 0.0 <= p <= 1.0
        assert p >= 0.5


def test_low_amount_costs_dominate_no_wait():
    """On a small balance the waiting costs dominate -> act now."""
    model = WaitDecisionModel(
        amount_at_risk=10.0,
        base_recovery_probability=0.5,
        current_state=ObservableState.DEGRADED,
    )
    steps, _ = model.optimal()
    assert steps == 0
    assert model.should_wait() is False


def test_critical_state_waits_for_recovery():
    """Critical corridors trend back and WAIT is worthwhile at high value."""
    model = WaitDecisionModel(
        amount_at_risk=100000.0,
        base_recovery_probability=0.2,
        current_state=ObservableState.CRITICAL,
    )
    steps, ev = model.optimal()
    assert steps > 0
    assert ev > model.act_now_ev()


def test_environment_readiness_is_monotone_from_degraded():
    """env(0) <= env(1) <= ... for degraded/critical starting states."""
    for state in (ObservableState.DEGRADED, ObservableState.CRITICAL):
        model = WaitDecisionModel(amount_at_risk=1.0, base_recovery_probability=0.1,
                                  current_state=state)
        envs = [model.env_recovery_probability(k) for k in range(0, MAX_WAIT_STEPS + 1)]
        assert all(b >= a - 1e-12 for a, b in zip(envs, envs[1:]))
        # degraded: single-step transition is deterministic
        if state is ObservableState.DEGRADED:
            assert envs[0] == pytest.approx(0.5)
            assert envs[1] == pytest.approx(0.2 * 0.95 + 0.7 * 0.5 + 0.1 * 0.2)


def test_health_readiness_constant_and_top_threshold():
    model = WaitDecisionModel(amount_at_risk=1.0, base_recovery_probability=0.5,
                              current_state=ObservableState.HEALTHY)
    for k in range(0, MAX_WAIT_STEPS + 1):
        assert model.env_recovery_probability(k) == pytest.approx(0.95)


def test_probability_after_wait_bounded_by_ceiling():
    """Even many waits cannot push probability above the health ceiling logic."""
    model = WaitDecisionModel(
        amount_at_risk=100000.0,
        base_recovery_probability=0.8,
        current_state=ObservableState.CRITICAL,
    )
    for k in range(1, MAX_WAIT_STEPS + 1):
        assert model.recovery_probability_after_wait(k) <= 1.0
        assert model.recovery_probability_after_wait(k) >= 0.8


def test_evaluate_wait_recommendation_public_helper():
    ctx_healthy = make_context(corridor_state="HEALTHY")
    act, wait, steps, ev = evaluate_wait_recommendation(
        ctx_healthy, RecoveryAction.RETRY_LATER, 0.5)
    assert act == RecoveryAction.RETRY_LATER
    assert wait is False
    assert steps == 0

    ctx_degraded = make_context(corridor_state="DEGRADED")
    act, wait, steps, ev = evaluate_wait_recommendation(
        ctx_degraded, RecoveryAction.RETRY_LATER, 0.5)
    assert act == RecoveryAction.RETRY_LATER
    assert wait is True
    assert steps > 0
    assert ev > 0.5 * 100000.0

    # low-value case -> no wait, even when degraded
    ctx_small = make_context(corridor_state="DEGRADED", amount=10.0)
    _, wait_small, steps_small, _ = evaluate_wait_recommendation(
        ctx_small, RecoveryAction.RETRY_LATER, 0.5)
    assert wait_small is False
    assert steps_small == 0


def test_route_health_status_string_maps_to_state():
    """status:DEGRADED or state:DEGRADED both resolve to a degraded corridor."""
    ctx = make_context(corridor_state="DEGRADED")
    ctx2 = DecisionContext(
        case_id="case-wait2", tenant_id="tenant-1", domain=ctx.domain,
        amount=100000.0, currency="INR", failure_category=ctx.failure_category,
        retryability=ctx.retryability, recoverability=ctx.recoverability,
        baseline_action=ctx.baseline_action,
        route_health={"status": "DEGRADED"},
    )
    from app.services.wait_ev import _state_from_route_health
    assert _state_from_route_health(ctx.route_health) == ObservableState.DEGRADED
    assert _state_from_route_health(ctx2.route_health) == ObservableState.DEGRADED
    assert _state_from_route_health(None) == ObservableState.DEGRADED