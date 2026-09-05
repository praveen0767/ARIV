import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

try:
    from sqlalchemy import Column, String, Integer, DateTime, Enum, Interval, JSON
    from sqlalchemy.dialects.postgresql import UUID
    from sqlalchemy.orm import relationship
    from sqlalchemy.sql.schema import ForeignKey
    from sqlalchemy.sql import func
except Exception as e:
    import logging, enum, uuid
    logging.getLogger("ariv.domain.recovery_outcome").warning(
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
    Interval = _DummyColumn
    JSON = _DummyColumn
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

class RecoveryOutcomeStatus(enum.Enum):
    PENDING = "PENDING"
    RECOVERED = "RECOVERED"
    PARTIALLY_RECOVERED = "PARTIALLY_RECOVERED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"
    NO_RECOVERY = "NO_RECOVERY"

class RecoverySource(enum.Enum):
    ACTION_ATTRIBUTED = "ACTION_ATTRIBUTED"
    ORGANIC_RECOVERY = "ORGANIC_RECOVERY"
    BASELINE_RECOVERY = "BASELINE_RECOVERY"
    UNKNOWN_ATTRIBUTION = "UNKNOWN_ATTRIBUTION"
    UNKNOWN = "UNKNOWN_ATTRIBUTION"

class RecoveryOutcome(Base):
    __tablename__ = "recovery_outcome"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("recovery_case.id"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False)
    action_id = Column(UUID(as_uuid=True), ForeignKey("action.id"), nullable=True)
    
    outcome_status = Column(Enum(RecoveryOutcomeStatus, name="recovery_outcome_status"), nullable=False, default=RecoveryOutcomeStatus.PENDING)
    recovered_amount = Column(Integer, nullable=False, default=0)
    currency = Column(String(3), nullable=False, default="INR")
    recovered_at = Column(DateTime(timezone=True), nullable=True)
    provider_reference = Column(String, nullable=True)
    time_to_recovery = Column(Interval, nullable=True)
    recovery_source = Column(Enum(RecoverySource, name="recovery_source_type"), nullable=False, default=RecoverySource.UNKNOWN_ATTRIBUTION)


    
    # Lightweight attribution provenance
    attribution_decision = Column(String, nullable=True)
    attribution_provenance = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    @property
    def attribution_source(self) -> RecoverySource:
        """Alias separating outcome_status from attribution."""
        return self.recovery_source

    @property
    def recovered_amount_minor(self) -> int:
        return self.recovered_amount

    @recovered_amount_minor.setter
    def recovered_amount_minor(self, val: int):
        self.recovered_amount = val

