import uuid
from datetime import datetime, timezone

try:
    from sqlalchemy import Column, String, Integer, DateTime, Boolean
    from sqlalchemy.dialects.postgresql import UUID
    from sqlalchemy.sql.schema import ForeignKey
    from sqlalchemy.sql import func
    from sqlalchemy.orm import relationship
except Exception as e:
    import logging
    logging.getLogger("ariv.domain.recovery_measurement").warning(
        "SQLAlchemy not available (%s); using dummy placeholders.", e
    )
    class _DummyColumn:
        def __init__(self, *args, **kwargs):
            pass
    Column = _DummyColumn
    String = _DummyColumn
    Integer = _DummyColumn
    DateTime = _DummyColumn
    Boolean = _DummyColumn
    class _DummyUUID:
        def __init__(self, *args, **kwargs):
            pass
    UUID = _DummyUUID
    relationship = lambda *args, **kwargs: None
    ForeignKey = lambda *args, **kwargs: None
    class _DummyFunc:
        @staticmethod
        def now():
            return None
    func = _DummyFunc

from app.domain.base import Base

class RecoveryMeasurement(Base):
    __tablename__ = "recovery_measurement"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outcome_id = Column(UUID(as_uuid=True), ForeignKey("recovery_outcome.id"), nullable=False, unique=True)
    
    measurement_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    
    estimated_control_recovery = Column(Integer, nullable=True) # minor units (counterfactual estimate)
    treatment_recovery = Column(Integer, nullable=False, default=0) # minor units (observed recovery under treatment)
    control_recovery = Column(Integer, nullable=False, default=0) # minor units (observed recovery under control)
    incremental_recovery = Column(Integer, nullable=False, default=0) # minor units (incremental estimate)
    
    cost_of_recovery = Column(Integer, nullable=True) # minor units
    attribution_window_seconds = Column(Integer, nullable=False)
    
    experiment_id = Column(UUID(as_uuid=True), ForeignKey("experiment.id"), nullable=True)
    experiment_variant = Column(String(20), nullable=True) # "TREATMENT" or "CONTROL"
    baseline_policy_version = Column(String, nullable=True)
    baseline_method = Column(String, nullable=True, default="deterministic_heuristic")
    provenance = Column(String, nullable=True, default="heuristic: 5% of case amount; unvalidated estimate, not an empirical counterfactual")
    is_counterfactual_estimate = Column(Boolean, nullable=True, default=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    outcome = relationship("RecoveryOutcome")
    experiment = relationship("Experiment")

    @property
    def action_cost_minor(self) -> int:
        return self.cost_of_recovery or 0

    @property
    def incremental_recovery_minor(self) -> int:
        return self.incremental_recovery

    @property
    def incremental_recovery_estimate(self) -> int:
        return self.incremental_recovery

    @property
    def treatment_recovery_minor(self) -> int:
        return self.treatment_recovery

    @property
    def control_recovery_minor(self) -> int:
        return self.control_recovery

    @property
    def estimated_control_recovery_minor(self) -> int:
        return self.estimated_control_recovery or 0

    @property
    def baseline_expected_recovery(self) -> int:
        return self.estimated_control_recovery or 0

    @property
    def observed_recovery(self) -> int:
        if self.experiment_variant == "CONTROL":
            return self.control_recovery
        return self.treatment_recovery

