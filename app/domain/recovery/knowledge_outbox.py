"""app/domain/recovery/knowledge_outbox.py

Durable PostgreSQL-backed knowledge / vector index outbox for ARIV.
Architecturally decoupled from the financial ExecutionOutbox.

Guarantees:
- PostgreSQL durable persistence of vector indexing intent.
- Idempotent: exactly one outbox task per RecoveryMeasurement.
- Tenant-aware: tenant_id metadata stored directly on each record.
- Decoupled from financial execution: failures in Qdrant never roll back financial recovery.
"""

import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Integer, Index, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.domain.base import Base


class KnowledgeOutboxStatus(str, enum.Enum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEAD_LETTERED = "DEAD_LETTERED"


class KnowledgeOutbox(Base):
    __tablename__ = "knowledge_outbox"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False)
    measurement_id = Column(UUID(as_uuid=True), ForeignKey("recovery_measurement.id"), nullable=False, unique=True)
    payload = Column(JSON, nullable=False)
    status = Column(Enum(KnowledgeOutboxStatus), nullable=False, default=KnowledgeOutboxStatus.PENDING)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    last_error = Column(String, nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    claimed_by = Column(String(255), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    tenant = relationship("Tenant")
    measurement = relationship("RecoveryMeasurement")

    __table_args__ = (
        Index("ix_knowledge_outbox_status_lease", "status", "lease_expires_at"),
        Index("ix_knowledge_outbox_tenant", "tenant_id"),
    )
