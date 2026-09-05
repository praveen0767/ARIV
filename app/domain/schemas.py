try:
    from pydantic import BaseModel, Field
except Exception as e:
    import logging
    logging.getLogger("ariv.domain.schemas").warning(
        "pydantic not available (%s); using dummy BaseModel and Field.", e
    )
    class BaseModel:
        def __init__(self, **data):
            for key, value in data.items():
                setattr(self, key, value)
        def dict(self):
            return self.__dict__
    def Field(*, default_factory=None, **kwargs):
        # Return the default value if a default_factory is provided, else None
        if default_factory is not None:
            return default_factory()
        return None
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

    # Systemic Corridor & Route Health Context
    route_health: Optional[dict] = None


class DecisionProposal(BaseModel):
    """
    The STRICT schema that the LLM must output.
    """
    diagnosis: Optional[str] = None
    recommended_action: RecoveryAction
    candidate_actions: List[RecoveryAction] = Field(default_factory=list)
    reason: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    expected_irv: Optional[float] = None
    knowledge_refs: List[str] = Field(default_factory=list)
