"""
app/domain/provider.py

Domain models, typed request/response schemas, outcome normalization,
and exceptions for payment provider execution in ARIV.
"""

import enum
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field, field_validator, ConfigDict


class ProviderEnvironment(str, enum.Enum):
    SANDBOX = "SANDBOX"
    PRODUCTION = "PRODUCTION"


class ProviderCapability(str, enum.Enum):
    CREATE_PAYMENT_LINK = "CREATE_PAYMENT_LINK"
    FETCH_PAYMENT_LINK = "FETCH_PAYMENT_LINK"
    FETCH_PAYMENT = "FETCH_PAYMENT"
    CANCEL_PAYMENT_LINK = "CANCEL_PAYMENT_LINK"


class ProviderOutcomeStatus(str, enum.Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class RetrySafety(str, enum.Enum):
    SAFE_TO_RETRY = "SAFE_TO_RETRY"
    NOT_RETRIABLE = "NOT_RETRIABLE"
    UNKNOWN_RETRY_RISK = "UNKNOWN_RETRY_RISK"


class ProviderErrorCode(str, enum.Enum):
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    INVALID_REQUEST = "INVALID_REQUEST"
    PAYMENT_DECLINED = "PAYMENT_DECLINED"
    GATEWAY_ERROR = "GATEWAY_ERROR"
    TIMEOUT = "TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    UNKNOWN = "UNKNOWN"


class ProviderExecutionResult(BaseModel):
    """
    Provider-independent, normalized result model for all provider operations.
    """
    status: ProviderOutcomeStatus
    provider: str
    provider_request_id: Optional[str] = None
    provider_resource_id: Optional[str] = None
    provider_status: Optional[str] = None
    error_code: Optional[str] = None
    error_reason: Optional[str] = None
    retry_safety: RetrySafety
    raw_metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    idempotency_key: Optional[str] = None

    model_config = ConfigDict(frozen=True)


class CreatePaymentLinkRequest(BaseModel):
    """
    Typed request to generate a customer-facing payment link.
    Requires an explicit idempotency_key for safe mutation.
    """
    amount: int = Field(gt=0, description="Amount in smallest currency unit (e.g., paise for INR)")
    currency: str = Field(default="INR", min_length=3, max_length=3)
    description: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, description="Authoritative idempotency identity")
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    expire_by: Optional[int] = None
    notes: Dict[str, str] = Field(default_factory=dict)

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("idempotency_key must not be empty or whitespace")
        return v.strip()


class FetchPaymentLinkRequest(BaseModel):
    """
    Typed request to fetch the status of an existing payment link.
    Used for capability-specific reconciliation of CREATE_PAYMENT_LINK.
    """
    link_id: str = Field(min_length=1)
    idempotency_key: Optional[str] = None

    @field_validator("link_id")
    @classmethod
    def validate_link_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("link_id must not be empty or whitespace")
        return v.strip()


class FetchPaymentRequest(BaseModel):
    """
    Typed request to fetch status of an existing payment.
    Used for capability-specific reconciliation of direct payment captures/retries.
    """
    payment_id: str = Field(min_length=1)
    idempotency_key: Optional[str] = None

    @field_validator("payment_id")
    @classmethod
    def validate_payment_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("payment_id must not be empty or whitespace")
        return v.strip()


class CancelPaymentLinkRequest(BaseModel):
    """
    Typed request to cancel an issued payment link.
    """
    link_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)

    @field_validator("link_id", "idempotency_key")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field must not be empty or whitespace")
        return v.strip()


# Exceptions
class ProviderError(Exception):
    """Base exception for provider-level errors."""
    pass


class ProviderConfigurationError(ProviderError):
    """Raised when provider configuration is invalid or missing required secrets."""
    pass


class UnsupportedCapabilityError(ProviderError):
    """Raised when an operation is invoked that is not supported/enabled on the provider."""
    pass
