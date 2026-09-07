#!/usr/bin/env python3
"""
scripts/benchmark_traces.py

Representative case trace utility for the ARIV economic benchmark.

For each of the first 5 synthetic cases (seed 42) prints, per strategy:
  - case_id, amount, classification
  - baseline_action
  - AI recommendation (AI_PLUS_ECONOMIC only)
  - candidate actions
  - probability per candidate   (via ProbabilityProvider.estimate)
  - ENR per candidate           (via EconomicOptimizer.rank_candidates)
  - policy result
  - final selected action
  - HIDDEN EVALUATOR DATA  (clearly labelled; never fed back to any strategy)

NO hidden truth is passed to any decision component.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.domain.decision import RecoveryAction, PolicyStatus
from app.domain.schemas import DecisionContext, DecisionProposal
from app.services.baseline import DeterministicBaseline
from app.services.candidate_generator import CandidateGenerator
from app.services.probability_provider import ProbabilityProvider
from app.services.economic_optimizer import EconomicOptimizer, LEGACY_TIE_BREAK
from app.services.policy import PolicyEngine

from scripts.run_economic_benchmark import generate_synthetic_benchmark_cases, BenchmarkAIAdapter

import asyncio


DEFAULT_OP_COST = 10.0
DEFAULT_RISK_PENALTY = 5.0


def _select_via_policy(ranked, domain, category, route_health):
    """Iterate ranked candidates through PolicyEngine; return first approved action."""
    for cand in ranked:
        p_status, _, _ = PolicyEngine.evaluate(
            proposal=DecisionProposal(recommended_action=cand["action"]),
            domain=domain,
            category=category,
            route_health=route_health,
        )
        if p_status in (PolicyStatus.APPROVED, PolicyStatus.NEEDS_REVIEW):
            return cand["action"], p_status
    return RecoveryAction.STOP_RECOVERY, PolicyStatus.APPROVED


def get_traces(num_cases: int = 5, seed: int = 42):
    cases = generate_synthetic_benchmark_cases(
        count=num_cases, seed=seed, min_paise=10000, max_paise=1000000
    )

    separator = "=" * 80

    for i, case in enumerate(cases):
        pub = case["public"]
        hidden = case["_hidden_truth"]   # used ONLY for HIDDEN EVALUATOR DATA display

        domain = pub["domain"]
        category = pub["failure_category"]
        retryability = pub["retryability"]
        recoverability = pub["recoverability"]
        amount = pub["amount"]

        baseline_action = DeterministicBaseline.decide(
            domain=domain, category=category, retryability=retryability
        )
        route_health = {
            "corridor": pub["corridor"],
            "status": pub["corridor_status"],
            "summary": f"Corridor {pub['corridor']}: {pub['corridor_status']}",
            "degradation_score": 3.5 if pub["corridor_status"] == "DEGRADED" else 0.5,
        }
        context = DecisionContext(
            case_id=pub["case_id"],
            tenant_id=pub["tenant_id"],
            domain=domain,
            amount=amount,
            currency="INR",
            failure_category=category,
            retryability=retryability,
            recoverability=recoverability,
            baseline_action=baseline_action,
            historical_cases=[],
            route_health=route_health,
        )

        print(f"\n{separator}")
        print(f"CASE {i+1:02d}  id={pub['case_id']}  amount=INR {amount:.2f}")
        print(f"  domain={domain.value}  category={category.value}")
        print(f"  retryability={retryability.value}  recoverability={recoverability.value}")
        print(f"  corridor={pub['corridor']}  corridor_status={pub['corridor_status']}")

        # ── NAIVE ──────────────────────────────────────────────────────────────
        print(f"\n  [NAIVE]")
        print(f"    baseline_action : {baseline_action.value}")
        print(f"    ai_recommendation: None")
        print(f"    candidate_actions: [RETRY_NOW]")
        naive_prob, naive_prov = ProbabilityProvider.estimate(RecoveryAction.RETRY_NOW, context)
        naive_enr = EconomicOptimizer.compute_expected_net_recovery(
            probability=naive_prob, recoverable_amount=amount,
            operational_cost=DEFAULT_OP_COST, risk_penalty=DEFAULT_RISK_PENALTY
        )
        print(f"    probabilities    : {{RETRY_NOW: {naive_prob:.3f}}}  provenance={naive_prov}")
        print(f"    ENR              : {{RETRY_NOW: {naive_enr:.3f}}}")
        naive_p_status, _, _ = PolicyEngine.evaluate(
            proposal=DecisionProposal(recommended_action=RecoveryAction.RETRY_NOW),
            domain=domain, category=category, route_health=route_health,
        )
        print(f"    policy_result    : {naive_p_status.value}")
        print(f"    final_action     : RETRY_NOW")

        # ── BASELINE ───────────────────────────────────────────────────────────
        print(f"\n  [BASELINE]")
        print(f"    baseline_action : {baseline_action.value}")
        print(f"    ai_recommendation: None")
        base_prob, base_prov = ProbabilityProvider.estimate(baseline_action, context)
        base_enr = EconomicOptimizer.compute_expected_net_recovery(
            probability=base_prob, recoverable_amount=amount,
            operational_cost=DEFAULT_OP_COST, risk_penalty=DEFAULT_RISK_PENALTY
        )
        print(f"    probabilities    : {{{baseline_action.value}: {base_prob:.3f}}}  provenance={base_prov}")
        print(f"    ENR              : {{{baseline_action.value}: {base_enr:.3f}}}")
        base_p_status, _, _ = PolicyEngine.evaluate(
            proposal=DecisionProposal(recommended_action=baseline_action),
            domain=domain, category=category, route_health=route_health,
        )
        base_final = baseline_action if base_p_status in (PolicyStatus.APPROVED, PolicyStatus.NEEDS_REVIEW) else RecoveryAction.STOP_RECOVERY
        print(f"    policy_result    : {base_p_status.value}")
        print(f"    final_action     : {base_final.value}")

        # ── ECONOMIC ───────────────────────────────────────────────────────────
        candidates_econ = CandidateGenerator.generate_candidates(context=context, ai_proposal=None)
        ranked_econ = EconomicOptimizer.rank_candidates(
            candidates=candidates_econ,
            context=context,
            probability_provider=ProbabilityProvider,
            operational_cost=DEFAULT_OP_COST,
            risk_penalty=DEFAULT_RISK_PENALTY,
            tie_break=LEGACY_TIE_BREAK,
        )
        econ_final, econ_p_status = _select_via_policy(ranked_econ, domain, category, route_health)
        print(f"\n  [ECONOMIC]")
        print(f"    baseline_action : {baseline_action.value}")
        print(f"    ai_recommendation: None")
        print(f"    candidate_actions: {[c.value for c in candidates_econ]}")
        probs_str = ", ".join(f"{r['action'].value}: {r['recovery_probability']:.3f}" for r in ranked_econ)
        enr_str   = ", ".join(f"{r['action'].value}: {r['expected_net_recovery']:.3f}" for r in ranked_econ)
        print(f"    probabilities    : {{{probs_str}}}")
        print(f"    ENR              : {{{enr_str}}}")
        print(f"    policy_result    : {econ_p_status.value}")
        print(f"    final_action     : {econ_final.value}")

        # ── AI_PLUS_ECONOMIC ───────────────────────────────────────────────────
        prompt = (
            f"domain:{domain.value} category:{category.value} "
            f"retryability:{retryability.value} route:{pub['corridor_status']}"
        )
        ai_resp = asyncio.run(BenchmarkAIAdapter.generate_decision(prompt))
        ai_rec = RecoveryAction[ai_resp["recommended_action"]]
        ai_cands = [RecoveryAction[a] for a in ai_resp["candidate_actions"] if a in RecoveryAction.__members__]
        ai_proposal = DecisionProposal(
            diagnosis=ai_resp.get("diagnosis"),
            recommended_action=ai_rec,
            candidate_actions=ai_cands,
            reason=ai_resp["reason"],
            confidence=ai_resp["confidence"],
            knowledge_refs=ai_resp["knowledge_refs"],
        )
        candidates_ai = CandidateGenerator.generate_candidates(context=context, ai_proposal=ai_proposal)
        ranked_ai = EconomicOptimizer.rank_candidates(
            candidates=candidates_ai,
            context=context,
            probability_provider=ProbabilityProvider,
            operational_cost=DEFAULT_OP_COST,
            risk_penalty=DEFAULT_RISK_PENALTY,
            tie_break=LEGACY_TIE_BREAK,
        )
        ai_final, ai_p_status = _select_via_policy(ranked_ai, domain, category, route_health)
        print(f"\n  [AI_PLUS_ECONOMIC]")
        print(f"    baseline_action : {baseline_action.value}")
        print(f"    ai_recommendation: {ai_rec.value}  (confidence={ai_resp['confidence']:.2f})")
        print(f"    candidate_actions: {[c.value for c in candidates_ai]}")
        probs_str_ai = ", ".join(f"{r['action'].value}: {r['recovery_probability']:.3f}" for r in ranked_ai)
        enr_str_ai   = ", ".join(f"{r['action'].value}: {r['expected_net_recovery']:.3f}" for r in ranked_ai)
        print(f"    probabilities    : {{{probs_str_ai}}}")
        print(f"    ENR              : {{{enr_str_ai}}}")
        print(f"    policy_result    : {ai_p_status.value}")
        print(f"    final_action     : {ai_final.value}")

        # ── HIDDEN EVALUATOR DATA (never fed to any strategy) ─────────────────
        print(f"\n  [HIDDEN EVALUATOR DATA — not exposed to any strategy]")
        print(f"    latent_incident : {hidden['latent_incident']}")
        print(f"    is_systemic     : {hidden['is_systemic']}")
        print(f"    outcome_roll    : {hidden['outcome_roll']:.4f}")
        conv = hidden["conversions"]
        conv_str = ", ".join(f"{k.value}: {v:.2f}" for k, v in conv.items())
        print(f"    conversions     : {{{conv_str}}}")

    print(f"\n{separator}")


if __name__ == "__main__":
    get_traces(num_cases=5, seed=42)
