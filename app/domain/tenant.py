import enum
import uuid
from sqlalchemy import Column, String, JSON, Enum, DateTime
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timezone
from app.domain.base import Base

class TenantType(str, enum.Enum):
    ENTERPRISE = "ENTERPRISE"
    CONSUMER = "CONSUMER"
    PARTNER = "PARTNER"
    INTERNAL = "INTERNAL"
    PLATFORM = "PLATFORM"

class Tenant(Base):
    __tablename__ = "tenant"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type = Column(Enum(TenantType), nullable=False)
    name = Column(String, nullable=False)
    config = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
