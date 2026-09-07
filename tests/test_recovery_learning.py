"""
tests/test_recovery_learning.py

Phase 3: Dirichlet-smoothed, corridor-aware, provider-confirmed recovery learning.

Proves the learner fixes RC-2a and RC-2b:
- probability is NEVER 0 (no p(STOP) collapse)
- minimum support required before experience overrides the prior
- memory is partitioned by corridor (no cross-corridor bleed)
- STOP_RECOVERY is frozen at the prior and never trained from its own failures
- only provider-confirmed terminal outcomes are learned
- at the economic layer, a hard-fraud NON_RETRIABLE case ranks STOP above the
  "flipped" futile GPL because STOP keeps its prior while GPL is smoothed down
"""

import pytest

from app.domain.schemas import DecisionContext
from app.domain.decision import RecoveryAction
from app.domain.recovery_case import RecoveryDomain
from app.domain.classification import FailureCategory, Retryability, Recoverability
from app.services.recovery_learning import RecoveryLearningService
from app.services.economic_optimizer import EconomicOptimizer


BETA = 4.0
PRIOR = 0.6
MIN_SUPPORT = 5


def make_learner(**kw):
    kwargs = {"beta": BETA, "min_support": MIN_SUPPORT, "prior": PRIOR}
    kwargs.update(kw)
    return RecoveryLearningService(**kwargs)


def make_context(domain=RecoveryDomain.B2C,
                 category=FailureCategory.TRANSIENT_TECHNICAL,
                 corridor="razorpay:card:b2c",
                 baseline=RecoveryAction.RETRY_LATER,
                 amount=2000.0):
    return DecisionContext(
        case_id="case-learn",
        tenant_id="tenant-1",
        domain=domain,
        amount=amount,
        currency="INR",
        failure_category=category,
        retryability=Retryability.LATER_RETRY_POSSIBLE,
        recoverability=Recoverability.HIGH,
        baseline_action=baseline,
        route_health={"status": "OPERATIONAL", "corridor": corridor},
    )


def test_provider_confirmed_outputs_only():
    """Provisional / speculative outcomes never touch the memory store."""
    learner = make_learner()
    ctx = make_context()
    for status in ["PENDING", "IN_PROGRESS", "PROPOSED", "QUEUED", "RETRYING", "PROCESSING"]:
        assert learner.record_outcome(RecoveryDomain.B2C, ctx.failure_category, "razorpay:card:b2c",
                                      RecoveryAction.GENERATE_PAYMENT_LINK, status) is False
    assert learner.estimate(RecoveryAction.GENERATE_PAYMENT_LINK, ctx) == (PRIOR, ["deterministic_prior"])


def test_minimum_support_keeps_prior():
    """Fewer than min_support confirmed attempts cannot override the prior."""
    learner = make_learner()
    ctx = make_context()
    for _ in range(MIN_SUPPORT - 1):
        learner.record_outcome(RecoveryDomain.B2C, ctx.failure_category, "razorpay:card:b2c",
                               RecoveryAction.RETRY_LATER, "RECOVERED")
    prob, prov = learner.estimate(RecoveryAction.RETRY_LATER, ctx)
    assert prob == pytest.approx(PRIOR)
    assert prov == ["deterministic_prior"]


def test_smoothing_matches_formula_at_min_support():
    """p(successes=5, n=5) = (5 + beta*prior)/(5 + beta)."""
    learner = make_learner()
    ctx = make_context()
    for _ in range(5):
        learner.record_outcome(RecoveryDomain.B2C, ctx.failure_category, "razorpay:card:b2c",
                               RecoveryAction.RETRY_LATER, "RECOVERED")
    prob, prov = learner.estimate(RecoveryAction.RETRY_LATER, ctx)
    expected = (5 + BETA * PRIOR) / (5 + BETA)
    assert prob == pytest.approx(expected)
    assert prov == ["empirical_history_smoothed"]


def test_probability_never_zero_even_for_total_failure():
    """A run of total failures cannot collapse the probability to 0 (RC-2b guard)."""
    learner = make_learner()
    ctx = make_context()
    for _ in range(200):
        learner.record_outcome(RecoveryDomain.B2C, ctx.failure_category, "razorpay:card:b2c",
                               RecoveryAction.GENERATE_PAYMENT_LINK, "FAILED")
    prob, _ = learner.estimate(RecoveryAction.GENERATE_PAYMENT_LINK, ctx)
    assert prob > 0.0
    # bounded away from 0 by the Dirichlet prior share
    assert prob >= (BETA * PRIOR) / (200 + BETA) - 1e-12


def test_stop_never_trained_and_stays_at_prior():
    """STOP never learns from its own 'FAILED' outcomes (survivorship edge)."""
    learner = make_learner()
    ctx = make_context(baseline=RecoveryAction.STOP_RECOVERY)
    for _ in range(100):
        assert learner.record_outcome(RecoveryDomain.B2C, ctx.failure_category, "razorpay:card:b2c",
                                      RecoveryAction.STOP_RECOVERY, "FAILED") is False
    prob, prov = learner.estimate(RecoveryAction.STOP_RECOVERY, ctx)
    assert prob == pytest.approx(PRIOR)
    assert prov == ["deterministic_prior"]


def test_corridor_aware_memory_partitioning():
    """Precedents on one corridor never inflate another corridor's probability (RC-2a)."""
    learner = make_learner()
    healthy = "razorpay:card:b2c"
    degraded = "razorpay:upi:b2c"

    ctx_healthy = make_context(corridor=healthy)
    ctx_degraded = make_context(corridor=degraded)

    for _ in range(20):
        learner.record_outcome(RecoveryDomain.B2C, ctx_healthy.failure_category, healthy,
                               RecoveryAction.RETRY_LATER, "RECOVERED")

    # healthy corridor learned
    ph, _ = learner.estimate(RecoveryAction.RETRY_LATER, ctx_healthy)
    assert ph > PRIOR + 0.1
    # degraded corridor sees no precedent -> prior
    pd, prov = learner.estimate(RecoveryAction.RETRY_LATER, ctx_degraded)
    assert pd == pytest.approx(PRIOR)
    assert prov == ["deterministic_prior"]


def test_rc2b_hard_fraud_stop_outranks_flipped_gpl():
    """Economic regression: on NON_RETRIABLE hard-fraud, the learner stops GPL's rank.

    With frozen-memory unsmoothed p(STOP)=0, GPL (prior 0.6) outranked STOP and
    every fraud block flipped to a futile payment link. With the learner, STOP
    keeps its prior and GPL is smoothed down, so STOP beats GPL economically.
    """
    learner = make_learner()
    corridor = "razorpay:fraud:b2c"
    ctx = make_context(category=FailureCategory.NON_RETRIABLE,
                      baseline=RecoveryAction.STOP_RECOVERY,
                      corridor=corridor)

    # Observed provider truth on this corridor: 20 blocked/GPL-failed attempts.
    for _ in range(20):
        learner.record_outcome(RecoveryDomain.B2C, ctx.failure_category, corridor,
                               RecoveryAction.GENERATE_PAYMENT_LINK, "FAILED")

    p_stop, prov_stop = learner.estimate(RecoveryAction.STOP_RECOVERY, ctx)
    p_gpl, prov_gpl = learner.estimate(RecoveryAction.GENERATE_PAYMENT_LINK, ctx)
    assert prov_stop == ["deterministic_prior"]
    assert prov_gpl == ["empirical_history_smoothed"]
    assert p_stop == pytest.approx(PRIOR)
    assert p_gpl < p_stop

    ranked = EconomicOptimizer.rank_candidates(
        candidates=[
            RecoveryAction.GENERATE_PAYMENT_LINK,
            RecoveryAction.STOP_RECOVERY,
            RecoveryAction.RETRY_NOW,
        ],
        context=ctx,
        probability_provider=learner,
    )
    # STOP must rank above the futile GPL
    assert ranked[0]["action"] in (RecoveryAction.STOP_RECOVERY,)
    stop_rank = [i for i, c in enumerate(ranked) if c["action"] == RecoveryAction.STOP_RECOVERY][0]
    gpl_rank = [i for i, c in enumerate(ranked) if c["action"] == RecoveryAction.GENERATE_PAYMENT_LINK][0]
    assert stop_rank < gpl_rank


def test_reset_and_isolation():
    learner_a = make_learner()
    learner_b = make_learner()
    ctx = make_context()
    for _ in range(MIN_SUPPORT):
        learner_a.record_outcome(RecoveryDomain.B2C, ctx.failure_category, "razorpay:card:b2c",
                                 RecoveryAction.RETRY_LATER, "RECOVERED")
    learner_b.record_outcome(RecoveryDomain.B2C, ctx.failure_category, "razorpay:card:b2c",
                             RecoveryAction.RETRY_LATER, "RECOVERED")
    # separate instances are isolated (b: under min support -> prior)
    assert learner_a.estimate(RecoveryAction.RETRY_LATER, ctx)[0] > PRIOR
    assert learner_b.estimate(RecoveryAction.RETRY_LATER, ctx)[0] == pytest.approx(PRIOR)
    # reset clears
    learner_a.reset()
    assert learner_a.estimate(RecoveryAction.RETRY_LATER, ctx)[0] == pytest.approx(PRIOR)


def test_context_without_corridor_keeps_its_own_bucket():
    """Cases with no corridor context do not accidentally read corridor memory."""
    learner = make_learner()
    ctx_no_route = make_context()
    ctx_no_route2 = DecisionContext(
        case_id="no-route", tenant_id="t", domain=ctx_no_route.domain,
        amount=ctx_no_route.amount, currency="INR",
        failure_category=ctx_no_route.failure_category,
        retryability=ctx_no_route.retryability, recoverability=ctx_no_route.recoverability,
        baseline_action=ctx_no_route.baseline_action, route_health=None,
    )
    for _ in range(MIN_SUPPORT + 1):
        learner.record_outcome(RecoveryDomain.B2C, ctx_no_route.failure_category, None,
                               RecoveryAction.SEND_REMINDER, "RECOVERED")
    # corridor-pathed request sees prior; no-route request sees learned value
    assert learner.estimate(RecoveryAction.SEND_REMINDER, ctx_no_route)[0] == pytest.approx(PRIOR)
    assert learner.estimate(RecoveryAction.SEND_REMINDER, ctx_no_route2)[0] > PRIOR