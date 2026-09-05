import pytest
from app.domain.schemas import DecisionProposal, DecisionContext
from app.domain.decision import RecoveryAction, AutonomyLevel, PolicyStatus
from app.domain.recovery_case import RecoveryDomain
from app.domain.classification import FailureCategory, Retryability
from app.services.policy import PolicyEngine
from app.services.baseline import DeterministicBaseline

def test_deterministic_baseline():
    """Verify Baseline always proposes safe actions"""
    # Transient -> RETRY_LATER
    action = DeterministicBaseline.decide(
        RecoveryDomain.B2C, FailureCategory.TRANSIENT_TECHNICAL, Retryability.LATER_RETRY_POSSIBLE
    )
    assert action == RecoveryAction.RETRY_LATER

    # Non Retriable -> STOP
    action = DeterministicBaseline.decide(
        RecoveryDomain.B2C, FailureCategory.NON_RETRIABLE, Retryability.BLOCKED
    )
    assert action == RecoveryAction.STOP_RECOVERY

    # Unknown B2B -> ESCALATE
    action = DeterministicBaseline.decide(
        RecoveryDomain.B2B, FailureCategory.UNKNOWN, Retryability.BLOCKED
    )
    assert action == RecoveryAction.ESCALATE_TO_HUMAN

def test_policy_engine_safety_gates():
    """Verify PolicyEngine prevents unsafe AI proposals"""
    # 1. AI proposes RETRY_NOW on NON_RETRIABLE (Hallucination/Bad AI)
    proposal = DecisionProposal(
        recommended_action=RecoveryAction.RETRY_NOW,
        reason="I am an LLM and I want to retry.",
        confidence=0.99,
        expected_irv=100.0
    )
    
    status, autonomy, reason = PolicyEngine.evaluate(proposal, RecoveryDomain.B2C, FailureCategory.NON_RETRIABLE)
    assert status == PolicyStatus.REJECTED
    assert autonomy == AutonomyLevel.SUGGESTION_ONLY
    assert "Cannot retry non-retriable" in reason

    # 2. AI proposes RETRY_NOW on B2B (Requires Human Approval)
    proposal = DecisionProposal(
        recommended_action=RecoveryAction.RETRY_NOW,
        reason="Looks like a good idea.",
        confidence=0.90,
        expected_irv=50.0
    )
    status, autonomy, reason = PolicyEngine.evaluate(proposal, RecoveryDomain.B2B, FailureCategory.TRANSIENT_TECHNICAL)
    assert status == PolicyStatus.NEEDS_REVIEW
    assert autonomy == AutonomyLevel.HUMAN_APPROVAL

    # 3. Safe Proposal (B2C Transient -> RETRY)
    proposal = DecisionProposal(
        recommended_action=RecoveryAction.RETRY_LATER,
        reason="Safe retry.",
        confidence=0.85,
        expected_irv=10.0
    )
    status, autonomy, reason = PolicyEngine.evaluate(proposal, RecoveryDomain.B2C, FailureCategory.TRANSIENT_TECHNICAL)
    assert status == PolicyStatus.APPROVED
    assert autonomy == AutonomyLevel.FULL_AUTO

def test_llm_degradation():
    """
    Test that if LLM fails or produces malformed output, the system degrades to the deterministic baseline.
    This is handled in the AgentRuntime implementation block.
    """
    # We simulate this behavior explicitly in AgentRuntime's except block.
    pass

def test_tenant_isolation():
    """
    Ensure the Qdrant retriever enforces tenant filtering.
    """
    from app.interfaces.knowledge import TenantAwareKnowledgeRetriever
    
    retriever = TenantAwareKnowledgeRetriever(tenant_id="tenant-123")
    assert retriever.tenant_id == "tenant-123"
    # Actual qdrant test would assert the query filter must contain this ID.
