"""
tests/test_phase2_ablation.py

Phase 2 AI Ablation & Incremental Intelligence Evaluation Test Suite.
Validates:
  1. A0 does not call AI
  2. A1 does not call AI
  3. A2 calls AI but not memory
  4. A3 calls AI + memory
  5. A4 calls AI + memory + systemic intelligence
  6. No hidden truth reaches AI
  7. No hidden truth reaches memory
  8. Oracle/regret not available before action selection
  9. Same cohort generated across variants
  10. No cross-variant mutable state
  11. Deterministic replay produces identical results
  12. Zero network/API/provider calls
  13. Consistent metric schema across all 5 variants
  14. A0 BASELINE parity with Phase 1 BASELINE (case-by-case identical decisions)
"""

import copy
import json
import pytest
from typing import Dict, Any
from unittest.mock import patch, MagicMock

from app.domain.decision import RecoveryAction
from app.domain.classification import FailureCategory, Retryability, Recoverability
from app.domain.recovery_case import RecoveryDomain
from app.domain.schemas import DecisionContext
from scripts.run_judge_benchmark import (
    generate_cohort,
    compute_oracle_for_case,
    evaluate_strategy_outcome,
    execute_strategy_decision,
    JudgeAIAdapter,
)
from scripts.run_phase2_ablation import (
    execute_ablation_variant_decision,
    get_frozen_public_memory,
    search_public_memory,
    run_phase2_ablation,
    VARIANTS,
)


@pytest.fixture
def sample_case():
    cohort = generate_cohort(count=1, seed=42)
    return cohort[0]


def test_1_2_a0_a1_do_not_call_ai(sample_case):
    """Verify A0 (BASELINE) and A1 (ECONOMIC) never invoke AI proposal generation."""
    pub = sample_case["public"]

    with patch.object(JudgeAIAdapter, "generate_decision", wraps=JudgeAIAdapter.generate_decision) as spy_ai:
        # A0
        action_a0, _, _, _, _ = execute_ablation_variant_decision("A0_BASELINE", pub, op_cost=10.0, risk_penalty=5.0)
        assert spy_ai.call_count == 0

        # A1
        action_a1, _, _, _, _ = execute_ablation_variant_decision("A1_ECONOMIC", pub, op_cost=10.0, risk_penalty=5.0)
        assert spy_ai.call_count == 0


def test_3_a2_calls_ai_not_memory(sample_case):
    """Verify A2 (AI_ECONOMIC) invokes AI but does not retrieve memory."""
    pub = sample_case["public"]

    with patch.object(JudgeAIAdapter, "generate_decision", wraps=JudgeAIAdapter.generate_decision) as spy_ai, \
         patch("scripts.run_phase2_ablation.search_public_memory", wraps=search_public_memory) as spy_mem:
        
        action, _, _, _, debug = execute_ablation_variant_decision("A2_AI_ECONOMIC", pub, op_cost=10.0, risk_penalty=5.0)
        
        assert spy_ai.call_count == 1
        assert spy_mem.call_count == 0


def test_4_a3_calls_ai_and_memory(sample_case):
    """Verify A3 (AI_ECONOMIC_MEMORY) invokes both AI and memory retrieval."""
    pub = sample_case["public"]

    with patch.object(JudgeAIAdapter, "generate_decision", wraps=JudgeAIAdapter.generate_decision) as spy_ai, \
         patch("scripts.run_phase2_ablation.search_public_memory", wraps=search_public_memory) as spy_mem:
        
        action, _, _, _, debug = execute_ablation_variant_decision("A3_AI_ECONOMIC_MEMORY", pub, op_cost=10.0, risk_penalty=5.0)
        
        assert spy_ai.call_count == 1
        assert spy_mem.call_count == 1


def test_5_a4_calls_ai_memory_and_systemic(sample_case):
    """Verify A4 (FULL_ARIV) invokes AI, memory, and systemic intelligence tracking."""
    pub = sample_case["public"]

    mock_systemic = MagicMock()
    mock_systemic.analyze_route_health.return_value = {
        "corridor": pub["corridor"],
        "status": "DEGRADED",
        "degradation_score": 3.5,
    }

    with patch.object(JudgeAIAdapter, "generate_decision", wraps=JudgeAIAdapter.generate_decision) as spy_ai, \
         patch("scripts.run_phase2_ablation.search_public_memory", wraps=search_public_memory) as spy_mem:
        
        action, _, _, _, debug = execute_ablation_variant_decision(
            "A4_FULL_ARIV", pub, op_cost=10.0, risk_penalty=5.0, systemic_service=mock_systemic
        )
        
        assert spy_ai.call_count == 1
        assert spy_mem.call_count == 1
        assert mock_systemic.record_signal.call_count == 1
        assert mock_systemic.analyze_route_health.call_count == 1


def test_6_7_no_hidden_truth_reaches_ai_or_memory(sample_case):
    """Verify hidden truth fields (latent_incident, outcome_roll, conversions) are never passed to AI or memory."""
    pub = copy.deepcopy(sample_case["public"])
    hidden = sample_case["_hidden_truth"]

    # Verify public context does NOT contain any hidden truth keys
    hidden_keys = {"latent_incident", "outcome_roll", "conversions", "is_systemic"}
    for hk in hidden_keys:
        assert hk not in pub

    with patch.object(JudgeAIAdapter, "generate_decision") as mock_ai:
        mock_ai.return_value = {
            "recommended_action": "RETRY_LATER",
            "candidate_actions": ["RETRY_LATER"],
            "reason": "Test",
            "confidence": 0.8,
            "knowledge_refs": [],
        }
        execute_ablation_variant_decision("A3_AI_ECONOMIC_MEMORY", pub, op_cost=10.0, risk_penalty=5.0)

        # Inspect prompt passed to AI
        prompt_arg = mock_ai.call_args[0][0]
        for hk in hidden_keys:
            assert hk not in prompt_arg
            assert str(hidden.get(hk)) not in prompt_arg


def test_8_oracle_regret_not_available_before_action_selection(sample_case):
    """Verify strategy execution functions never receive oracle_info or hidden_truth."""
    pub = sample_case["public"]

    with patch("scripts.run_judge_benchmark.compute_oracle_for_case") as mock_oracle:
        # Action selection happens independently of oracle computation
        action, _, _, _, _ = execute_ablation_variant_decision("A1_ECONOMIC", pub, op_cost=10.0, risk_penalty=5.0)
        assert mock_oracle.call_count == 0


def test_9_same_cohort_across_variants():
    """Verify that identical public cases and seeds are generated for all variants."""
    cohort1 = generate_cohort(count=50, seed=42)
    cohort2 = generate_cohort(count=50, seed=42)

    for c1, c2 in zip(cohort1, cohort2):
        assert c1["public"] == c2["public"]
        assert c1["_hidden_truth"] == c2["_hidden_truth"]


def test_10_no_cross_variant_mutable_state(sample_case):
    """Verify that running one variant does not mutate public case or pollute global state for next variant."""
    pub_original = copy.deepcopy(sample_case["public"])

    for v in VARIANTS:
        execute_ablation_variant_decision(v, sample_case["public"], op_cost=10.0, risk_penalty=5.0)
        assert sample_case["public"] == pub_original


def test_11_deterministic_replay():
    """Verify two independent runs of Phase 2 ablation produce bit-for-bit identical metrics."""
    res1 = run_phase2_ablation(cases_per_seed=10, seeds=[42], save_artifacts=False)
    res2 = run_phase2_ablation(cases_per_seed=10, seeds=[42], save_artifacts=False)

    json1 = json.dumps(res1["variants"], sort_keys=True)
    json2 = json.dumps(res2["variants"], sort_keys=True)
    assert json1 == json2


def test_12_zero_network_calls():
    """Verify zero external socket / HTTP network connections during benchmark execution."""
    import socket
    def forbidden_connect(*args, **kwargs):
        raise RuntimeError("Forbidden network call during offline benchmark execution!")

    with patch("socket.socket.connect", side_effect=forbidden_connect):
        res = run_phase2_ablation(cases_per_seed=10, seeds=[42], save_artifacts=False)
        assert len(res["variants"]) == 5


def test_13_consistent_metric_schema():
    """Verify all 5 variants produce identical dictionary metric keys and non-null aggregates."""
    res = run_phase2_ablation(cases_per_seed=20, seeds=[42, 43], save_artifacts=False)
    required_keys = {
        "variant",
        "total_cases",
        "gross_recovered_inr",
        "net_recovered_inr",
        "case_recovery_rate",
        "value_recovery_rate",
        "total_cost_inr",
        "total_risk_penalty_inr",
        "total_economic_regret_inr",
        "oracle_capture_rate",
        "policy_violations",
        "action_counts",
    }

    for var_key, metrics in res["variants"].items():
        assert required_keys.issubset(metrics.keys())
        assert metrics["total_cases"] == 40


def test_14_a0_baseline_parity_with_phase1_baseline():
    """Verify A0_BASELINE produces bit-for-bit identical action decisions and outcomes as Phase 1 BASELINE."""
    cohort = generate_cohort(count=100, seed=42)
    op_cost = 10.0
    risk_penalty = 5.0
    high_risk_penalty = 25.0

    for case_rec in cohort:
        pub = case_rec["public"]
        oracle_info = compute_oracle_for_case(case_rec, op_cost, risk_penalty, high_risk_penalty)

        # Phase 1 BASELINE
        act_p1, passed_p1, p_p1, prov_p1, _ = execute_strategy_decision("BASELINE", pub, op_cost, risk_penalty)
        eval_p1 = evaluate_strategy_outcome("BASELINE", act_p1, passed_p1, case_rec, oracle_info, op_cost, risk_penalty, high_risk_penalty)

        # Phase 2 A0_BASELINE
        act_p2, passed_p2, p_p2, prov_p2, _ = execute_ablation_variant_decision("A0_BASELINE", pub, op_cost, risk_penalty)
        eval_p2 = evaluate_strategy_outcome("A0_BASELINE", act_p2, passed_p2, case_rec, oracle_info, op_cost, risk_penalty, high_risk_penalty)

        # Bit-for-bit equivalence checks
        assert act_p1 == act_p2
        assert passed_p1 == passed_p2
        assert eval_p1["recovered"] == eval_p2["recovered"]
        assert eval_p1["recovered_amount"] == eval_p2["recovered_amount"]
        assert eval_p1["cost_incurred"] == eval_p2["cost_incurred"]
        assert eval_p1["risk_incurred"] == eval_p2["risk_incurred"]
        assert eval_p1["net_recovered_value"] == eval_p2["net_recovered_value"]
        assert eval_p1["policy_violation"] == eval_p2["policy_violation"]
        assert eval_p1["economic_regret"] == eval_p2["economic_regret"]
