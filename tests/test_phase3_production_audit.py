import pytest
from app.domain.schemas import DecisionContext
from app.domain.decision import RecoveryAction
from app.domain.recovery_case import RecoveryDomain
from app.domain.classification import FailureCategory, Retryability, Recoverability
from app.services.economic_optimizer import EconomicOptimizer
from app.services.candidate_generator import CandidateGenerator
from app.services.probability_provider import ProbabilityProvider
from app.services.temporal_layer import evaluate_temporal_decision, TemporalDecision, TemporalValueModel, MAX_WAIT_STEPS


def build_context(state_name: str = "DEGRADED", amount: float = 1000.0):
    """Create a minimal valid DecisionContext with a given route health state."""
    return DecisionContext(
        case_id="test-case",
        tenant_id="tenant-1",
        domain=RecoveryDomain.B2C,
        amount=amount,
        currency="INR",
        failure_category=FailureCategory.UNKNOWN,
        retryability=Retryability.LATER_RETRY_POSSIBLE,
        recoverability=Recoverability.MEDIUM,
        baseline_action=None,
        historical_cases=[],
        playbook_snippets=[],
        route_health={"state": state_name},
    )


def get_economic_action(context: DecisionContext):
    """Run the Economic optimizer to obtain the baseline action and probability."""
    candidates = CandidateGenerator.generate_candidates(context=context, ai_proposal=None)
    ranked = EconomicOptimizer.rank_candidates(
        candidates=candidates,
        context=context,
        probability_provider=ProbabilityProvider,
    )
    for cand in ranked:
        # Assume the first ranked candidate is policy‑approved for the test
        return cand["action"], cand["recovery_probability"]
    raise AssertionError("No candidates returned")


def test_t0_uses_frozen_economic_optimizer():
    ctx = build_context()
    action, prob = get_economic_action(ctx)
    # Verify that the returned action is a valid RecoveryAction enum
    assert isinstance(action, RecoveryAction)
    assert 0.0 <= prob <= 1.0


def test_t1_and_t2_invoke_temporal_layer_and_wait_enumeration():
    ctx = build_context(state_name="DEGRADED", amount=2000.0)
    econ_action, econ_prob = get_economic_action(ctx)

    # T1 – zero wait/delay costs, should consider WAIT candidates
    act_t1, temporal_t1 = evaluate_temporal_decision(
        context=ctx,
        economic_action=econ_action,
        economic_probability=econ_prob,
        delay_cost_per_interval=0.0,
        waiting_cost_per_interval=0.0,
    )
    assert isinstance(temporal_t1, TemporalDecision)
    # In this synthetic scenario the best decision is WAIT because the transition
    # matrix improves the recovery probability over time.
    assert temporal_t1 == TemporalDecision.WAIT
    assert isinstance(act_t1, RecoveryAction)

    # T2 – default wait economics (non‑zero costs). The same scenario may still select WAIT,
    # but we verify that the explicit wait costs reduce the expected value compared to T1.
    act_t2, temporal_t2 = evaluate_temporal_decision(
        context=ctx,
        economic_action=econ_action,
        economic_probability=econ_prob,
    )
    assert isinstance(temporal_t2, TemporalDecision)
    # Compute EVs for WAIT decision under both cost settings using the internal model.
    model_zero = TemporalValueModel(
        amount_at_risk=ctx.amount,
        base_recovery_probability=econ_prob,
        delay_cost_per_interval=0.0,
        waiting_cost_per_interval=0.0,
    )
    ev_wait_zero = model_zero.expected_value(TemporalDecision.WAIT, wait_steps=MAX_WAIT_STEPS)
    model_default = TemporalValueModel(
        amount_at_risk=ctx.amount,
        base_recovery_probability=econ_prob,
        delay_cost_per_interval=0.01,
        waiting_cost_per_interval=0.005,
    )
    ev_wait_default = model_default.expected_value(TemporalDecision.WAIT, wait_steps=MAX_WAIT_STEPS)
    assert ev_wait_default < ev_wait_zero
    assert isinstance(act_t2, RecoveryAction)


def test_t2_wait_cost_reduces_ev_relative_to_t1():
    ctx = build_context(state_name="DEGRADED", amount=1500.0)
    econ_action, econ_prob = get_economic_action(ctx)

    # Evaluate with zero costs (T1)
    _, temporal_t1 = evaluate_temporal_decision(
        context=ctx,
        economic_action=econ_action,
        economic_probability=econ_prob,
        delay_cost_per_interval=0.0,
        waiting_cost_per_interval=0.0,
    )
    # Evaluate with default costs (T2)
    _, temporal_t2 = evaluate_temporal_decision(
        context=ctx,
        economic_action=econ_action,
        economic_probability=econ_prob,
    )

    # Compute EVs for WAIT decision under both cost settings using the internal model.
    model_zero = TemporalValueModel(
        amount_at_risk=ctx.amount,
        base_recovery_probability=econ_prob,
        delay_cost_per_interval=0.0,
        waiting_cost_per_interval=0.0,
    )
    ev_wait_zero = model_zero.expected_value(TemporalDecision.WAIT, wait_steps=MAX_WAIT_STEPS)
    model_default = TemporalValueModel(
        amount_at_risk=ctx.amount,
        base_recovery_probability=econ_prob,
        delay_cost_per_interval=0.01,
        waiting_cost_per_interval=0.005,
    )
    ev_wait_default = model_default.expected_value(TemporalDecision.WAIT, wait_steps=MAX_WAIT_STEPS)
    assert ev_wait_default < ev_wait_zero
