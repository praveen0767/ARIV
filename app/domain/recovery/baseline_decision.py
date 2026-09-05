import uuid
from datetime import datetime, timezone

try:
    from sqlalchemy import Column, String, Integer, DateTime, Enum, Boolean
    from sqlalchemy.dialects.postgresql import UUID
    from sqlalchemy.sql.schema import ForeignKey
    from sqlalchemy.sql import func
except Exception as e:
    import logging
    logging.getLogger("ariv.domain.baseline_decision").warning(
        "SQLAlchemy not available (%s); using dummy placeholders.", e
    )
    class _DummyColumn:
        def __init__(self, *args, **kwargs):
            pass
    Column = _DummyColumn
    String = _DummyColumn
    Integer = _DummyColumn
    DateTime = _DummyColumn
    Enum = _DummyColumn
    Boolean = _DummyColumn
    class _DummyUUID:
        def __init__(self, *args, **kwargs):
            pass
    UUID = _DummyUUID
    ForeignKey = lambda *args, **kwargs: None
    class _DummyFunc:
        @staticmethod
        def now():
            return None
    func = _DummyFunc

from app.domain.base import Base
from app.domain.decision import RecoveryAction

class BaselineDecision(Base):
    __tablename__ = "baseline_decision"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("recovery_case.id"), nullable=False)
    
    baseline_action = Column(Enum(RecoveryAction, name="recovery_action", create_type=False), nullable=False)
    policy_version = Column(String, nullable=False)
    expected_recovery_amount = Column(Integer, nullable=False) # minor units
    
    baseline_method = Column(String, nullable=True, default="deterministic_heuristic")
    provenance = Column(String, nullable=True, default="heuristic: 5% of case amount for retriable actions, 0 for STOP_RECOVERY; unvalidated estimate, not an empirical counterfactual")
    is_estimate = Column(Boolean, nullable=True, default=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    @property
    def baseline_policy_version(self) -> str:
        return self.policy_version

    @property
    def baseline_expected_recovery(self) -> int:
        return self.expected_recovery_amount
