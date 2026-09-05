import pytest
import json
import os
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.classification import ClassificationService
from app.domain.classification import FailureCategory, Retryability, Recoverability
from app.domain.events import RiskEvent
from app.domain.recovery_case import RecoveryCase, CaseStatus
from app.domain.state_machine import CaseStateMachine, StateTransitionError

@pytest.fixture
def golden_fixtures():
    fixtures_path = os.path.join(os.path.dirname(__file__), 'fixtures', 'golden_failures.json')
    with open(fixtures_path, 'r') as f:
        return json.load(f)

@pytest.mark.asyncio
async def test_deterministic_classification(golden_fixtures):
    """Test all golden failure payloads map deterministically without LLM"""
    for fixture in golden_fixtures:
        # Mock Session and RiskEvent
        session = AsyncMock()
        session.add = MagicMock()
        risk_event = RiskEvent(case_id="dummy_case_id", canonical_payload=fixture["payload"])
        
        # Execute Classification
        classification = await ClassificationService.classify(session, risk_event)
        
        # Verify
        assert classification.failure_category.value == fixture["expected_category"], f"Failed on {fixture['id']}"
        assert classification.retryability.value == fixture["expected_retryability"], f"Failed on {fixture['id']}"
        assert classification.recoverability.value == fixture["expected_recoverability"], f"Failed on {fixture['id']}"
        assert classification.taxonomy_version == "1.0"
        
        # Ensure session.add was called to persist classification
        session.add.assert_called_once_with(classification)

def test_safe_state_transitions():
    """Test optimistic locking and terminal state protection"""
    case = RecoveryCase(status=CaseStatus.OPEN, version=1)
    
    # Valid transition
    CaseStateMachine.transition_to(case, CaseStatus.RISK_ASSESSED, expected_version=1)
    assert case.status == CaseStatus.RISK_ASSESSED
    assert case.version == 2
    
    # Invalid transition (Version mismatch)
    with pytest.raises(StateTransitionError, match="Version mismatch"):
        CaseStateMachine.transition_to(case, CaseStatus.PENDING_APPROVAL, expected_version=1)
        
    # Valid Terminal Transition
    CaseStateMachine.transition_to(case, CaseStatus.RECOVERED)
    assert case.status == CaseStatus.RECOVERED
    assert case.version == 3
    
    # Late Failure (Failure arriving after recovery)
    with pytest.raises(StateTransitionError, match="Cannot regress"):
        CaseStateMachine.transition_to(case, CaseStatus.FAILED)
    
    # State didn't change due to protection
    assert case.status == CaseStatus.RECOVERED
    assert case.version == 3

def test_tenant_isolation_rule():
    """
    Ensure we can't query or classify cross-tenant.
    In Phase 2, classification is stateless based on payload, but future Qdrant retrieval MUST enforce this.
    This test serves as a documentation marker that tenant boundaries are required in retrieval.
    """
    # Placeholder for when Qdrant Retrieval is added in Phase 3
    # The taxonomy classifier currently only uses the local event payload, 
    # which is inherently tenant-safe since the payload is tied to the Tenant's Case.
    pass
