import enum
import uuid
# Optional import of SQLAlchemy components for environments without DB dependencies
try:
    from sqlalchemy import Column, String, Enum as SAEnum, DateTime, ForeignKey, JSON, Integer
    from sqlalchemy.dialects.postgresql import UUID as SAUUID
    from sqlalchemy.orm import relationship
    from sqlalchemy import Enum as SAEnum  # type: ignore
    from sqlalchemy.dialects.postgresql import UUID
except Exception as e:
    import logging
    logging.getLogger("ariv.domain.recovery_case").warning(
        "SQLAlchemy not available (%s); using dummy placeholders.", e
    )
    # Dummy placeholder definitions for SQLAlchemy column types when unavailable
    class _DummyColumn:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
        def __repr__(self):
            return f"_DummyColumn(args={self.args}, kwargs={self.kwargs})"
    Column = _DummyColumn
    String = _DummyColumn
    DateTime = _DummyColumn
    ForeignKey = _DummyColumn
    JSON = _DummyColumn
    Integer = _DummyColumn
    def _dummy_saenum(*args, **kwargs):
        # Return a dummy column placeholder for enum types
        return _DummyColumn(*args, **kwargs)
    SAEnum = _dummy_saenum
    SAUUID = uuid.UUID
    def _dummy_uuid(*args, **kwargs):
        # Accept any arguments such as as_uuid=True and return a placeholder value
        return 'dummy_uuid'
    UUID = _dummy_uuid
from datetime import datetime, timezone
relationship = lambda *args, **kwargs: None
from app.domain.base import Base
# Tenant may be unavailable without SQLAlchemy; guard import
try:
    from app.domain.tenant import Tenant
except Exception:
    Tenant = None

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

    domain = Column(SAEnum(RecoveryDomain), nullable=False)
    case_type = Column(SAEnum(CaseType), nullable=False)
    status = Column(SAEnum(CaseStatus), nullable=False, default=CaseStatus.OPEN)
    
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

