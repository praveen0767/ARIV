import enum
import uuid
from datetime import datetime, timezone

try:
    from sqlalchemy import Column, String, Integer, DateTime, Enum, JSON
    from sqlalchemy.dialects.postgresql import UUID, JSONB
    from sqlalchemy.sql.schema import ForeignKey
    from sqlalchemy.sql import func
except Exception as e:
    import logging
    logging.getLogger("ariv.domain.experiment").warning(
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
    JSON = _DummyColumn
    class _DummyUUID:
        def __init__(self, *args, **kwargs):
            pass
    UUID = _DummyUUID
    JSONB = _DummyUUID
    ForeignKey = lambda *args, **kwargs: None
    class _DummyFunc:
        @staticmethod
        def now():
            return None
    func = _DummyFunc

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
