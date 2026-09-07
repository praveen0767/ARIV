#!/usr/bin/env python3
"""run_phase3_temporal.py

Phase 3 harness implementing three variants:
* T0 – frozen Phase 2 Economic optimizer (A1_ECONOMIC) – control.
* T1 – Economic optimizer wrapped by deterministic temporal decision layer **without** explicit wait costs.
* T2 – Same as T1 but with explicit wait and delay costs (WAIT economics).

The script reuses the public cohort generation and oracle utilities from
`run_judge_benchmark.py`. All evaluation is deterministic and offline.
"""

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Project root import handling
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(PROJECT_ROOT))

from app.domain.decision import RecoveryAction
from app.services.economic_optimizer import EconomicOptimizer
from app.services.candidate_generator import CandidateGenerator
from app.services.probability_provider import ProbabilityProvider
from app.services.economic_optimizer import EconomicOptimizer, LEGACY_TIE_BREAK
from app.services.policy import PolicyEngine
from app.services.temporal_layer import evaluate_temporal_decision, TemporalDecision
from scripts.run_judge_benchmark import (
    generate_cohort,
    compute_oracle_for_case,
    evaluate_strategy_outcome,
    DEFAULT_SEEDS,
    DEFAULT_CASES_PER_SEED,
    DEFAULT_OPERATIONAL_COST_INR,
    DEFAULT_RISK_PENALTY_INR,
    DEFAULT_HIGH_RISK_PENALTY_INR,
)

VARIANTS = ["T0", "T1", "T2"]


def run_phase3(
    cases_per_seed: int = DEFAULT_CASES_PER_SEED,
    seeds: List[int] = DEFAULT_SEEDS,
) -> Dict[str, Any]:
    start_time = time.time()
    op_cost = DEFAULT_OPERATIONAL_COST_INR
    risk_penalty = DEFAULT_RISK_PENALTY_INR
    high_risk_penalty = DEFAULT_HIGH_RISK_PENALTY_INR

    seed_variant_results: Dict[int, Dict[str, Dict[str, Any]]] = {}
    seed_total_volumes: Dict[int, float] = {}

    for seed in seeds:
        seed_variant_results[seed] = {v: {
            "gross_recovered": 0.0,
            "net_recovered": 0.0,
            "cost": 0.0,
            "risk": 0.0,
            "regret": 0.0,
            "oracle_net": 0.0,
            "recovered_cases": 0,
            "policy_violations": 0,
            "action_counts": {},
        } for v in VARIANTS}

        cohort = generate_cohort(count=cases_per_seed, seed=seed)
        seed_total_volumes[seed] = sum(c["public"]["amount"] for c in cohort)

        for case_rec in cohort:
            pub = case_rec["public"]
            oracle_info = compute_oracle_for_case(case_rec, op_cost, risk_penalty, high_risk_penalty)

            # Economic optimizer recommendation (used for all variants)
            # Build a minimal DecisionContext to feed the EconomicOptimizer (reuse logic from Phase2)
            # For simplicity we re‑use the existing execute_ablation_variant_decision logic for A1.
            # Here we mimic that path directly.
            # NOTE: EconomicOptimizer expects candidates generated via CandidateGenerator.
            # Construct a dummy context similar to Phase2's.
            from app.domain.schemas import DecisionContext, DecisionProposal
            from app.domain.decision import RecoveryAction, PolicyStatus
            from app.domain.recovery_case import RecoveryDomain
            from app.domain.classification import FailureCategory, Retryability, Recoverability

            # Assemble DecisionContext (replicating logic from Phase2 A1 path)
            context = DecisionContext(
                case_id=pub["case_id"],
                tenant_id=pub["tenant_id"],
                domain=pub["domain"],
                amount=pub["amount"],
                currency="INR",
                failure_category=pub["failure_category"],
                retryability=pub["retryability"],
                recoverability=pub["recoverability"],
                baseline_action=None,
                historical_cases=[],
                playbook_snippets=[],
                route_health={"status": pub.get("corridor_status", "OK")},
            )

            # Candidate generation and ranking (same as Phase2 A1)
            candidates = CandidateGenerator.generate_candidates(context=context, ai_proposal=None)
            ranked = EconomicOptimizer.rank_candidates(
                candidates=candidates,
                context=context,
                probability_provider=ProbabilityProvider,
                operational_cost=op_cost,
                risk_penalty=risk_penalty,
                tie_break=LEGACY_TIE_BREAK,
            )
            # Select first policy‑approved candidate
            selected_action = RecoveryAction.STOP_RECOVERY
            selected_prob = 0.0
            selected_prov = []
            for cand in ranked:
                p_status, _, _ = PolicyEngine.evaluate(
                    proposal=DecisionProposal(recommended_action=cand["action"]),
                    domain=context.domain,
                    category=context.failure_category,
                    route_health=context.route_health,
                )
                if p_status in (PolicyStatus.APPROVED, PolicyStatus.NEEDS_REVIEW):
                    selected_action = cand["action"]
                    selected_prob = cand["recovery_probability"]
                    selected_prov = cand["probability_provenance"]
                    break
            # T0 uses the economic action directly
            for variant in VARIANTS:
                if variant == "T0":
                    act = selected_action
                    prob = selected_prob
                elif variant == "T1":
                    # Temporal wrapper without explicit wait costs (costs set to 0)
                    act, _ = evaluate_temporal_decision(
                        context=context,
                        economic_action=selected_action,
                        economic_probability=selected_prob,
                        delay_cost_per_interval=0.0,
                        waiting_cost_per_interval=0.0,
                    )
                    prob = selected_prob  # probability unchanged for accounting
                else:  # T2 – full wait economics (default costs inside layer)
                    act, _ = evaluate_temporal_decision(
                        context=context,
                        economic_action=selected_action,
                        economic_probability=selected_prob,
                        # use defaults (0.01, 0.005) defined in temporal_layer
                    )
                    prob = selected_prob

                out = evaluate_strategy_outcome(
                    strategy=variant,
                    action=act,
                    passed_policy=True,  # policy already enforced above
                    case_record=case_rec,
                    oracle_info=oracle_info,
                    op_cost=op_cost,
                    risk_penalty=risk_penalty,
                    high_risk_penalty=high_risk_penalty,
                )
                v_res = seed_variant_results[seed][variant]
                v_res["gross_recovered"] += out["recovered_amount"]
                v_res["net_recovered"] += out["net_recovered_value"]
                v_res["cost"] += out["cost_incurred"]
                v_res["risk"] += out["risk_incurred"]
                v_res["regret"] += out["economic_regret"]
                v_res["oracle_net"] += out["oracle_net_value"]
                if out["recovered"]:
                    v_res["recovered_cases"] += 1
                if out["policy_violation"]:
                    v_res["policy_violations"] += 1
                act_str = act.value
                v_res["action_counts"][act_str] = v_res["action_counts"].get(act_str, 0) + 1

    # Aggregation similar to Phase2
    total_cases_per_variant = cases_per_seed * len(seeds)
    total_volume_cohort = sum(seed_total_volumes.values())
    aggregated_variants: Dict[str, Dict[str, Any]] = {}
    from scripts.run_phase2_ablation import calculate_student_t_ci
    for variant in VARIANTS:
        nets = [seed_variant_results[s][variant]["net_recovered"] for s in seeds]
        grosses = [seed_variant_results[s][variant]["gross_recovered"] for s in seeds]
        costs = [seed_variant_results[s][variant]["cost"] for s in seeds]
        risks = [seed_variant_results[s][variant]["risk"] for s in seeds]
        regrets = [seed_variant_results[s][variant]["regret"] for s in seeds]
        oracles = [seed_variant_results[s][variant]["oracle_net"] for s in seeds]
        rec_cases = sum(seed_variant_results[s][variant]["recovered_cases"] for s in seeds)
        violations = sum(seed_variant_results[s][variant]["policy_violations"] for s in seeds)
        mean_net, ci_low, ci_high = calculate_student_t_ci(nets)
        sum_net = sum(nets)
        sum_gross = sum(grosses)
        sum_cost = sum(costs)
        sum_risk = sum(risks)
        sum_regret = sum(regrets)
        sum_oracle = sum(oracles)
        case_rec_rate = round((rec_cases / total_cases_per_variant) * 100.0, 2)
        val_rec_rate = round((sum_gross / total_volume_cohort) * 100.0, 2) if total_volume_cohort > 0 else 0.0
        oracle_capture = round((sum_net / sum_oracle) * 100.0, 2) if sum_oracle > 0 else 0.0
        # Combine action counts across seeds
        combined_action_counts: Dict[str, int] = {}
        for s in seeds:
            for act_k, cnt in seed_variant_results[s][variant]["action_counts"].items():
                combined_action_counts[act_k] = combined_action_counts.get(act_k, 0) + cnt
        aggregated_variants[variant] = {
            "variant": variant,
            "total_cases": total_cases_per_variant,
            "recovered_cases": rec_cases,
            "case_recovery_rate": case_rec_rate,
            "value_recovery_rate": val_rec_rate,
            "gross_recovered_inr": round(sum_gross, 2),
            "net_recovered_inr": round(sum_net, 2),
            "net_recovered_mean_per_seed": mean_net,
            "net_recovered_ci95": [ci_low, ci_high],
            "total_cost_inr": round(sum_cost, 2),
            "total_risk_penalty_inr": round(sum_risk, 2),
            "total_economic_regret_inr": round(sum_regret, 2),
            "oracle_capture_rate": oracle_capture,
            "policy_violations": violations,
            "action_counts": combined_action_counts,
        }

    elapsed = round(time.time() - start_time, 2)
    final_payload = {
        "metadata": {
            "cases_per_seed": cases_per_seed,
            "seeds": seeds,
            "total_cases_evaluated": total_cases_per_variant * len(VARIANTS),
            "total_transaction_volume_inr": round(total_volume_cohort, 2),
            "elapsed_seconds": elapsed,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "per_seed_results": seed_variant_results,
        "variants": aggregated_variants,
    }
    # Write artifacts
    out_dir = PROJECT_ROOT / "artifacts" / "benchmarks" / "phase3"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "phase3_temporal_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, indent=2)
    # Simple markdown report (placeholder)
    md_path = out_dir / "phase3_report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Phase 3 Temporal / Wait Economics Report\n\n")
        for v in VARIANTS:
            agg = aggregated_variants[v]
            f.write(f"## Variant {v}\n")
            f.write(f"- Net Recovered: ₹{agg['net_recovered_inr']:,}\n")
            f.write(f"- Case Recovery Rate: {agg['case_recovery_rate']}%\n\n")
    return final_payload


def main():
    parser = argparse.ArgumentParser(description="Run Phase 3 Temporal / Wait Economics benchmark")
    parser.add_argument("--cases", type=int, default=DEFAULT_CASES_PER_SEED, help="Cases per seed")
    parser.add_argument("--seeds", type=int, nargs="+", default=DEFAULT_SEEDS, help="Seeds to evaluate")
    args = parser.parse_args()
    res = run_phase3(cases_per_seed=args.cases, seeds=args.seeds)
    print("\nPhase 3 aggregate results:")
    for v in VARIANTS:
        agg = res["variants"][v]
        print(f"{v:3s}: Net ₹{agg['net_recovered_inr']:12,.2f} | Cases {agg['case_recovery_rate']}%")

if __name__ == "__main__":
    main()
