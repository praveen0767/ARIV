"""
app/infrastructure/adapters/razorpay.py

Strict, typed Razorpay sandbox provider adapter for ARIV.
Handles credentials safety, idempotency mapping, outcome normalization,
and timeout/retry semantics without exposing arbitrary HTTP or SQL.
"""

import json
import logging
import re
from typing import Any, Dict, Optional, Set
import httpx

from app.domain.provider import (
    CancelPaymentLinkRequest,
    CreatePaymentLinkRequest,
    FetchPaymentLinkRequest,
    FetchPaymentRequest,
    ProviderCapability,
    ProviderEnvironment,
    ProviderErrorCode,
    ProviderExecutionResult,
    ProviderOutcomeStatus,
    ProviderConfigurationError,
    RetrySafety,
    UnsupportedCapabilityError,
)
from app.interfaces.provider import PaymentProviderAdapter

logger = logging.getLogger("ariv.infrastructure.adapters.razorpay")

# Sensitive fields to sanitize from logs/metadata
SENSITIVE_FIELD_PATTERNS = [
    re.compile(r"card", re.IGNORECASE),
    re.compile(r"cvv", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"pan", re.IGNORECASE),
    re.compile(r"account_number", re.IGNORECASE),
]


class RazorpayConfig:
    """
    Configuration model for Razorpay adapter.
    Enforces sandbox by default, strict URL checking, timeout validation,
    and credential secrecy.
    """

    def __init__(
        self,
        key_id: str,
        key_secret: str,
        environment: ProviderEnvironment = ProviderEnvironment.SANDBOX,
        base_url: str = "https://api.razorpay.com/v1",
        timeout_seconds: float = 10.0,
        enabled_capabilities: Optional[Set[ProviderCapability]] = None,
        allow_production: bool = False,
    ):
        if not key_id or not isinstance(key_id, str) or not key_id.strip():
            raise ProviderConfigurationError("Razorpay key_id must be a non-empty string.")
        if not key_secret or not isinstance(key_secret, str) or not key_secret.strip():
            raise ProviderConfigurationError("Razorpay key_secret must be a non-empty string.")

        if not base_url or not isinstance(base_url, str) or not (
            base_url.startswith("http://") or base_url.startswith("https://")
        ):
            raise ProviderConfigurationError(
                f"Razorpay base_url must be a valid HTTP/HTTPS URL, got: {base_url!r}"
            )

        if timeout_seconds <= 0:
            raise ProviderConfigurationError(
                f"Razorpay timeout_seconds must be positive, got: {timeout_seconds}"
            )

        if not isinstance(environment, ProviderEnvironment):
            try:
                environment = ProviderEnvironment(environment)
            except Exception:
                raise ProviderConfigurationError(
                    f"Unsupported environment: {environment}. Must be SANDBOX or PRODUCTION."
                )

        if environment == ProviderEnvironment.PRODUCTION and not allow_production:
            raise ProviderConfigurationError(
                "Production environment is disabled by default. "
                "Explicit allow_production=True is required to configure production Razorpay."
            )

        self.key_id = key_id.strip()
        self.key_secret = key_secret.strip()
        self.environment = environment
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        self.enabled_capabilities = enabled_capabilities or {
            ProviderCapability.CREATE_PAYMENT_LINK,
            ProviderCapability.FETCH_PAYMENT_LINK,
            ProviderCapability.FETCH_PAYMENT,
            ProviderCapability.CANCEL_PAYMENT_LINK,
        }
        self.allow_production = allow_production

    def __repr__(self) -> str:
        return (
            f"RazorpayConfig(environment={self.environment.value}, "
            f"base_url={self.base_url!r}, key_id={self.key_id!r}, "
            f"key_secret='[REDACTED]', timeout={self.timeout_seconds}s, "
            f"capabilities={[c.value for c in self.enabled_capabilities]})"
        )


class RazorpaySandboxAdapter(PaymentProviderAdapter):
    """
    Razorpay Provider Adapter implementation.
    Operates safely in sandbox mode, enforcing typed schemas and outcome normalization.
    """

    def __init__(
        self,
        config: RazorpayConfig,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.config = config
        self._custom_client = client

    @property
    def provider_name(self) -> str:
        return "razorpay"

    def _sanitize_metadata(self, data: Any) -> Any:
        """
        Recursively sanitizes responses to prevent any PAN/CVV/token leakage.
        """
        if isinstance(data, dict):
            clean = {}
            for k, v in data.items():
                if any(p.search(str(k)) for p in SENSITIVE_FIELD_PATTERNS):
                    clean[k] = "[REDACTED]"
                else:
                    clean[k] = self._sanitize_metadata(v)
            return clean
        elif isinstance(data, list):
            return [self._sanitize_metadata(item) for item in data]
        return data

    def _extract_request_id(self, response: Optional[httpx.Response], data: Optional[dict] = None) -> Optional[str]:
        if response is not None:
            req_id = response.headers.get("x-request-id") or response.headers.get("x-razorpay-request-id")
            if req_id:
                return req_id
        if data and isinstance(data, dict):
            return data.get("id") or data.get("razorpay_payment_id")
        return None

    def _extract_error_details(self, data: Any) -> tuple[str, str]:
        if isinstance(data, dict):
            error_obj = data.get("error")
            if isinstance(error_obj, dict):
                code = error_obj.get("code") or "PROVIDER_ERROR"
                desc = error_obj.get("description") or error_obj.get("reason") or "Unknown provider error"
                return str(code), str(desc)
            desc = data.get("description") or data.get("message") or str(data)
            return "PROVIDER_ERROR", str(desc)
        return "PROVIDER_ERROR", str(data) if data else "Unknown error"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._custom_client is not None:
            return self._custom_client
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.timeout_seconds),
            headers={"User-Agent": "ARIV-Recovery-Engine/1.0"},
        )

    async def create_payment_link(
        self, request: CreatePaymentLinkRequest
    ) -> ProviderExecutionResult:
        """
        Generates a payment link via Razorpay API.
        Idempotency key is mapped to 'X-Razorpay-Idempotency' header and metadata notes.
        """
        if ProviderCapability.CREATE_PAYMENT_LINK not in self.config.enabled_capabilities:
            raise UnsupportedCapabilityError(
                f"Capability {ProviderCapability.CREATE_PAYMENT_LINK.value} is not enabled."
            )

        if not request.idempotency_key or not request.idempotency_key.strip():
            raise ValueError("idempotency_key is required for create_payment_link")

        url = f"{self.config.base_url}/payment_links"
        headers = {
            "X-Razorpay-Idempotency": request.idempotency_key,
        }

        # Build clean, bounded payload
        payload: Dict[str, Any] = {
            "amount": request.amount,
            "currency": request.currency,
            "description": request.description,
            "notes": {**request.notes, "ariv_idempotency_key": request.idempotency_key},
        }

        if request.customer_name or request.customer_email or request.customer_phone:
            customer: Dict[str, str] = {}
            if request.customer_name:
                customer["name"] = request.customer_name
            if request.customer_email:
                customer["email"] = request.customer_email
            if request.customer_phone:
                customer["contact"] = request.customer_phone
            payload["customer"] = customer

        if request.expire_by:
            payload["expire_by"] = request.expire_by

        client = await self._get_client()
        should_close = self._custom_client is None

        try:
            logger.info(
                "Dispatching create_payment_link to Razorpay Sandbox: idempotency_key=%s, amount=%d %s",
                request.idempotency_key,
                request.amount,
                request.currency,
            )

            response = await client.post(
                url,
                json=payload,
                headers=headers,
                auth=(self.config.key_id, self.config.key_secret),
                timeout=self.config.timeout_seconds,
            )

            req_id = self._extract_request_id(response)

            try:
                resp_data = response.json()
            except Exception:
                logger.error("Failed to parse JSON response from Razorpay (status=%d)", response.status_code)
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.UNKNOWN,
                    provider=self.provider_name,
                    provider_request_id=req_id,
                    error_code=ProviderErrorCode.MALFORMED_RESPONSE.value,
                    error_reason=f"Malformed or non-JSON response from provider (HTTP {response.status_code})",
                    retry_safety=RetrySafety.UNKNOWN_RETRY_RISK,
                    idempotency_key=request.idempotency_key,
                )

            sanitized_data = self._sanitize_metadata(resp_data)

            # Success
            if response.status_code in (200, 201):
                resource_id = resp_data.get("id")
                provider_status = resp_data.get("status", "created")
                logger.info(
                    "Payment link created successfully: resource_id=%s, status=%s",
                    resource_id,
                    provider_status,
                )
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.SUCCEEDED,
                    provider=self.provider_name,
                    provider_request_id=req_id or resource_id,
                    provider_resource_id=resource_id,
                    provider_status=provider_status,
                    retry_safety=RetrySafety.NOT_RETRIABLE,
                    raw_metadata={
                        "short_url": sanitized_data.get("short_url"),
                        "status": provider_status,
                    },
                    idempotency_key=request.idempotency_key,
                )

            # Client Rejections (4xx)
            if response.status_code in (400, 422):
                code, reason = self._extract_error_details(resp_data)
                logger.warning("Deterministic rejection from Razorpay (%d): %s - %s", response.status_code, code, reason)
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.FAILED,
                    provider=self.provider_name,
                    provider_request_id=req_id,
                    error_code=ProviderErrorCode.INVALID_REQUEST.value,
                    error_reason=f"{code}: {reason}",
                    retry_safety=RetrySafety.NOT_RETRIABLE,
                    raw_metadata=sanitized_data,
                    idempotency_key=request.idempotency_key,
                )

            if response.status_code in (401, 403):
                code, reason = self._extract_error_details(resp_data)
                logger.error("Authentication/Authorization failed with Razorpay: %s - %s", code, reason)
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.FAILED,
                    provider=self.provider_name,
                    provider_request_id=req_id,
                    error_code=ProviderErrorCode.AUTHENTICATION_ERROR.value,
                    error_reason="Authentication failed with provider credentials",
                    retry_safety=RetrySafety.NOT_RETRIABLE,
                    raw_metadata=sanitized_data,
                    idempotency_key=request.idempotency_key,
                )

            if response.status_code == 429:
                logger.warning("Rate limit exceeded on Razorpay API (429)")
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.FAILED,
                    provider=self.provider_name,
                    provider_request_id=req_id,
                    error_code=ProviderErrorCode.RATE_LIMIT_EXCEEDED.value,
                    error_reason="Rate limit exceeded",
                    retry_safety=RetrySafety.SAFE_TO_RETRY,
                    raw_metadata=sanitized_data,
                    idempotency_key=request.idempotency_key,
                )

            # Server Errors (5xx) on mutating operations
            if response.status_code >= 500:
                logger.error("Provider server error (%d) during create_payment_link", response.status_code)
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.UNKNOWN,
                    provider=self.provider_name,
                    provider_request_id=req_id,
                    error_code=ProviderErrorCode.GATEWAY_ERROR.value,
                    error_reason=f"Provider server error (HTTP {response.status_code})",
                    retry_safety=RetrySafety.UNKNOWN_RETRY_RISK,
                    raw_metadata=sanitized_data,
                    idempotency_key=request.idempotency_key,
                )

            # Fallthrough unknown response
            return ProviderExecutionResult(
                status=ProviderOutcomeStatus.UNKNOWN,
                provider=self.provider_name,
                provider_request_id=req_id,
                error_code=ProviderErrorCode.UNKNOWN.value,
                error_reason=f"Unexpected response status: {response.status_code}",
                retry_safety=RetrySafety.UNKNOWN_RETRY_RISK,
                raw_metadata=sanitized_data,
                idempotency_key=request.idempotency_key,
            )

        except httpx.TimeoutException as exc:
            # Crucial: Network timeouts on mutating operations must be UNKNOWN
            logger.warning("Timeout waiting for Razorpay response on create_payment_link: %s", exc)
            return ProviderExecutionResult(
                status=ProviderOutcomeStatus.UNKNOWN,
                provider=self.provider_name,
                error_code=ProviderErrorCode.TIMEOUT.value,
                error_reason="Request timed out waiting for provider response",
                retry_safety=RetrySafety.UNKNOWN_RETRY_RISK,
                idempotency_key=request.idempotency_key,
            )

        except (httpx.ConnectError, httpx.NetworkError) as exc:
            logger.error("Network error communicating with Razorpay: %s", exc)
            return ProviderExecutionResult(
                status=ProviderOutcomeStatus.UNKNOWN,
                provider=self.provider_name,
                error_code=ProviderErrorCode.NETWORK_ERROR.value,
                error_reason=f"Network error: {type(exc).__name__}",
                retry_safety=RetrySafety.UNKNOWN_RETRY_RISK,
                idempotency_key=request.idempotency_key,
            )

        except Exception as exc:
            logger.exception("Unexpected error during create_payment_link: %s", exc)
            return ProviderExecutionResult(
                status=ProviderOutcomeStatus.UNKNOWN,
                provider=self.provider_name,
                error_code=ProviderErrorCode.UNKNOWN.value,
                error_reason=f"Unexpected adapter exception: {str(exc)}",
                retry_safety=RetrySafety.UNKNOWN_RETRY_RISK,
                idempotency_key=request.idempotency_key,
            )

        finally:
            if should_close:
                await client.aclose()

    async def fetch_payment_link(
        self, request: FetchPaymentLinkRequest
    ) -> ProviderExecutionResult:
        """
        Fetches payment link details by ID from Razorpay.
        Read-only idempotent operation for payment link reconciliation.
        """
        if ProviderCapability.FETCH_PAYMENT_LINK not in self.config.enabled_capabilities:
            raise UnsupportedCapabilityError(
                f"Capability {ProviderCapability.FETCH_PAYMENT_LINK.value} is not enabled."
            )

        if not request.link_id or not request.link_id.strip():
            raise ValueError("link_id is required for fetch_payment_link")

        url = f"{self.config.base_url}/payment_links/{request.link_id}"
        client = await self._get_client()
        should_close = self._custom_client is None

        try:
            logger.info("Fetching payment link from Razorpay: link_id=%s", request.link_id)

            response = await client.get(
                url,
                auth=(self.config.key_id, self.config.key_secret),
                timeout=self.config.timeout_seconds,
            )

            req_id = self._extract_request_id(response)

            try:
                resp_data = response.json()
            except Exception:
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.UNKNOWN,
                    provider=self.provider_name,
                    provider_request_id=req_id,
                    error_code=ProviderErrorCode.MALFORMED_RESPONSE.value,
                    error_reason=f"Malformed JSON in response (HTTP {response.status_code})",
                    retry_safety=RetrySafety.SAFE_TO_RETRY,
                    idempotency_key=request.idempotency_key,
                )

            sanitized_data = self._sanitize_metadata(resp_data)

            if response.status_code == 200:
                link_id = resp_data.get("id")
                link_status = resp_data.get("status")
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.SUCCEEDED,
                    provider=self.provider_name,
                    provider_request_id=req_id or link_id,
                    provider_resource_id=link_id,
                    provider_status=link_status,
                    retry_safety=RetrySafety.NOT_RETRIABLE,
                    raw_metadata={
                        "amount": sanitized_data.get("amount"),
                        "currency": sanitized_data.get("currency"),
                        "status": link_status,
                        "short_url": sanitized_data.get("short_url"),
                    },
                    idempotency_key=request.idempotency_key,
                )

            if response.status_code == 404:
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.FAILED,
                    provider=self.provider_name,
                    provider_request_id=req_id,
                    error_code=ProviderErrorCode.INVALID_REQUEST.value,
                    error_reason="Payment link resource not found",
                    retry_safety=RetrySafety.NOT_RETRIABLE,
                    raw_metadata=sanitized_data,
                    idempotency_key=request.idempotency_key,
                )

            if response.status_code in (401, 403):
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.FAILED,
                    provider=self.provider_name,
                    provider_request_id=req_id,
                    error_code=ProviderErrorCode.AUTHENTICATION_ERROR.value,
                    error_reason="Authentication failed with provider",
                    retry_safety=RetrySafety.NOT_RETRIABLE,
                    raw_metadata=sanitized_data,
                    idempotency_key=request.idempotency_key,
                )

            if response.status_code >= 500:
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.UNKNOWN,
                    provider=self.provider_name,
                    provider_request_id=req_id,
                    error_code=ProviderErrorCode.GATEWAY_ERROR.value,
                    error_reason=f"Provider server error (HTTP {response.status_code})",
                    retry_safety=RetrySafety.SAFE_TO_RETRY,
                    raw_metadata=sanitized_data,
                    idempotency_key=request.idempotency_key,
                )

            return ProviderExecutionResult(
                status=ProviderOutcomeStatus.UNKNOWN,
                provider=self.provider_name,
                provider_request_id=req_id,
                error_code=ProviderErrorCode.UNKNOWN.value,
                error_reason=f"Unexpected response status: {response.status_code}",
                retry_safety=RetrySafety.SAFE_TO_RETRY,
                raw_metadata=sanitized_data,
                idempotency_key=request.idempotency_key,
            )

        except httpx.TimeoutException:
            return ProviderExecutionResult(
                status=ProviderOutcomeStatus.UNKNOWN,
                provider=self.provider_name,
                error_code=ProviderErrorCode.TIMEOUT.value,
                error_reason="Request timed out fetching payment link",
                retry_safety=RetrySafety.SAFE_TO_RETRY,
                idempotency_key=request.idempotency_key,
            )

        except (httpx.ConnectError, httpx.NetworkError) as exc:
            return ProviderExecutionResult(
                status=ProviderOutcomeStatus.UNKNOWN,
                provider=self.provider_name,
                error_code=ProviderErrorCode.NETWORK_ERROR.value,
                error_reason=f"Network error: {type(exc).__name__}",
                retry_safety=RetrySafety.SAFE_TO_RETRY,
                idempotency_key=request.idempotency_key,
            )

        finally:
            if should_close:
                await client.aclose()

    async def fetch_payment(
        self, request: FetchPaymentRequest
    ) -> ProviderExecutionResult:
        """
        Fetches payment details by ID from Razorpay.
        Read-only idempotent operation.
        """
        if ProviderCapability.FETCH_PAYMENT not in self.config.enabled_capabilities:
            raise UnsupportedCapabilityError(
                f"Capability {ProviderCapability.FETCH_PAYMENT.value} is not enabled."
            )

        if not request.payment_id or not request.payment_id.strip():
            raise ValueError("payment_id is required for fetch_payment")

        url = f"{self.config.base_url}/payments/{request.payment_id}"
        client = await self._get_client()
        should_close = self._custom_client is None

        try:
            logger.info("Fetching payment from Razorpay: payment_id=%s", request.payment_id)

            response = await client.get(
                url,
                auth=(self.config.key_id, self.config.key_secret),
                timeout=self.config.timeout_seconds,
            )

            req_id = self._extract_request_id(response)

            try:
                resp_data = response.json()
            except Exception:
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.UNKNOWN,
                    provider=self.provider_name,
                    provider_request_id=req_id,
                    error_code=ProviderErrorCode.MALFORMED_RESPONSE.value,
                    error_reason=f"Malformed JSON in response (HTTP {response.status_code})",
                    retry_safety=RetrySafety.SAFE_TO_RETRY,  # Read is safe to retry
                    idempotency_key=request.idempotency_key,
                )

            sanitized_data = self._sanitize_metadata(resp_data)

            if response.status_code == 200:
                payment_id = resp_data.get("id")
                payment_status = resp_data.get("status")
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.SUCCEEDED,
                    provider=self.provider_name,
                    provider_request_id=req_id or payment_id,
                    provider_resource_id=payment_id,
                    provider_status=payment_status,
                    retry_safety=RetrySafety.NOT_RETRIABLE,
                    raw_metadata={
                        "amount": sanitized_data.get("amount"),
                        "currency": sanitized_data.get("currency"),
                        "status": payment_status,
                        "method": sanitized_data.get("method"),
                    },
                    idempotency_key=request.idempotency_key,
                )

            if response.status_code == 404:
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.FAILED,
                    provider=self.provider_name,
                    provider_request_id=req_id,
                    error_code=ProviderErrorCode.INVALID_REQUEST.value,
                    error_reason="Payment resource not found",
                    retry_safety=RetrySafety.NOT_RETRIABLE,
                    raw_metadata=sanitized_data,
                    idempotency_key=request.idempotency_key,
                )

            if response.status_code in (401, 403):
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.FAILED,
                    provider=self.provider_name,
                    provider_request_id=req_id,
                    error_code=ProviderErrorCode.AUTHENTICATION_ERROR.value,
                    error_reason="Authentication failed with provider",
                    retry_safety=RetrySafety.NOT_RETRIABLE,
                    raw_metadata=sanitized_data,
                    idempotency_key=request.idempotency_key,
                )

            if response.status_code == 429:
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.FAILED,
                    provider=self.provider_name,
                    provider_request_id=req_id,
                    error_code=ProviderErrorCode.RATE_LIMIT_EXCEEDED.value,
                    error_reason="Rate limit exceeded",
                    retry_safety=RetrySafety.SAFE_TO_RETRY,
                    raw_metadata=sanitized_data,
                    idempotency_key=request.idempotency_key,
                )

            # Server error on read operation is SAFE_TO_RETRY
            if response.status_code >= 500:
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.UNKNOWN,
                    provider=self.provider_name,
                    provider_request_id=req_id,
                    error_code=ProviderErrorCode.GATEWAY_ERROR.value,
                    error_reason=f"Provider server error (HTTP {response.status_code})",
                    retry_safety=RetrySafety.SAFE_TO_RETRY,
                    raw_metadata=sanitized_data,
                    idempotency_key=request.idempotency_key,
                )

            return ProviderExecutionResult(
                status=ProviderOutcomeStatus.UNKNOWN,
                provider=self.provider_name,
                provider_request_id=req_id,
                error_code=ProviderErrorCode.UNKNOWN.value,
                error_reason=f"Unexpected response status: {response.status_code}",
                retry_safety=RetrySafety.SAFE_TO_RETRY,
                raw_metadata=sanitized_data,
                idempotency_key=request.idempotency_key,
            )

        except httpx.TimeoutException:
            # Safe to retry for reads
            return ProviderExecutionResult(
                status=ProviderOutcomeStatus.UNKNOWN,
                provider=self.provider_name,
                error_code=ProviderErrorCode.TIMEOUT.value,
                error_reason="Request timed out fetching payment",
                retry_safety=RetrySafety.SAFE_TO_RETRY,
                idempotency_key=request.idempotency_key,
            )

        except (httpx.ConnectError, httpx.NetworkError) as exc:
            return ProviderExecutionResult(
                status=ProviderOutcomeStatus.UNKNOWN,
                provider=self.provider_name,
                error_code=ProviderErrorCode.NETWORK_ERROR.value,
                error_reason=f"Network error: {type(exc).__name__}",
                retry_safety=RetrySafety.SAFE_TO_RETRY,
                idempotency_key=request.idempotency_key,
            )

        finally:
            if should_close:
                await client.aclose()

    async def cancel_payment_link(
        self, request: CancelPaymentLinkRequest
    ) -> ProviderExecutionResult:
        """
        Cancels an existing payment link.
        Mutating operation: requires idempotency_key.
        """
        if ProviderCapability.CANCEL_PAYMENT_LINK not in self.config.enabled_capabilities:
            raise UnsupportedCapabilityError(
                f"Capability {ProviderCapability.CANCEL_PAYMENT_LINK.value} is not enabled."
            )

        if not request.idempotency_key or not request.idempotency_key.strip():
            raise ValueError("idempotency_key is required for cancel_payment_link")

        url = f"{self.config.base_url}/payment_links/{request.link_id}/cancel"
        headers = {
            "X-Razorpay-Idempotency": request.idempotency_key,
        }

        client = await self._get_client()
        should_close = self._custom_client is None

        try:
            logger.info("Cancelling payment link on Razorpay: link_id=%s", request.link_id)

            response = await client.post(
                url,
                headers=headers,
                auth=(self.config.key_id, self.config.key_secret),
                timeout=self.config.timeout_seconds,
            )

            req_id = self._extract_request_id(response)

            try:
                resp_data = response.json()
            except Exception:
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.UNKNOWN,
                    provider=self.provider_name,
                    provider_request_id=req_id,
                    error_code=ProviderErrorCode.MALFORMED_RESPONSE.value,
                    error_reason=f"Malformed JSON in response (HTTP {response.status_code})",
                    retry_safety=RetrySafety.UNKNOWN_RETRY_RISK,
                    idempotency_key=request.idempotency_key,
                )

            sanitized_data = self._sanitize_metadata(resp_data)

            if response.status_code == 200:
                resource_id = resp_data.get("id")
                status = resp_data.get("status", "cancelled")
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.SUCCEEDED,
                    provider=self.provider_name,
                    provider_request_id=req_id or resource_id,
                    provider_resource_id=resource_id,
                    provider_status=status,
                    retry_safety=RetrySafety.NOT_RETRIABLE,
                    raw_metadata=sanitized_data,
                    idempotency_key=request.idempotency_key,
                )

            if response.status_code in (400, 422):
                code, reason = self._extract_error_details(resp_data)
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.FAILED,
                    provider=self.provider_name,
                    provider_request_id=req_id,
                    error_code=ProviderErrorCode.INVALID_REQUEST.value,
                    error_reason=f"{code}: {reason}",
                    retry_safety=RetrySafety.NOT_RETRIABLE,
                    raw_metadata=sanitized_data,
                    idempotency_key=request.idempotency_key,
                )

            if response.status_code in (401, 403):
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.FAILED,
                    provider=self.provider_name,
                    provider_request_id=req_id,
                    error_code=ProviderErrorCode.AUTHENTICATION_ERROR.value,
                    error_reason="Authentication failed with provider",
                    retry_safety=RetrySafety.NOT_RETRIABLE,
                    raw_metadata=sanitized_data,
                    idempotency_key=request.idempotency_key,
                )

            if response.status_code >= 500:
                return ProviderExecutionResult(
                    status=ProviderOutcomeStatus.UNKNOWN,
                    provider=self.provider_name,
                    provider_request_id=req_id,
                    error_code=ProviderErrorCode.GATEWAY_ERROR.value,
                    error_reason=f"Provider server error (HTTP {response.status_code})",
                    retry_safety=RetrySafety.UNKNOWN_RETRY_RISK,
                    raw_metadata=sanitized_data,
                    idempotency_key=request.idempotency_key,
                )

            return ProviderExecutionResult(
                status=ProviderOutcomeStatus.UNKNOWN,
                provider=self.provider_name,
                provider_request_id=req_id,
                error_code=ProviderErrorCode.UNKNOWN.value,
                error_reason=f"Unexpected response status: {response.status_code}",
                retry_safety=RetrySafety.UNKNOWN_RETRY_RISK,
                raw_metadata=sanitized_data,
                idempotency_key=request.idempotency_key,
            )

        except httpx.TimeoutException:
            return ProviderExecutionResult(
                status=ProviderOutcomeStatus.UNKNOWN,
                provider=self.provider_name,
                error_code=ProviderErrorCode.TIMEOUT.value,
                error_reason="Request timed out cancelling payment link",
                retry_safety=RetrySafety.UNKNOWN_RETRY_RISK,
                idempotency_key=request.idempotency_key,
            )

        except (httpx.ConnectError, httpx.NetworkError) as exc:
            return ProviderExecutionResult(
                status=ProviderOutcomeStatus.UNKNOWN,
                provider=self.provider_name,
                error_code=ProviderErrorCode.NETWORK_ERROR.value,
                error_reason=f"Network error: {type(exc).__name__}",
                retry_safety=RetrySafety.UNKNOWN_RETRY_RISK,
                idempotency_key=request.idempotency_key,
            )

        finally:
            if should_close:
                await client.aclose()
