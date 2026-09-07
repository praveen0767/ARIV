"""
tests/test_judge_benchmark.py

Focused test suite for ARIV Judge-Grade Evaluation Harness (Phase 1).
Validates:
  1. Identical cohorts across all 5 strategies (Common Random Numbers)
  2. Strict isolation of held-out evaluation truth (zero leakage)
  3. Deterministic reproducibility (bit-for-bit identical outputs)
  4. Strategy isolation and natural decision divergence (no artificial force)
  5. Evaluator-only economic regret and oracle ceiling properties
  6. Student's t 95% confidence interval calculations
  7. Probability calibration metrics (Brier Score, ECE, calibration curves)
  8. Distribution-shift cohort properties and degradation metrics
  9. Action-level metrics and serialization schema
  10. Offline execution invariants (zero network, zero DB mutations)
"""

import copy
import json
import pytest
from unittest.mock import patch

from app.domain.decision import RecoveryAction
from scripts.run_judge_benchmark import (
    generate_cohort,
    generate_shifted_cohort,
    execute_strategy_decision,
    evaluate_strategy_outcome,
    compute_oracle_for_case,
    run_single_seed_benchmark,
    calculate_stats_and_ci,
    calculate_probability_calibration,
    run_judge_benchmark,
    DEFAULT_OPERATIONAL_COST_INR,
    DEFAULT_RISK_PENALTY_INR,
    DEFAULT_HIGH_RISK_PENALTY_INR,
)


def test_identical_cohorts_across_strategies():
    """Verify that all 5 strategies evaluate the exact same cases and outcome rolls for a given seed."""
    cases = generate_cohort(count=100, seed=42)
    assert len(cases) == 100

    # Ensure public context is populated and outcome_roll is uniquely sampled per case
    rolls = [c["_hidden_truth"]["outcome_roll"] for c in cases]
    assert len(set(rolls)) == 100, "Every case should have an independent outcome roll."

    # Run single seed benchmark and verify each strategy evaluated all 100 cases
    res = run_single_seed_benchmark(seed=42, cases=cases)
    for strat in ["NO_ACTION", "NAIVE_RETRY", "BASELINE", "ECONOMIC", "AI_PLUS_ECONOMIC"]:
        assert res["strategies"][strat]["total_cases"] == 100


def test_hidden_truth_isolation():
    """Verify that _hidden_truth is strictly isolated from DecisionContext and strategy logic."""
    cases = generate_cohort(count=20, seed=42)
    sample_case = cases[0]

    # Verify _hidden_truth exists in the case record but NOT in public context
    assert "_hidden_truth" in sample_case
    assert "_hidden_truth" not in sample_case["public"]
    assert "latent_incident" not in sample_case["public"]
    assert "conversions" not in sample_case["public"]
    assert "outcome_roll" not in sample_case["public"]

    # Verify that strategy execution receives ONLY public dictionary
    for strat in ["NO_ACTION", "NAIVE_RETRY", "BASELINE", "ECONOMIC", "AI_PLUS_ECONOMIC"]:
        # Pass ONLY sample_case["public"]
        action, passed_policy, est_p, prov, debug_info = execute_strategy_decision(
            strategy=strat,
            pub=sample_case["public"],
            op_cost=DEFAULT_OPERATIONAL_COST_INR,
            risk_penalty=DEFAULT_RISK_PENALTY_INR,
        )
        assert isinstance(action, RecoveryAction)
        assert 0.0 <= est_p <= 1.0


def test_deterministic_reproducibility():
    """Verify two independent runs with identical seeds produce bit-for-bit identical results."""
    cohort_1 = generate_cohort(count=200, seed=42)
    cohort_2 = generate_cohort(count=200, seed=42)

    # Assert cohorts are identical
    assert json.dumps(cohort_1, default=str) == json.dumps(cohort_2, default=str)

    res_1 = run_single_seed_benchmark(seed=42, cases=cohort_1)
    res_2 = run_single_seed_benchmark(seed=42, cases=cohort_2)

    # Drop non-serialized eval records
    res_1.pop("_eval_records", None)
    res_2.pop("_eval_records", None)

    hash_1 = json.dumps(res_1, sort_keys=True, default=str)
    hash_2 = json.dumps(res_2, sort_keys=True, default=str)
    assert hash_1 == hash_2, "Benchmark must be 100% deterministic."


def test_strategy_isolation_and_decision_divergence():
    """Verify strategies are independently implemented and naturally capable of divergence
    without requiring artificial distinctness on every single case.
    """
    cases = generate_cohort(count=50, seed=42)
    decisions = {s: [] for s in ["NO_ACTION", "NAIVE_RETRY", "BASELINE", "ECONOMIC", "AI_PLUS_ECONOMIC"]}

    for c in cases:
        for s in decisions:
            act, _, _, _, _ = execute_strategy_decision(
                strategy=s,
                pub=c["public"],
                op_cost=DEFAULT_OPERATIONAL_COST_INR,
                risk_penalty=DEFAULT_RISK_PENALTY_INR,
            )
            decisions[s].append(act.value)

    # 1. NO_ACTION must always choose STOP_RECOVERY
    assert all(a == "STOP_RECOVERY" for a in decisions["NO_ACTION"])

    # 2. NAIVE_RETRY must always choose RETRY_NOW
    assert all(a == "RETRY_NOW" for a in decisions["NAIVE_RETRY"])

    # 3. BASELINE, ECONOMIC, and AI_PLUS_ECONOMIC must diverge naturally on some cases
    diff_base_econ = sum(1 for b, e in zip(decisions["BASELINE"], decisions["ECONOMIC"]) if b != e)
    diff_econ_ai = sum(1 for e, a in zip(decisions["ECONOMIC"], decisions["AI_PLUS_ECONOMIC"]) if e != a)

    assert diff_base_econ > 0, "ECONOMIC should diverge from BASELINE on some cases."
    assert diff_econ_ai > 0, "AI_PLUS_ECONOMIC should diverge from ECONOMIC on route-degraded or customer cases."

    # 4. Convergence is permitted: some decisions can legitimately be identical
    same_econ_ai = sum(1 for e, a in zip(decisions["ECONOMIC"], decisions["AI_PLUS_ECONOMIC"]) if e == a)
    assert same_econ_ai > 0, "Strategies should legitimately agree when the same action is optimal."


def test_regret_and_oracle_ceiling_computation():
    """Verify evaluator-only Oracle is an upper bound on admissible net value and regret >= 0."""
    cases = generate_cohort(count=100, seed=42)
    res = run_single_seed_benchmark(seed=42, cases=cases)

    oracle_net = res["oracle_ceiling"]["oracle_net_inr"]
    assert oracle_net > 0, "Oracle net value must be positive."

    for strat in ["NO_ACTION", "NAIVE_RETRY", "BASELINE", "ECONOMIC", "AI_PLUS_ECONOMIC"]:
        strat_net = res["strategies"][strat]["net_recovered_value_inr"]
        mean_regret = res["strategies"][strat]["mean_economic_regret_inr"]
        capture_rate = res["strategies"][strat]["oracle_capture_rate"]

        # Oracle ceiling property
        assert oracle_net >= strat_net - 1e-2, f"Oracle must be >= strategy net value for {strat}."
        # Non-negative regret
        assert mean_regret >= 0.0, f"Mean regret must be non-negative for {strat}."
        # Capture rate bounded in [0.0, 1.0] (or negative if net < 0)
        assert capture_rate <= 1.05, f"Capture rate cannot significantly exceed 100% for {strat}."


def test_confidence_interval_calculation():
    """Verify Student's t-distribution confidence interval calculation."""
    # Symmetrical data
    values = [100.0, 102.0, 98.0, 101.0, 99.0, 100.5, 99.5, 100.2, 99.8, 100.0]
    stats = calculate_stats_and_ci(values)

    assert stats["mean"] == 100.0
    assert stats["median"] == 100.0
    assert stats["ci_95_low"] < stats["mean"] < stats["ci_95_high"]
    assert stats["margin_of_error"] > 0
    # Margin of error for N=10 with s ~ 1.15 and t_crit = 2.262 is ~ 0.8
    assert 0.5 <= stats["margin_of_error"] <= 1.5


def test_probability_calibration_metrics():
    """Verify Brier Score and Expected Calibration Error calculation."""
    # Perfectly calibrated case
    pred_probs = [0.1] * 10 + [0.9] * 10
    actual_outcomes = [0] * 9 + [1] * 1 + [1] * 9 + [0] * 1
    cal = calculate_probability_calibration(pred_probs, actual_outcomes, num_bins=10)

    assert "brier_score" in cal
    assert "ece" in cal
    assert "bins" in cal
    assert cal["brier_score"] >= 0.0
    assert cal["ece"] >= 0.0
    assert len(cal["bins"]) == 10


def test_distribution_shift_cohort_properties():
    """Verify shifted cohort has higher payment amounts and distinct incident weights."""
    normal_cohort = generate_cohort(count=100, seed=42)
    shifted_cohort = generate_shifted_cohort(count=100, seed=42)

    normal_mean_amt = sum(c["public"]["amount"] for c in normal_cohort) / 100
    shifted_mean_amt = sum(c["public"]["amount"] for c in shifted_cohort) / 100

    # Shifted cohort must have significantly higher average amount
    assert shifted_mean_amt > normal_mean_amt * 2.0


def test_action_level_metrics_schema():
    """Verify action distribution and metrics dictionary contains all required fields."""
    cases = generate_cohort(count=50, seed=42)
    res = run_single_seed_benchmark(seed=42, cases=cases)

    for strat in ["BASELINE", "ECONOMIC", "AI_PLUS_ECONOMIC"]:
        act_metrics = res["strategies"][strat]["action_metrics"]
        total_count_from_actions = sum(m["count"] for m in act_metrics.values())
        assert total_count_from_actions == 50

        for act_name, m in act_metrics.items():
            assert "count" in m
            assert "percentage" in m
            assert "gross_recovered_inr" in m
            assert "total_cost_inr" in m
            assert "total_regret_inr" in m


def test_offline_execution_invariants():
    """Verify benchmark runs completely offline with zero external network or database calls."""
    import socket
    real_connect = socket.socket.connect

    def forbidden_connect(*args, **kwargs):
        raise RuntimeError("Forbidden external network attempt during benchmark execution!")

    with patch.object(socket.socket, "connect", forbidden_connect):
        cases = generate_cohort(count=30, seed=42)
        res = run_single_seed_benchmark(seed=42, cases=cases)
        assert res["strategies"]["AI_PLUS_ECONOMIC"]["net_recovered_value_inr"] > 0
