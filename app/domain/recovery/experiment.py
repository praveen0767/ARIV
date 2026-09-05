import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, DateTime, Enum, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql.schema import ForeignKey
from sqlalchemy.sql import func

from app.domain.base import Base

class ExperimentStatus(enum.Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    PAUSED = "PAUSED"

class Experiment(Base):
    __tablename__ = "experiment"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False)
    name = Column(String, nullable=False)
    status = Column(Enum(ExperimentStatus, name="experiment_status", create_type=False), nullable=False, default=ExperimentStatus.DRAFT)
    
    treatment_policy = Column(JSON, nullable=False)
    control_policy = Column(JSON, nullable=False)
    allocation_percentage = Column(Integer, nullable=False, default=50) # 0-100
    metric_definition = Column(JSON, nullable=False)
    
    start_at = Column(DateTime(timezone=True), nullable=True)
    end_at = Column(DateTime(timezone=True), nullable=True)
    policy_version = Column(String, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
