import enum
import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.domain.base import Base
from app.domain.recovery_case import RecoveryCase

class ProviderEvent(Base):
    __tablename__ = "provider_event"
    __table_args__ = (
        UniqueConstraint('provider', 'external_id', name='uix_provider_external_id'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider = Column(String, nullable=False) # e.g., 'razorpay'
    external_id = Column(String, nullable=False) # e.g., x-razorpay-event-id
    payload = Column(JSON, nullable=False)
    idempotency_key = Column(String, nullable=False, unique=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

class RiskEvent(Base):
    __tablename__ = "risk_event"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("recovery_case.id"), nullable=False)
    canonical_payload = Column(JSON, nullable=False)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    case = relationship("RecoveryCase")

class AuditEventType(str, enum.Enum):
    CASE_CREATED = "CASE_CREATED"
    WEBHOOK_RECEIVED = "WEBHOOK_RECEIVED"
    STATE_TRANSITION = "STATE_TRANSITION"

class AuditEvent(Base):
    __tablename__ = "audit_event"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("recovery_case.id"), nullable=True) # nullable for system events
    event_type = Column(String, nullable=False)
    details = Column(JSON, nullable=False)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    case = relationship("RecoveryCase")
