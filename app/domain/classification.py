import enum
import uuid
from sqlalchemy import Column, String, Enum, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.domain.base import Base

class FailureCategory(str, enum.Enum):
    TRANSIENT_TECHNICAL = "TRANSIENT_TECHNICAL"
    CUSTOMER_ACTION_REQUIRED = "CUSTOMER_ACTION_REQUIRED"
    PAYMENT_METHOD_PROBLEM = "PAYMENT_METHOD_PROBLEM"
    PROVIDER_DEGRADATION = "PROVIDER_DEGRADATION"
    MERCHANT_CONFIGURATION = "MERCHANT_CONFIGURATION"
    RISK_OR_FRAUD = "RISK_OR_FRAUD"
    NON_RETRIABLE = "NON_RETRIABLE"
    UNKNOWN = "UNKNOWN"

class Retryability(str, enum.Enum):
    IMMEDIATE_RETRY_POSSIBLE = "IMMEDIATE_RETRY_POSSIBLE"
    LATER_RETRY_POSSIBLE = "LATER_RETRY_POSSIBLE"
    REQUIRES_NEW_METHOD = "REQUIRES_NEW_METHOD"
    BLOCKED = "BLOCKED"

class Recoverability(str, enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"

class RecoveryClassification(Base):
    __tablename__ = "recovery_classification"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("recovery_case.id"), nullable=False)
    failure_category = Column(Enum(FailureCategory), nullable=False)
    retryability = Column(Enum(Retryability), nullable=False)
    recoverability = Column(Enum(Recoverability), nullable=False)
    taxonomy_version = Column(String, nullable=False, default="1.0")
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    case = relationship("RecoveryCase")
