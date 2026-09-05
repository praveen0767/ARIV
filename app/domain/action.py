import enum
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import Column, String, Enum, DateTime, ForeignKey, JSON, Boolean, Integer, Float, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.domain.base import Base
from app.domain.recovery_case import RecoveryCase
from app.domain.tenant import Tenant
from app.domain.decision import RecoveryAction


class ActionStatus(str, enum.Enum):
    PROPOSED = "PROPOSED"
    AUTHORIZED = "AUTHORIZED"
    QUEUED = "QUEUED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class OutboxStatus(str, enum.Enum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEAD_LETTERED = "DEAD_LETTERED"


class ExecutionStatus(str, enum.Enum):
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class Action(Base):
    __tablename__ = "action"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("recovery_case.id"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False)
    decision_id = Column(UUID(as_uuid=True), ForeignKey("decision_record.id"), nullable=False)

    action_type = Column(Enum(RecoveryAction), nullable=False)
    status = Column(Enum(ActionStatus), nullable=False, default=ActionStatus.PROPOSED)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # relationships
    case = relationship("RecoveryCase")
    decision = relationship("DecisionRecord")
    attempts = relationship("ExecutionAttempt", back_populates="action", cascade="all, delete-orphan")
    outbox = relationship("ExecutionOutbox", back_populates="action", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        Index('ix_action_unique', 'tenant_id', 'case_id', 'action_type', 'decision_id', unique=True),
    )


class ExecutionAttempt(Base):
    __tablename__ = "execution_attempt"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action_id = Column(UUID(as_uuid=True), ForeignKey("action.id"), nullable=False)
    attempt_number = Column(Integer, nullable=False)
    status = Column(Enum(ExecutionStatus), nullable=False)
    provider_request_id = Column(String, nullable=True)
    attempt_metadata = Column("metadata", JSON, nullable=True)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    action = relationship("Action", back_populates="attempts")

    __table_args__ = (
        Index('ix_execution_attempt_unique', 'action_id', 'attempt_number', unique=True),
    )


class ExecutionOutbox(Base):
    __tablename__ = "execution_outbox"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action_id = Column(UUID(as_uuid=True), ForeignKey("action.id"), nullable=False, unique=True)
    payload = Column(JSON, nullable=False)
    status = Column(Enum(OutboxStatus), nullable=False, default=OutboxStatus.PENDING)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    claimed_by = Column(String(255), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    last_error = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    dispatched = Column(Boolean, default=False, nullable=False)
    dispatched_at = Column(DateTime(timezone=True), nullable=True)

    action = relationship("Action", back_populates="outbox")

    __table_args__ = (
        Index('ix_execution_outbox_status_lease', 'status', 'lease_expires_at'),
    )
