from pydantic import BaseModel, Field
from typing import List, Optional
from app.domain.decision import RecoveryAction
from app.domain.recovery_case import RecoveryDomain
from app.domain.classification import FailureCategory, Retryability, Recoverability

class DecisionContext(BaseModel):
    """
    The deterministic context assembled for the LLM to reason over.
    """
    case_id: str
    tenant_id: str
    domain: RecoveryDomain
    
    # Financial context
    amount: float
    currency: str
    
    # Classification context
    failure_category: Optional[FailureCategory] = None
    retryability: Optional[Retryability] = None
    recoverability: Optional[Recoverability] = None
    
    # Historical context
    time_since_failure_seconds: int = 0
    intervention_count: int = 0
    
    # Enforced baseline for AI comparison
    baseline_action: Optional[RecoveryAction] = None
    
    # Retrieved Knowledge (RAG)
    historical_cases: List[dict] = Field(default_factory=list)
    playbook_snippets: List[dict] = Field(default_factory=list)


class DecisionProposal(BaseModel):
    """
    The STRICT schema that the LLM must output.
    """
    recommended_action: RecoveryAction
    reason: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    expected_irv: Optional[float] = None
    knowledge_refs: List[str] = Field(default_factory=list)
