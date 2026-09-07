"""
tests/test_route_aware_probability.py

Phase 5: corridor / route health is an input to the recovery-probability estimate.

Proves:
- degraded/critical corridors discount online retry actions' probability (ENR),
  while asynchronous/offline actions keep their nominal estimate;
- the wrapper composes with the deterministic provider and the Phase-3 learner;
- values stay in [0, 1] and provenance names the applied discount;
- no route_health -> no discount (upward-compatible).
"""

import pytest

from app.domain.schemas import DecisionContext
from app.domain.decision import RecoveryAction
from app.domain.recovery_case import RecoveryDomain
from app.domain.classification import FailureCategory, Retryability, Recoverability
from app.services.probability_provider import ProbabilityProvider
from app.services.recovery_learning import RecoveryLearningService
from app.services.route_aware_probability import (
    RouteAwareProbabilityProvider,
    route_discount,
    resolve_route_state,
)


def make_context(route_health):
    return DecisionContext(
        case_id="case-route",
        tenant_id="tenant-1",
        domain=RecoveryDomain.B2C,
        amount=5000.0,
        currency="INR",
        failure_category=FailureCategory.TRANSIENT_TECHNICAL,
        retryability=Retryability.LATER_RETRY_POSSIBLE,
        recoverability=Recoverability.HIGH,
        baseline_action=RecoveryAction.RETRY_LATER,
        route_health=route_health,
    )


def test_no_route_health_no_discount():
    """Absent/normal route health leaves the estimate unchanged."""
    provider = RouteAwareProbabilityProvider()
    ctx = make_context(route_health=None)
    prob, prov = provider.estimate(RecoveryAction.RETRY_LATER, ctx)
    base, _ = ProbabilityProvider.estimate(RecoveryAction.RETRY_LATER, ctx)
    assert prob == pytest.approx(base)
    assert prov == ["deterministic_prior"]


def test_operational_route_no_discount():
    ctx = make_context(route_health={"status": "OPERATIONAL", "corridor": "razorpay:card:b2c"})
    provider = RouteAwareProbabilityProvider()
    prob, prov = provider.estimate(RecoveryAction.RETRY_LATER, ctx)
    assert prob == pytest.approx(0.6)
    assert prov == ["deterministic_prior"]


def test_degraded_discounts_retries_only():
    ctx = make_context(route_health={"status": "DEGRADED", "corridor": "razorpay:card:b2c"})
    provider = RouteAwareProbabilityProvider()

    retry_prob, retry_prov = provider.estimate(RecoveryAction.RETRY_LATER, ctx)
    assert retry_prob == pytest.approx(0.6 * 0.55)
    assert "route_health:DEGRADED:x0.55" in retry_prov

    retry_now_prob, _ = provider.estimate(RecoveryAction.RETRY_NOW, ctx)
    assert retry_now_prob == pytest.approx(0.6 * 0.55)

    # asynchronous / offline actions keep nominal probability
    for action in (RecoveryAction.GENERATE_PAYMENT_LINK,
                   RecoveryAction.SEND_REMINDER,
                   RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE,
                   RecoveryAction.STOP_RECOVERY):
        prob, prov = provider.estimate(action, ctx)
        assert prob == pytest.approx(0.6), action
        assert "route_health:DEGRADED" not in prov


def test_critical_discount_stronger_than_degraded():
    degraded = make_context(route_health={"status": "DEGRADED"})
    critical = make_context(route_health={"status": "CRITICAL"})
    provider = RouteAwareProbabilityProvider()
    p_degraded, _ = provider.estimate(RecoveryAction.RETRY_LATER, degraded)
    p_critical, _ = provider.estimate(RecoveryAction.RETRY_LATER, critical)
    assert p_critical < p_degraded < 0.6
    assert p_critical == pytest.approx(0.6 * 0.15)


def test_route_discount_helper():
    ctx = make_context(route_health={"state": "CRITICAL"})
    assert route_discount(ctx.route_health, RecoveryAction.RETRY_LATER) == 0.15
    assert route_discount(ctx.route_health, RecoveryAction.GENERATE_PAYMENT_LINK) == 1.0
    assert route_discount({"status": "HEALTHY"}, RecoveryAction.RETRY_NOW) == 1.0
    assert route_discount("something", RecoveryAction.RETRY_NOW) == 1.0
    assert resolve_route_state({"summary": "Corridor is DEGRADED"}) == "DEGRADED"
    assert resolve_route_state({}) == "OPERATIONAL"


def test_composes_with_recovery_learner():
    """Route discount applies on top of the smoothed learner's estimate."""
    learner = RecoveryLearningService(beta=4.0, min_support=5, prior=0.6)
    ctx = make_context(route_health={"status": "DEGRADED", "corridor": "razorpay:card:b2c"})
    for _ in range(5):
        learner.record_outcome(RecoveryDomain.B2C, ctx.failure_category, "razorpay:card:b2c",
                               RecoveryAction.RETRY_LATER, "RECOVERED")
    inner_prob, _ = learner.estimate(RecoveryAction.RETRY_LATER, ctx)
    assert inner_prob > 0.7  # learner raised above the prior

    provider = RouteAwareProbabilityProvider(inner_provider=learner)
    prob, prov = provider.estimate(RecoveryAction.RETRY_LATER, ctx)
    assert prob == pytest.approx(inner_prob * 0.55)
    assert prov[0] == "empirical_history_smoothed"
    assert "route_health:DEGRADED:x0.55" in prov


def test_route_aware_ranking_beats_retry_on_systemic_outage():
    """On a DEGRADED corridor the economic rank chooses the offline action.

    This is the RC-2a economic fix: without the discount, a retry boosted by
    (corridor-blind) memory could out-rank the route-appropriate GPL.
    """
    from app.services.economic_optimizer import EconomicOptimizer

    ctx = make_context(route_health={"status": "DEGRADED", "corridor": "razorpay:card:b2c"})
    provider = RouteAwareProbabilityProvider()
    ranked = EconomicOptimizer.rank_candidates(
        candidates=[
            RecoveryAction.RETRY_LATER,
            RecoveryAction.GENERATE_PAYMENT_LINK,
            RecoveryAction.STOP_RECOVERY,
        ],
        context=ctx,
        probability_provider=provider,
    )
    gpl_enr = next(c["expected_net_recovery"] for c in ranked
                   if c["action"] == RecoveryAction.GENERATE_PAYMENT_LINK)
    retry_enr = next(c["expected_net_recovery"] for c in ranked
                     if c["action"] == RecoveryAction.RETRY_LATER)
    assert retry_enr < gpl_enr