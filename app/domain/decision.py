import enum
import uuid
from sqlalchemy import Column, String, Enum, DateTime, ForeignKey, Float, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.domain.base import Base
from app.domain.tenant import Tenant
from app.domain.recovery_case import RecoveryCase

class AutonomyLevel(str, enum.Enum):
    FULL_AUTO = "FULL_AUTO"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"
    SUGGESTION_ONLY = "SUGGESTION_ONLY"

class RecoveryAction(str, enum.Enum):
    RETRY_NOW = "RETRY_NOW"
    RETRY_LATER = "RETRY_LATER"
    REQUEST_PAYMENT_METHOD_UPDATE = "REQUEST_PAYMENT_METHOD_UPDATE"
    GENERATE_PAYMENT_LINK = "GENERATE_PAYMENT_LINK"
    SEND_REMINDER = "SEND_REMINDER"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"
    WAIT = "WAIT"
    STOP_RECOVERY = "STOP_RECOVERY"

class PolicyStatus(str, enum.Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"

class DecisionRecord(Base):
    __tablename__ = "decision_record"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("recovery_case.id"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False)
    
    # Decisions
    proposed_action = Column(Enum(RecoveryAction), nullable=False)
    baseline_action = Column(Enum(RecoveryAction), nullable=False)
    
    # Metrics
    ai_confidence = Column(Float, nullable=True)
    expected_irv = Column(Float, nullable=True)
    
    # Policy evaluation
    policy_status = Column(Enum(PolicyStatus), nullable=False)
    autonomy_level = Column(Enum(AutonomyLevel), nullable=False)
    rejection_reason = Column(String, nullable=True)
    
    # Audit trail for provenance
    provenance = Column(JSON, nullable=False, default={})
    
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    case = relationship("RecoveryCase")
    tenant = relationship("Tenant")
