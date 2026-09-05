"""
app/interfaces/provider.py

Typed, provider-agnostic payment execution interface.
Each provider operation is an explicit method.
Arbitrary HTTP, SQL, or generic execution methods are strictly prohibited.
"""

from abc import ABC, abstractmethod
from app.domain.provider import (
    CancelPaymentLinkRequest,
    CreatePaymentLinkRequest,
    FetchPaymentLinkRequest,
    FetchPaymentRequest,
    ProviderExecutionResult,
)


class PaymentProviderAdapter(ABC):
    """
    Abstract contract for payment provider adapters in ARIV.
    All operations must return normalized ProviderExecutionResult.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """The identifier of the payment provider (e.g. 'razorpay')."""
        pass

    @abstractmethod
    async def create_payment_link(
        self, request: CreatePaymentLinkRequest
    ) -> ProviderExecutionResult:
        """
        Creates a payment link via the provider.
        Mutating operation: requires valid idempotency_key.
        """
        pass

    @abstractmethod
    async def fetch_payment_link(
        self, request: FetchPaymentLinkRequest
    ) -> ProviderExecutionResult:
        """
        Fetches status of a payment link resource from the provider.
        Idempotent read operation for payment link reconciliation.
        """
        pass

    @abstractmethod
    async def fetch_payment(
        self, request: FetchPaymentRequest
    ) -> ProviderExecutionResult:
        """
        Fetches status of a payment resource from the provider.
        Idempotent read operation for payment transaction reconciliation.
        """
        pass

    @abstractmethod
    async def cancel_payment_link(
        self, request: CancelPaymentLinkRequest
    ) -> ProviderExecutionResult:
        """
        Cancels an active payment link on the provider.
        Mutating operation: requires valid idempotency_key.
        """
        pass
