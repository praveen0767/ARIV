import enum
import uuid
try:
    from sqlalchemy import Column, String, JSON, Enum, DateTime
    from sqlalchemy.dialects.postgresql import UUID
except Exception as e:
        import logging, enum, uuid
        logging.getLogger("ariv.domain.tenant").warning(
            "SQLAlchemy not available (%s); using dummy placeholders.", e
        )
        class _DummyColumn:
            def __init__(self, *args, **kwargs):
                pass
        Column = _DummyColumn
        String = _DummyColumn
        JSON = _DummyColumn
        Enum = _DummyColumn
        DateTime = _DummyColumn
        class _DummyUUID:
            def __init__(self, *args, **kwargs):
                pass
        UUID = _DummyUUID
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
