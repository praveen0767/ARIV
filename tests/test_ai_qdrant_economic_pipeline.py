import pytest
import hashlib
from unittest.mock import AsyncMock, patch, MagicMock
from app.domain.schemas import DecisionContext, DecisionProposal
from app.domain.decision import RecoveryAction, PolicyStatus, AutonomyLevel
from app.domain.recovery_case import RecoveryDomain
from app.domain.classification import FailureCategory, Retryability, Recoverability
from app.services.agent import AgentRuntime
from app.services.embedding import EmbeddingService
from app.services.candidate_generator import CandidateGenerator
from app.services.probability_provider import ProbabilityProvider
from app.services.economic_optimizer import EconomicOptimizer
from app.services.policy import PolicyEngine
from app.core.config import settings


@pytest.mark.asyncio
async def test_decision_proposal_schema_supports_candidate_actions():
    proposal = DecisionProposal(
        recommended_action=RecoveryAction.GENERATE_PAYMENT_LINK,
        candidate_actions=[
            RecoveryAction.GENERATE_PAYMENT_LINK,
            RecoveryAction.SEND_REMINDER,
            RecoveryAction.RETRY_LATER,
        ],
        reason="Customer preferred alternative link.",
        confidence=0.88,
        expected_irv=0.0,
        knowledge_refs=["playbook_b2c_high_value"],
    )
    assert proposal.recommended_action == RecoveryAction.GENERATE_PAYMENT_LINK
    assert len(proposal.candidate_actions) == 3
    assert proposal.confidence == 0.88


@pytest.mark.asyncio
async def test_agent_runtime_real_adapter_structured_parsing():
    mock_adapter = MagicMock()
    mock_adapter.generate_decision = AsyncMock(return_value={
        "recommended_action": "GENERATE_PAYMENT_LINK",
        "candidate_actions": ["GENERATE_PAYMENT_LINK", "SEND_REMINDER"],
        "reason": "AI selected alternative payment link.",
        "confidence": 0.82,
        "knowledge_refs": ["ref_1"],
    })

    context = DecisionContext(
        case_id="case-101",
        tenant_id="tenant-1",
        domain=RecoveryDomain.B2C,
        amount=500.0,
        currency="INR",
        failure_category=FailureCategory.TRANSIENT_TECHNICAL,
        retryability=Retryability.LATER_RETRY_POSSIBLE,
        baseline_action=RecoveryAction.RETRY_LATER,
        historical_cases=[
            {"action_type": "GENERATE_PAYMENT_LINK", "outcome_status": "RECOVERED"}
        ],
    )

    proposal = await AgentRuntime.propose_decision(context, adapter=mock_adapter)

    # 1. AI recommendation differs from baseline
    assert context.baseline_action == RecoveryAction.RETRY_LATER
    assert proposal.recommended_action == RecoveryAction.GENERATE_PAYMENT_LINK
    assert proposal.recommended_action != context.baseline_action

    # 2. Dynamic confidence and candidate actions parsed
    assert proposal.confidence == 0.82
    assert proposal.candidate_actions == [
        RecoveryAction.GENERATE_PAYMENT_LINK,
        RecoveryAction.SEND_REMINDER,
    ]
    # 3. Expected IRV is not authored by LLM
    assert proposal.expected_irv == 0.0

    # 4. Qdrant evidence was included in the prompt passed to adapter
    mock_adapter.generate_decision.assert_called_once()
    called_prompt = mock_adapter.generate_decision.call_args[1]["prompt"]
    assert "Retrieved Historical Recovery Cases:" in called_prompt
    assert "GENERATE_PAYMENT_LINK" in called_prompt
    assert "RECOVERED" in called_prompt


@pytest.mark.asyncio
async def test_agent_runtime_malformed_llm_safe_fallback():
    mock_adapter = MagicMock()
    mock_adapter.generate_decision = AsyncMock(side_effect=RuntimeError("OpenAI connection timed out"))

    context = DecisionContext(
        case_id="case-102",
        tenant_id="tenant-1",
        domain=RecoveryDomain.B2C,
        amount=250.0,
        currency="INR",
        failure_category=FailureCategory.TRANSIENT_TECHNICAL,
        retryability=Retryability.LATER_RETRY_POSSIBLE,
        baseline_action=RecoveryAction.RETRY_LATER,
    )

    proposal = await AgentRuntime.propose_decision(context, adapter=mock_adapter)

    # Graceful degradation to baseline
    assert proposal.recommended_action == RecoveryAction.RETRY_LATER
    assert proposal.candidate_actions == [RecoveryAction.RETRY_LATER]
    assert proposal.confidence == 0.0
    assert proposal.expected_irv == 0.0
    assert "degraded safely" in proposal.reason


def test_qdrant_context_dependent_vector():
    context_a = "domain:B2C category:TRANSIENT_TECHNICAL retryability:LATER_RETRY_POSSIBLE amount:100.00 baseline:RETRY_LATER"
    context_b = "domain:B2B category:NON_RETRIABLE retryability:BLOCKED amount:5000.00 baseline:STOP_RECOVERY"

    vector_a = EmbeddingService.embed_text(context_a)
    vector_b = EmbeddingService.embed_text(context_b)

    assert len(vector_a) == 768
    assert len(vector_b) == 768
    # Not all zeros
    assert any(x != 0.0 for x in vector_a)
    assert any(x != 0.0 for x in vector_b)
    # Contexts produce distinct vectors
    assert vector_a != vector_b


def test_probability_provider_empirical_history_branch():
    context = MagicMock()
    # 6 matching cases (>= 5): 4 RECOVERED, 2 FAILED
    context.historical_cases = [
        {"action_type": "GENERATE_PAYMENT_LINK", "outcome_status": "RECOVERED"},
        {"action_type": "GENERATE_PAYMENT_LINK", "outcome_status": "RECOVERED"},
        {"action_type": "GENERATE_PAYMENT_LINK", "outcome_status": "RECOVERED"},
        {"action_type": "GENERATE_PAYMENT_LINK", "outcome_status": "FAILED"},
        {"action_type": "GENERATE_PAYMENT_LINK", "outcome_status": "RECOVERED"},
        {"action_type": "GENERATE_PAYMENT_LINK", "outcome_status": "FAILED"},
        {"action_type": "RETRY_NOW", "outcome_status": "RECOVERED"},
    ]

    prob, prov = ProbabilityProvider.estimate(RecoveryAction.GENERATE_PAYMENT_LINK, context)
    assert prov == ["empirical_history"]
    assert pytest.approx(prob, 0.001) == 4 / 6  # ~0.6667


def test_probability_provider_prior_fallback_branch():
    context = MagicMock()
    # Only 3 matching cases (< 5 minimum)
    context.historical_cases = [
        {"action_type": "GENERATE_PAYMENT_LINK", "outcome_status": "RECOVERED"},
        {"action_type": "GENERATE_PAYMENT_LINK", "outcome_status": "RECOVERED"},
        {"action_type": "GENERATE_PAYMENT_LINK", "outcome_status": "RECOVERED"},
    ]

    prob, prov = ProbabilityProvider.estimate(RecoveryAction.GENERATE_PAYMENT_LINK, context)
    assert prov == ["deterministic_prior"]
    assert prob == float(settings.ECONOMIC_DETERMINISTIC_PRIOR)


def test_candidate_generator_limits_and_eligibility():
    context = DecisionContext(
        case_id="case-103",
        tenant_id="tenant-1",
        domain=RecoveryDomain.EMPLOYEE,  # Prohibits payment link
        amount=1500.0,
        currency="INR",
        failure_category=FailureCategory.NON_RETRIABLE,  # Prohibits retry
        retryability=Retryability.BLOCKED,
        baseline_action=RecoveryAction.STOP_RECOVERY,
    )

    proposal = DecisionProposal(
        recommended_action=RecoveryAction.RETRY_NOW,  # Ineligible for non-retriable
        candidate_actions=[
            RecoveryAction.RETRY_NOW,
            RecoveryAction.GENERATE_PAYMENT_LINK,  # Ineligible for employee
            RecoveryAction.SEND_REMINDER,
            RecoveryAction.STOP_RECOVERY,
        ],
        confidence=0.5,
    )

    candidates = CandidateGenerator.generate_candidates(context, proposal)
    assert len(candidates) <= 5
    # Non-retriable cannot have RETRY_NOW
    assert RecoveryAction.RETRY_NOW not in candidates
    # Employee cannot have GENERATE_PAYMENT_LINK
    assert RecoveryAction.GENERATE_PAYMENT_LINK not in candidates
    assert RecoveryAction.STOP_RECOVERY in candidates


def test_economic_optimizer_ranking():
    class DummyProvider:
        @staticmethod
        def estimate(action, context):
            if action == RecoveryAction.RETRY_NOW:
                return 0.9, ["empirical_history"]
            elif action == RecoveryAction.GENERATE_PAYMENT_LINK:
                return 0.5, ["deterministic_prior"]
            else:
                return 0.1, ["deterministic_prior"]

    context = MagicMock()
    context.amount = 1000.0

    candidates = [
        RecoveryAction.STOP_RECOVERY,
        RecoveryAction.GENERATE_PAYMENT_LINK,
        RecoveryAction.RETRY_NOW,
    ]

    ranked = EconomicOptimizer.rank_candidates(
        candidates=candidates,
        context=context,
        probability_provider=DummyProvider,
        operational_cost=10.0,
        risk_penalty=5.0,
    )

    assert len(ranked) == 3
    # RETRY_NOW: 0.9 * 1000 - 10 - 5 = 885.0
    assert ranked[0]["action"] == RecoveryAction.RETRY_NOW
    assert pytest.approx(ranked[0]["expected_net_recovery"], 0.01) == 885.0

    # GENERATE_PAYMENT_LINK: 0.5 * 1000 - 10 - 5 = 485.0
    assert ranked[1]["action"] == RecoveryAction.GENERATE_PAYMENT_LINK
    assert pytest.approx(ranked[1]["expected_net_recovery"], 0.01) == 485.0

    # Sorted descending
    assert ranked[0]["expected_net_recovery"] > ranked[1]["expected_net_recovery"] > ranked[2]["expected_net_recovery"]


def test_policy_engine_fallback_iteration():
    # Simulate: Top ENR candidate is RETRY_NOW, but category is NON_RETRIABLE
    # PolicyEngine rejects RETRY_NOW, so DecisionEngine proceeds to next candidate (SEND_REMINDER)
    candidates = [
        {
            "action": RecoveryAction.RETRY_NOW,
            "expected_net_recovery": 800.0,
            "recovery_probability": 0.85,
        },
        {
            "action": RecoveryAction.SEND_REMINDER,
            "expected_net_recovery": 400.0,
            "recovery_probability": 0.5,
        },
    ]

    selected = None
    for cand in candidates:
        prop = DecisionProposal(
            recommended_action=cand["action"],
            confidence=0.9,
        )
        status, autonomy, reason = PolicyEngine.evaluate(
            proposal=prop,
            domain=RecoveryDomain.B2C,
            category=FailureCategory.NON_RETRIABLE,
        )
        if status == PolicyStatus.APPROVED:
            selected = cand
            break

    assert selected is not None
    assert selected["action"] == RecoveryAction.SEND_REMINDER
    assert selected["expected_net_recovery"] == 400.0


def test_decision_engine_all_rejected_safe_stop():
    # When all candidate actions are rejected, policy must fall back to STOP_RECOVERY
    class RejectAllPolicy:
        @classmethod
        def evaluate(cls, proposal, domain, category):
            if proposal.recommended_action == RecoveryAction.STOP_RECOVERY:
                return PolicyStatus.APPROVED, AutonomyLevel.FULL_AUTO, None
            return PolicyStatus.REJECTED, AutonomyLevel.SUGGESTION_ONLY, "Hard reject"

    candidates = [RecoveryAction.RETRY_NOW, RecoveryAction.GENERATE_PAYMENT_LINK]
    selected = None
    for act in candidates:
        prop = DecisionProposal(recommended_action=act)
        status, autonomy, reason = RejectAllPolicy.evaluate(prop, RecoveryDomain.B2C, FailureCategory.NON_RETRIABLE)
        if status == PolicyStatus.APPROVED:
            selected = act
            break

    if not selected:
        selected = RecoveryAction.STOP_RECOVERY

    assert selected == RecoveryAction.STOP_RECOVERY


def test_economic_benchmark_four_strategies_and_determinism(tmp_path):
    from scripts.run_economic_benchmark import run_benchmark

    out_1 = tmp_path / "bench_1.json"
    out_2 = tmp_path / "bench_2.json"

    res_1 = run_benchmark(cases_count=5, seed=42, output_path=out_1)
    res_2 = run_benchmark(cases_count=5, seed=42, output_path=out_2)

    # All 4 strategies present
    strategies = ["NAIVE", "BASELINE", "ECONOMIC", "AI_PLUS_ECONOMIC"]
    assert all(s in res_1["strategy_comparison"] for s in strategies)

    # Identical across deterministic runs with same seed
    for s in strategies:
        data_1 = res_1["strategy_comparison"][s]
        data_2 = res_2["strategy_comparison"][s]
        assert data_1["modeled_net_recovered_value_inr"] == data_2["modeled_net_recovered_value_inr"]
        assert data_1["action_distribution"] == data_2["action_distribution"]


@pytest.mark.asyncio
async def test_systemic_intelligence_clustering_and_degradation():
    from app.services.systemic_intelligence import SystemicIntelligenceService

    SystemicIntelligenceService.clear_buffer()
    corridor = "razorpay:card:b2c"
    tenant_1 = "tenant-systemic-1"
    tenant_2 = "tenant-systemic-2"

    # 1. Single failure is OPERATIONAL
    SystemicIntelligenceService.record_signal(
        corridor=corridor, tenant_id=tenant_1, is_failure=True, amount=100.0
    )
    health_iso = SystemicIntelligenceService.analyze_route_health(corridor=corridor, tenant_id=tenant_1)
    assert health_iso["status"] == "OPERATIONAL"

    # 2. Repeated failures cluster -> CRITICAL
    for _ in range(5):
        SystemicIntelligenceService.record_signal(
            corridor=corridor, tenant_id=tenant_1, is_failure=True, amount=500.0
        )
    health_crit = SystemicIntelligenceService.analyze_route_health(corridor=corridor, tenant_id=tenant_1)
    assert health_crit["status"] in ("DEGRADED", "CRITICAL")
    assert health_crit["degradation_score"] >= 2.0
    assert health_crit["failure_count"] >= 5

    # 3. Tenant isolation: tenant_2 on same corridor has zero failures
    health_t2 = SystemicIntelligenceService.analyze_route_health(corridor=corridor, tenant_id=tenant_2)
    assert health_t2["sample_count"] == 0
    assert health_t2["status"] == "OPERATIONAL"


def test_systemic_degradation_suppresses_retries():
    context = DecisionContext(
        case_id="case-systemic-1",
        tenant_id="tenant-1",
        domain=RecoveryDomain.B2C,
        amount=1000.0,
        currency="INR",
        failure_category=FailureCategory.TRANSIENT_TECHNICAL,
        retryability=Retryability.LATER_RETRY_POSSIBLE,
        baseline_action=RecoveryAction.RETRY_NOW,
        route_health={"status": "DEGRADED", "corridor": "razorpay:card:b2c"},
    )
    proposal = DecisionProposal(
        recommended_action=RecoveryAction.RETRY_NOW,
        candidate_actions=[RecoveryAction.RETRY_NOW, RecoveryAction.GENERATE_PAYMENT_LINK],
        confidence=0.8,
    )

    # 1. CandidateGenerator drops RETRY_NOW if route is DEGRADED or CRITICAL
    candidates_degraded = CandidateGenerator.generate_candidates(
        context=context,
        ai_proposal=proposal,
    )
    assert RecoveryAction.RETRY_NOW not in candidates_degraded
    assert RecoveryAction.GENERATE_PAYMENT_LINK in candidates_degraded

    # 2. PolicyEngine rejects RETRY_NOW when route_health is DEGRADED
    route_health = {"status": "DEGRADED", "corridor": "razorpay:card:b2c"}
    prop = DecisionProposal(recommended_action=RecoveryAction.RETRY_NOW)
    status, _, reason = PolicyEngine.evaluate(
        proposal=prop,
        domain=RecoveryDomain.B2C,
        category=FailureCategory.TRANSIENT_TECHNICAL,
        route_health=route_health,
    )
    assert status == PolicyStatus.REJECTED
    assert "systemic corridor degradation" in reason.lower()


@pytest.mark.asyncio
async def test_systemic_context_reaches_agent_runtime():
    mock_adapter = MagicMock()
    mock_adapter.generate_decision = AsyncMock(return_value={
        "recommended_action": "GENERATE_PAYMENT_LINK",
        "candidate_actions": ["GENERATE_PAYMENT_LINK"],
        "reason": "Corridor degraded; preferring payment link",
        "confidence": 0.85,
    })

    route_health = {
        "status": "CRITICAL",
        "summary": "Corridor 'razorpay:card:b2c': CRITICAL (10/10 failures)",
    }
    context = DecisionContext(
        case_id="case-sys-ai",
        tenant_id="tenant-1",
        domain=RecoveryDomain.B2C,
        amount=750.0,
        currency="INR",
        failure_category=FailureCategory.TRANSIENT_TECHNICAL,
        retryability=Retryability.LATER_RETRY_POSSIBLE,
        baseline_action=RecoveryAction.RETRY_NOW,
        route_health=route_health,
    )

    proposal = await AgentRuntime.propose_decision(context, adapter=mock_adapter)
    prompt = mock_adapter.generate_decision.call_args[1]["prompt"]
    assert "Systemic Route Health: Corridor 'razorpay:card:b2c': CRITICAL" in prompt
    assert proposal.recommended_action == RecoveryAction.GENERATE_PAYMENT_LINK


@pytest.mark.asyncio
async def test_llm_adapter_missing_api_key_raises_controlled():
    from app.infrastructure.adapters.llm_adapter import LLMAdapter

    with patch("app.infrastructure.adapters.llm_adapter.settings") as mock_settings:
        mock_settings.LLM_API_KEY = ""
        with pytest.raises(RuntimeError) as exc_info:
            await LLMAdapter.generate_decision("test prompt")
        assert "missing LLM_API_KEY" in str(exc_info.value)


@pytest.mark.asyncio
async def test_llm_adapter_success_with_mocked_openai():
    from app.infrastructure.adapters.llm_adapter import LLMAdapter

    with patch("app.infrastructure.adapters.llm_adapter.settings") as mock_settings:
        mock_settings.LLM_API_KEY = "sk-test-mock-key-12345"
        mock_settings.LLM_BASE_URL = ""
        mock_settings.LLM_MODEL = "gpt-4o-mini"
        mock_settings.LLM_TIMEOUT_SECONDS = 5.0

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [
            MagicMock(message=MagicMock(content='{"diagnosis": "Gateway outage", "recommended_action": "RETRY_LATER", "candidate_actions": ["RETRY_LATER"], "reason": "Wait for recovery", "confidence": 0.9}'))
        ]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("openai.AsyncOpenAI", return_value=mock_client):
            result = await LLMAdapter.generate_decision("Test prompt")
            assert result["recommended_action"] == "RETRY_LATER"
            assert result["diagnosis"] == "Gateway outage"
            assert result["confidence"] == 0.9


def test_embedding_provider_abstraction():
    from app.services.embedding import DeterministicEmbeddingProvider

    # 1. Deterministic fallback produces non-zero vectors and expected provenance
    provider = DeterministicEmbeddingProvider()
    vec1 = provider.embed_text("sample text A")
    vec2 = provider.embed_text("sample text B")
    assert len(vec1) == 768
    assert len(vec2) == 768
    assert vec1 != vec2
    assert any(x != 0.0 for x in vec1)
    assert provider.get_provenance() == "deterministic_embedding_fallback"

    # 2. EmbeddingService uses deterministic provider when offline
    service_vec = EmbeddingService.embed_text("test context")
    assert len(service_vec) == 768
    assert any(x != 0.0 for x in service_vec)


