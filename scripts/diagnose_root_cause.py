#!/usr/bin/env python3
"""
scripts/diagnose_root_cause.py

Diagnostic for the ARIV final-upgrade root-cause analysis (docs/final-upgrade/ai-root-cause.md).

Replays the EXACT Phase 2 ablation decision functions (execute_ablation_variant_decision /
evaluate_strategy_outcome from scripts/run_phase2_ablation.py and scripts/run_judge_benchmark.py)
so decisions are bit-for-bit identical to the committed ablation, but additionally captures
per-case detail: chosen action, action-switch deltas (A2 vs A1, A3 vs A2, A4 vs A3), oracle
action, latent truth, and probability provenance.

Output: JSON under artifacts/benchmarks/final_upgrade/root_cause_diagnostic.json
plus aggregate tables printed to stdout.
"""

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.systemic_intelligence import SystemicIntelligenceService

from scripts.run_judge_benchmark import (
    generate_cohort,
    compute_oracle_for_case,
    evaluate_strategy_outcome,
    DEFAULT_OPERATIONAL_COST_INR as OP_COST,
    DEFAULT_RISK_PENALTY_INR as RISK,
    DEFAULT_HIGH_RISK_PENALTY_INR as HIGH_RISK,
    DEFAULT_SEEDS,
)
from scripts.run_phase2_ablation import (
    execute_ablation_variant_decision,
)

VARIANTS = ["A1_ECONOMIC", "A2_AI_ECONOMIC", "A3_AI_ECONOMIC_MEMORY", "A4_FULL_ARIV"]


def variant_value(v):
    return v.value if hasattr(v, "value") else str(v)


def main(cases_per_seed=10000, seeds=None):
    if seeds is None:
        seeds = DEFAULT_SEEDS
    start = time.time()

    # Aggregation keys: (latent_incident, domain, is_systemic) -> per-variant totals
    agg = defaultdict(lambda: {v: {"net": 0.0, "gross": 0.0, "recovered": 0, "n": 0, "actions": defaultdict(int)} for v in VARIANTS})
    switch_a2_a1 = defaultdict(lambda: {"count": 0, "a1_conv": 0.0, "a2_conv": 0.0})
    switch_a3_a2 = defaultdict(lambda: {"count": 0, "a2_conv": 0.0, "a3_conv": 0.0})
    switch_a4_a3 = defaultdict(lambda: {"count": 0, "a3_conv": 0.0, "a4_conv": 0.0})
    summary = {"per_case": [], "totals": {}}

    for seed in seeds:
        cohort = generate_cohort(count=cases_per_seed, seed=seed)
        systemic_a4 = SystemicIntelligenceService()
        systemic_a4.clear_buffer()

        for case_rec in cohort:
            pub = case_rec["public"]
            hidden = case_rec["_hidden_truth"]
            oracle = compute_oracle_for_case(case_rec, OP_COST, RISK, HIGH_RISK)

            decision = {}
            for variant in VARIANTS:
                sys_srv = systemic_a4 if variant == "A4_FULL_ARIV" else None
                act, passed, est_p, prov, debug = execute_ablation_variant_decision(
                    variant, pub, OP_COST, RISK, sys_srv
                )
                out = evaluate_strategy_outcome(
                    variant, act, passed, case_rec, oracle, OP_COST, RISK, HIGH_RISK
                )
                decision[variant] = {"action": variant_value(act), "net": out["net_recovered_value"], "gross": out["recovered_amount"], "recovered": out["recovered"]}

            key = (
                hidden["latent_incident"],
                pub["domain"].value if hasattr(pub["domain"], "value") else str(pub["domain"]),
                hidden["is_systemic"],
            )
            for v in VARIANTS:
                d = decision[v]
                a = agg[key][v]
                a["net"] += d["net"]
                a["gross"] += d["gross"]
                a["recovered"] += 1 if d["recovered"] else 0
                a["n"] += 1
                a["actions"][d["action"]] += 1

            # Switch deltas
            truth_conv = lambda act: hidden["conversions"].get(act, 0.0)

            def actobj(s):
                for a in hidden["conversions"]:
                    if variant_value(a) == s:
                        return a
                return None

            for pair, sw, c1k, c2k in [
                (("A2_AI_ECONOMIC", "A1_ECONOMIC"), switch_a2_a1, "a1_conv", "a2_conv"),
                (("A3_AI_ECONOMIC_MEMORY", "A2_AI_ECONOMIC"), switch_a3_a2, "a2_conv", "a3_conv"),
                (("A4_FULL_ARIV", "A3_AI_ECONOMIC_MEMORY"), switch_a4_a3, "a3_conv", "a4_conv"),
            ]:
                a2a = decision[pair[0]]["action"]
                a1a = decision[pair[1]]["action"]
                if a2a != a1a:
                    o2 = actobj(a2a)
                    o1 = actobj(a1a)
                    sw[tuple(sorted([a2a, a1a]))]["count"] += 1
                    sw[tuple(sorted([a2a, a1a]))][c1k] += truth_conv(o1) if o1 else 0.0
                    sw[tuple(sorted([a2a, a1a]))][c2k] += truth_conv(o2) if o2 else 0.0

            summary["per_case"].append({
                "seed": seed,
                "latent": hidden["latent_incident"],
                "domain": key[1],
                "is_systemic": hidden["is_systemic"],
                "amount": pub["amount"],
                "oracle_action": oracle["oracle_action"],
                "oracle_net": oracle["oracle_net_value"],
                "actions": {v: decision[v]["action"] for v in VARIANTS},
                "nets": {v: round(decision[v]["net"], 2) for v in VARIANTS},
            })

    print("=== ATTRIBUTION BY (latent_incident, domain, is_systemic) ===")
    totals = {v: 0.0 for v in VARIANTS}
    rows = []
    for key in sorted(agg):
        r = {"key": key, "n": agg[key]["A1_ECONOMIC"]["n"]}
        for v in VARIANTS:
            r[v] = round(agg[key][v]["net"], 2)
            r[f"{v}_rec"] = agg[key][v]["recovered"]
            r[f"{v}_acts"] = dict(agg[key][v]["actions"])
            totals[v] += agg[key][v]["net"]
        rows.append(r)
    for r in rows:
        print(f"{str(r['key']):65s} n={r['n']:5d}  A1={r['A1_ECONOMIC']:12,.0f}  A2={r['A2_AI_ECONOMIC']:12,.0f}  A3={r['A3_AI_ECONOMIC_MEMORY']:12,.0f}  A4={r['A4_FULL_ARIV']:12,.0f}")
        acts = ", ".join(f"{v}:{r[v+'_acts']}" for v in VARIANTS)
        print(f"{'':65s}    actions  {acts}")
    print("TOTALS:", {v: round(totals[v], 2) for v in VARIANTS})

    print("\n=== SWITCH ANALYSIS A2 vs A1 ===")
    for sw, d in sorted(switch_a2_a1.items()):
        print(f"{sw}  count={d['count']:6d}  sum_true_conv A1={d['a1_conv']:.2f} A2={d['a2_conv']:.2f}")

    print("\n=== SWITCH ANALYSIS A3 vs A2 ===")
    for sw, d in sorted(switch_a3_a2.items()):
        print(f"{sw}  count={d['count']:6d}  sum_true_conv A2={d['a2_conv']:.2f} A3={d['a3_conv']:.2f}")

    print("\n=== SWITCH ANALYSIS A4 vs A3 ===")
    for sw, d in sorted(switch_a4_a3.items()):
        print(f"{sw}  count={d['count']:6d}  sum_true_conv A3={d['a3_conv']:.2f} A4={d['a4_conv']:.2f}")

    summary["totals"] = totals
    summary["switch_a2_a1"] = {f"{k[0]}<->{k[1]}": v for k, v in switch_a2_a1.items()}
    summary["switch_a3_a2"] = {f"{k[0]}<->{k[1]}": v for k, v in switch_a3_a2.items()}
    summary["switch_a4_a3"] = {f"{k[0]}<->{k[1]}": v for k, v in switch_a4_a3.items()}
    summary["elapsed_seconds"] = round(time.time() - start, 2)
    summary["config"] = {"cases_per_seed": cases_per_seed, "seeds": seeds, "defaults": {"op_cost": OP_COST, "risk": RISK, "high_risk": HIGH_RISK}}

    out_path = PROJECT_ROOT / "artifacts" / "benchmarks" / "final_upgrade" / "root_cause_diagnostic.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nSaved diagnostic to {out_path} in {summary['elapsed_seconds']}s")


if __name__ == "__main__":
    main()