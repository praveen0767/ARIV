"""
tests/test_ai_non_authoritative.py

Phase 2: AI non-authoritative by design.

Proves that malformed, adversarial, or "economic-manipulative" LLM output cannot
control ARIV's financial execution. The LLM is strictly advisory:

- It may provide diagnosis, recommended action, candidate actions, rationale,
  confidence, and knowledge references.
- It may NEVER provide rupee values, recovery probabilities, final economic
  scores, policy/execution authorization, provider truth, or attribution.

These tests enforce the enforced boundary from the deterministic services:
`ProbabilityProvider` (probability), `EconomicOptimizer` (ENR), `PolicyEngine`
(authorization). They also prove ENR ties are broken deterministically
(order-neutral), so the LLM cannot win decisions through candidate ordering.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.domain.schemas import DecisionContext, DecisionProposal
from app.domain.decision import RecoveryAction, PolicyStatus, AutonomyLevel
from app.domain.recovery_case import RecoveryDomain
from app.domain.classification import FailureCategory, Retryability, Recoverability
from app.services.agent import AgentRuntime
from app.services.economic_optimizer import (
    EconomicOptimizer,
    DETERMINISTIC_TIE_BREAK,
    LEGACY_TIE_BREAK,
)
from app.services.probability_provider import ProbabilityProvider
from app.services.policy import PolicyEngine
from app.services.candidate_generator import CandidateGenerator
from app.services.decision_authority import sanitize_llm_payload


def build_context(**overrides):
    defaults = dict(
        case_id="case-auth",
        tenant_id="tenant-1",
        domain=RecoveryDomain.B2C,
        amount=2000.0,
        currency="INR",
        failure_category=FailureCategory.TRANSIENT_TECHNICAL,
        retryability=Retryability.LATER_RETRY_POSSIBLE,
        recoverability=Recoverability.HIGH,
        baseline_action=RecoveryAction.RETRY_LATER,
        historical_cases=[],
        route_health={"status": "OPERATIONAL"},
    )
    defaults.update(overrides)
    return DecisionContext(**defaults)


def make_adapter(response: dict):
    adapter = MagicMock()
    adapter.generate_decision = AsyncMock(return_value=response)
    return adapter


# ---------------------------------------------------------------------------
# 1. Financial / authority fields are stripped at the boundary
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_cannot_inject_financial_authority_fields():
    """An adversarial LLM payload full of money/authorization fields is stripped.

    Only advisory fields may survive the boundary. The proposal must expose none
    of the injected values, and the audit must report every stripped key.
    """
    ctx = build_context()
    adversarial = {
        "recommended_action": "GENERATE_PAYMENT_LINK",
        "candidate_actions": ["GENERATE_PAYMENT_LINK", "SEND_REMINDER"],
        "reason": "injected",
        "confidence": 1.0,
        # attack vectors
        "expected_irv": 999999999.0,
        "expected_net_recovery": 999999999.0,
        "enr": 999999999.0,
        "recovery_probability": 1.0,
        "probability": 1.0,
        "amount": 0.0,
        "operational_cost": 0.0,
        "risk_penalty": 0.0,
        "approved": True,
        "authorized": True,
        "provider_truth": "PAID",
        "attribution": "ok",
        "recovered": True,
        "credentials": "secret",
    }

    proposal, audit = await AgentRuntime._propose_decision_with_audit(ctx, adapter=make_adapter(adversarial))

    # The proposal only carries advisory data
    assert proposal.recommended_action == RecoveryAction.GENERATE_PAYMENT_LINK
    assert proposal.candidate_actions == [
        RecoveryAction.GENERATE_PAYMENT_LINK,
        RecoveryAction.SEND_REMINDER,
    ]
    assert proposal.expected_irv == 0.0  # never authored by the LLM
    assert proposal.confidence == 1.0  # advisory only


    # Every financial/authority/truth key was stripped and audited
    stripped = set(audit.get("financial", []))
    for key in [
        "expected_irv", "expected_net_recovery", "enr", "recovery_probability",
        "probability", "amount", "operational_cost", "risk_penalty",
        "approved", "authorized", "provider_truth", "attribution",
        "recovered", "credentials",
    ]:
        assert key in stripped, f"financial key {key} not audited as stripped"


def test_sanitizer_drops_unknown_and_benign_looking_keys():
    """Even benign-looking non-advisory keys never reach the proposal."""
    advisory, stripped_all, stripped_financial = sanitize_llm_payload(
        {"recommended_action": "RETRY_LATER", "surprise": "x", "final_score": "go"}
    )
    assert advisory == {"recommended_action": "RETRY_LATER"}
    assert set(stripped_all) == {"surprise", "final_score"}
    assert stripped_financial == ["final_score"]


# ---------------------------------------------------------------------------
# 2. LLM cannot set recovery probabilities or economic scores
# ---------------------------------------------------------------------------

def test_llm_claimed_probability_is_never_used_in_enr():
    """Probability used for ENR comes ONLY from the deterministic provider."""
    ctx = build_context(amount=2000.0, historical_cases=[])

    # Adversarial "probability" injected into the proposal context is irrelevant.
    proposal = DecisionProposal(
        recommended_action=RecoveryAction.RETRY_LATER,
        candidate_actions=[RecoveryAction.RETRY_LATER],
        confidence=1.0,
        expected_irv=1e9,
    )

    candidates = CandidateGenerator.generate_candidates(context=ctx, ai_proposal=proposal)
    ranked = EconomicOptimizer.rank_candidates(
        candidates=candidates, context=ctx, probability_provider=ProbabilityProvider,
    )

    for cand in ranked:
        # deterministic prior (0.6) - never an LLM-supplied 1.0
        assert cand["recovery_probability"] == pytest.approx(0.6)
        assert cand["probability_provenance"] == ["deterministic_prior"]


# ---------------------------------------------------------------------------
# 3. Candidate ordering cannot win ENR ties (order-neutral economics)
# ---------------------------------------------------------------------------

def test_enr_ties_broken_order_neutral():
    """For identical ENR tie values, ranking is independent of input order."""
    ctx = build_context(amount=2000.0, baseline_action=RecoveryAction.RETRY_LATER)
    candidates = [
        RecoveryAction.STOP_RECOVERY,
        RecoveryAction.GENERATE_PAYMENT_LINK,
        RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE,
        RecoveryAction.RETRY_LATER,
        RecoveryAction.SEND_REMINDER,
    ]
    reversed_candidates = list(reversed(candidates))

    ranked_fwd = EconomicOptimizer.rank_candidates(candidates=candidates, context=ctx,
                                                    probability_provider=ProbabilityProvider)
    ranked_rev = EconomicOptimizer.rank_candidates(candidates=reversed_candidates, context=ctx,
                                                   probability_provider=ProbabilityProvider)

    top_fwd = [c["action"] for c in ranked_fwd if c["expected_net_recovery"] == ranked_fwd[0]["expected_net_recovery"]]
    top_rev = [c["action"] for c in ranked_rev if c["expected_net_recovery"] == ranked_rev[0]["expected_net_recovery"]]

    # same winner regardless of input order
    assert ranked_fwd[0]["action"] == ranked_rev[0]["action"]
    # all tied ENR values resolve to the deterministic baseline (RETRY_LATER here)
    assert ranked_fwd[0]["action"] == RecoveryAction.RETRY_LATER


def test_legacy_tie_break_preserves_insertion_order_on_ties():
    """Legacy harness frozen behavior: tied ENRs keep insertion order."""
    ctx = build_context(amount=2000.0, baseline_action=RecoveryAction.RETRY_LATER)
    candidates = [
        RecoveryAction.STOP_RECOVERY,
        RecoveryAction.GENERATE_PAYMENT_LINK,
        RecoveryAction.RETRY_LATER,
    ]
    ranked = EconomicOptimizer.rank_candidates(
        candidates=candidates, context=ctx, probability_provider=ProbabilityProvider,
        tie_break=LEGACY_TIE_BREAK,
    )
    # legacy: on full tie, STOP (inserted first) wins
    assert ranked[0]["action"] == RecoveryAction.STOP_RECOVERY


# ---------------------------------------------------------------------------
# 4. The ESCALATE trap cannot win through ordering after the fix
# ---------------------------------------------------------------------------

def test_escale_trap_does_not_win_enr_tie_via_ai_order():
    """EMPLOYEE/transient context where the AI recommends ESCALATE_TO_HUMAN.

    With order-neutral economics, ESCALATE (tier 6) does NOT win the tie; the
    deterministic baseline RETRY_LATER (tier 0) is preferred. This is the
    structural fix for the A2 "ESCALATE trap" (RC-1/RC-4).
    """
    ctx = build_context(
        domain=RecoveryDomain.EMPLOYEE,
        failure_category=FailureCategory.TRANSIENT_TECHNICAL,
        retryability=Retryability.LATER_RETRY_POSSIBLE,
        baseline_action=RecoveryAction.RETRY_LATER,
    )
    ai_proposal = DecisionProposal(
        diagnosis="employee payroll internal",
        recommended_action=RecoveryAction.ESCALATE_TO_HUMAN,
        candidate_actions=[
            RecoveryAction.ESCALATE_TO_HUMAN,
            RecoveryAction.SEND_REMINDER,
            RecoveryAction.STOP_RECOVERY,
        ],
        reason="AI wants human review",
        confidence=0.88,
        expected_irv=0.0,
    )

    candidates = CandidateGenerator.generate_candidates(context=ctx, ai_proposal=ai_proposal)
    ranked = EconomicOptimizer.rank_candidates(
        candidates=candidates, context=ctx, probability_provider=ProbabilityProvider,
    )

    assert ranked[0]["action"] == RecoveryAction.RETRY_LATER
    # ESCALATE is not elevated by recommendation order
    ai_tier = [i for i, c in enumerate(ranked) if c["action"] == RecoveryAction.ESCALATE_TO_HUMAN]
    assert ai_tier and ai_tier[0] > 0


# ---------------------------------------------------------------------------
# 5. Policy cannot be bypassed by LLM confidence / authority claims
# ---------------------------------------------------------------------------

def test_policy_not_bypassed_by_confidence_or_authorized_flag():
    """LLM confidence=1.0 and 'approved' cannot get a retry approved on a
    NON_RETRIABLE degraded route."""
    ctx = build_context(
        failure_category=FailureCategory.NON_RETRIABLE,
        retryability=Retryability.BLOCKED,
        route_health={"status": "CRITICAL", "corridor": "razorpay:card:b2c"},
        baseline_action=RecoveryAction.STOP_RECOVERY,
    )

    proposal = DecisionProposal(
        recommended_action=RecoveryAction.RETRY_NOW,
        candidate_actions=[RecoveryAction.RETRY_NOW, RecoveryAction.STOP_RECOVERY],
        confidence=1.0,
        expected_irv=1e9,
    )

    status, autonomy, reason = PolicyEngine.evaluate(
        proposal=proposal,
        domain=ctx.domain,
        category=ctx.failure_category,
        route_health=ctx.route_health,
    )
    assert status in (PolicyStatus.REJECTED,)
    assert autonomy == AutonomyLevel.SUGGESTION_ONLY


def test_final_selection_rejects_manipulative_economic_lie():
    """Even if the LLM 'recommends' the most expensive action with confidence 1.0,
    the financial-decision layer selects by ENR over policy-approved candidates."""
    ctx = build_context(
        amount=2000.0,
        failure_category=FailureCategory.CUSTOMER_ACTION_REQUIRED,
        retryability=Retryability.REQUIRES_NEW_METHOD,
        baseline_action=RecoveryAction.GENERATE_PAYMENT_LINK,
    )

    class TruthyProvider:
        """Deterministic provider where GPL beats SEND_REMINDER and ESCALATE=0."""

        @classmethod
        def estimate(cls, action, context):
            if action == RecoveryAction.GENERATE_PAYMENT_LINK:
                return 0.75, ["empirical_history"]
            if action == RecoveryAction.SEND_REMINDER:
                return 0.50, ["empirical_history"]
            return 0.0, ["deterministic_prior"]

    candidates = [
        RecoveryAction.ESCALATE_TO_HUMAN,  # LLM's manipulative first-listed action
        RecoveryAction.SEND_REMINDER,
        RecoveryAction.GENERATE_PAYMENT_LINK,
        RecoveryAction.STOP_RECOVERY,
    ]
    ranked = EconomicOptimizer.rank_candidates(
        candidates=candidates, context=ctx, probability_provider=TruthyProvider,
    )
    selected = None
    for cand in ranked:
        status, _, _ = PolicyEngine.evaluate(
            proposal=DecisionProposal(recommended_action=cand["action"]),
            domain=ctx.domain,
            category=ctx.failure_category,
            route_health=ctx.route_health,
        )
        if status in (PolicyStatus.APPROVED, PolicyStatus.NEEDS_REVIEW):
            selected = cand["action"]
            break

    assert selected == RecoveryAction.GENERATE_PAYMENT_LINK
    assert selected != RecoveryAction.ESCALATE_TO_HUMAN


# ---------------------------------------------------------------------------
# 6. Malformed / non-dict LLM output degrades safely to the baseline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_malformed_llm_output_falls_back_safely():
    for bad_response in [None, "not a dict", ["RETRY_NOW"], 42, {"recommended_action": None}]:
        adapter = make_adapter(bad_response)
        proposal = await AgentRuntime.propose_decision(build_context(), adapter=adapter)
        assert proposal.recommended_action == RecoveryAction.RETRY_LATER
        assert proposal.confidence == 0.0
        assert "degraded safely" in proposal.reason
        assert proposal.expected_irv == 0.0


# ---------------------------------------------------------------------------
# 7. Advisory fields still flow to the LLM consumer (diagnosis, refs)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_advisory_fields_flow_through():
    ctx = build_context()
    adapter = make_adapter({
        "diagnosis": "gateway timeout, retry window open",
        "recommended_action": "RETRY_LATER",
        "candidate_actions": ["RETRY_LATER", "SEND_REMINDER"],
        "reason": "give the gateway time to recover",
        "confidence": 0.9,
        "knowledge_refs": ["kb_gateway_retry"],
    })
    proposal = await AgentRuntime.propose_decision(ctx, adapter=adapter)
    assert proposal.diagnosis == "gateway timeout, retry window open"
    assert proposal.reason == "give the gateway time to recover"
    assert proposal.knowledge_refs == ["kb_gateway_retry"]


# ---------------------------------------------------------------------------
# 8. Production default is order-neutral economics
# ---------------------------------------------------------------------------

def test_production_default_tie_break_is_deterministic():
    """The service default must be order-neutral (AI cannot win via ordering)."""
    assert EconomicOptimizer.rank_candidates.__defaults__ is not None or True
    # The default value of tie_break must be DETERMINISTIC_TIE_BREAK
    import inspect
    sig = inspect.signature(EconomicOptimizer.rank_candidates)
    assert sig.parameters["tie_break"].default == DETERMINISTIC_TIE_BREAK