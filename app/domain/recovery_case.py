import enum
import uuid
from sqlalchemy import Column, String, Enum, DateTime, ForeignKey, JSON, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.domain.base import Base
from app.domain.tenant import Tenant

class RecoveryDomain(str, enum.Enum):
    B2C = "B2C"
    B2B = "B2B"
    EMPLOYEE = "EMPLOYEE"
    PLATFORM = "PLATFORM"
    PARTNER = "PARTNER"

class CaseType(str, enum.Enum):
    INVOICE_OVERDUE = "INVOICE_OVERDUE"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    ACQUIRER_DEGRADATION = "ACQUIRER_DEGRADATION"

class CaseStatus(str, enum.Enum):
    OPEN = "OPEN"
    RISK_ASSESSED = "RISK_ASSESSED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    RECOVERED = "RECOVERED"
    FAILED = "FAILED"
    CLOSED = "CLOSED"

class RecoveryCase(Base):

    __tablename__ = "recovery_case"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False)

    domain = Column(Enum(RecoveryDomain), nullable=False)
    case_type = Column(Enum(CaseType), nullable=False)
    status = Column(Enum(CaseStatus), nullable=False, default=CaseStatus.OPEN)
    
    # Optimistic locking version
    version = Column(Integer, nullable=False, default=1)

    __mapper_args__ = {
        "version_id_col": version
    }

    
    # Authoritative monetary amount in minor units (e.g., paise, cents)
    amount_minor = Column(Integer, nullable=True)
    
    # Simple JSONB context for Phase 1
    context = Column(JSON, nullable=False, default={})
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    tenant = relationship("Tenant")

    @property
    def amount(self) -> int:
        """Accessor for case monetary amount in minor units."""
        if self.amount_minor is not None:
            return self.amount_minor
        if hasattr(self, "_amount") and self._amount is not None:
            return self._amount
        if self.context and isinstance(self.context, dict):
            return self.context.get("amount_minor", self.context.get("amount", 0))
        return 0

    @amount.setter
    def amount(self, value: int):
        self.amount_minor = value
        self._amount = value
        if self.context is None:
            self.context = {}
        if isinstance(self.context, dict):
            self.context["amount_minor"] = value
            self.context["amount"] = value

