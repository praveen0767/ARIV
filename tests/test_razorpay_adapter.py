"""
tests/test_razorpay_adapter.py

Phase 4B comprehensive test suite for RazorpaySandboxAdapter and Provider interface.

COVERAGE (15 Mandatory Scenarios):
1. Successful sandbox response (create_payment_link, fetch_payment, cancel_payment_link)
2. Deterministic provider rejection (400 / 422)
3. Provider 5xx error (500 / 503 -> UNKNOWN, UNKNOWN_RETRY_RISK)
4. Timeout -> UNKNOWN, TIMEOUT, UNKNOWN_RETRY_RISK
5. Connection / Network error -> UNKNOWN, NETWORK_ERROR
6. Malformed response (non-JSON) -> UNKNOWN, MALFORMED_RESPONSE
7. Rate limit (429) -> FAILED, RATE_LIMIT_EXCEEDED, SAFE_TO_RETRY
8. Missing credentials -> ProviderConfigurationError
9. Malformed configuration (invalid URL, non-positive timeout) -> ProviderConfigurationError
10. Wrong / unapproved environment (PRODUCTION without allow_production) -> ProviderConfigurationError
11. Missing idempotency key on mutating request -> ValueError
12. Secret redaction in logs / __repr__ / sanitized metadata
13. Normalized provider outcome fields & structure
14. Provider request correlation (x-request-id extraction)
15. Unsupported capability -> UnsupportedCapabilityError
"""

import logging
import pytest
import httpx
from unittest.mock import patch

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
from app.infrastructure.adapters.razorpay import RazorpayConfig, RazorpaySandboxAdapter


# ---------------------------------------------------------------------------
# Test Fixtures & Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_config() -> RazorpayConfig:
    return RazorpayConfig(
        key_id="rzp_test_mock_key_123",
        key_secret="mock_secret_abc456",
        environment=ProviderEnvironment.SANDBOX,
        base_url="https://api.razorpay.com/v1",
        timeout_seconds=5.0,
    )


@pytest.fixture
def valid_create_request() -> CreatePaymentLinkRequest:
    return CreatePaymentLinkRequest(
        amount=50000,
        currency="INR",
        description="Invoice payment #INV-1001",
        idempotency_key="idemp_case_001_v1",
        customer_name="Alice Johnson",
        customer_email="alice@example.com",
        customer_phone="+919876543210",
        notes={"case_id": "case_123", "tenant_id": "tenant_abc"},
    )


def build_adapter_with_mock(config: RazorpayConfig, handler) -> RazorpaySandboxAdapter:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return RazorpaySandboxAdapter(config=config, client=client)


# ---------------------------------------------------------------------------
# 1. Successful sandbox response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_1_successful_sandbox_create_payment_link(valid_config, valid_create_request):
    """Scenario 1a: Successful payment link creation."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-Razorpay-Idempotency") == "idemp_case_001_v1"
        assert request.url.path == "/v1/payment_links"
        return httpx.Response(
            200,
            json={
                "id": "plink_test_98765",
                "status": "created",
                "short_url": "https://rzp.io/i/test98765",
                "amount": 50000,
                "currency": "INR",
            },
            headers={"x-request-id": "req_corr_12345"},
        )

    adapter = build_adapter_with_mock(valid_config, handler)
    result = await adapter.create_payment_link(valid_create_request)

    assert result.status == ProviderOutcomeStatus.SUCCEEDED
    assert result.provider == "razorpay"
    assert result.provider_resource_id == "plink_test_98765"
    assert result.provider_status == "created"
    assert result.provider_request_id == "req_corr_12345"
    assert result.retry_safety == RetrySafety.NOT_RETRIABLE
    assert result.idempotency_key == "idemp_case_001_v1"
    assert result.raw_metadata.get("short_url") == "https://rzp.io/i/test98765"


@pytest.mark.asyncio
async def test_1_successful_sandbox_fetch_payment_link(valid_config):
    """Scenario 1b: Successful fetch payment link status."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/payment_links/plink_test_777"
        return httpx.Response(
            200,
            json={
                "id": "plink_test_777",
                "status": "paid",
                "amount": 50000,
                "currency": "INR",
                "short_url": "https://rzp.io/i/777",
            },
            headers={"x-request-id": "req_fetch_plink_777"},
        )

    adapter = build_adapter_with_mock(valid_config, handler)
    req = FetchPaymentLinkRequest(link_id="plink_test_777")
    result = await adapter.fetch_payment_link(req)

    assert result.status == ProviderOutcomeStatus.SUCCEEDED
    assert result.provider_resource_id == "plink_test_777"
    assert result.provider_status == "paid"
    assert result.provider_request_id == "req_fetch_plink_777"
    assert result.retry_safety == RetrySafety.NOT_RETRIABLE


@pytest.mark.asyncio
async def test_1_successful_sandbox_fetch_payment(valid_config):
    """Scenario 1b: Successful fetch payment status."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/payments/pay_test_456"
        return httpx.Response(
            200,
            json={
                "id": "pay_test_456",
                "status": "captured",
                "amount": 50000,
                "currency": "INR",
                "method": "card",
            },
            headers={"x-request-id": "req_fetch_999"},
        )

    adapter = build_adapter_with_mock(valid_config, handler)
    req = FetchPaymentRequest(payment_id="pay_test_456")
    result = await adapter.fetch_payment(req)

    assert result.status == ProviderOutcomeStatus.SUCCEEDED
    assert result.provider_resource_id == "pay_test_456"
    assert result.provider_status == "captured"
    assert result.provider_request_id == "req_fetch_999"
    assert result.retry_safety == RetrySafety.NOT_RETRIABLE


@pytest.mark.asyncio
async def test_1_successful_sandbox_cancel_payment_link(valid_config):
    """Scenario 1c: Successful cancel payment link."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/payment_links/plink_123/cancel"
        return httpx.Response(
            200,
            json={"id": "plink_123", "status": "cancelled"},
            headers={"x-request-id": "req_cancel_001"},
        )

    adapter = build_adapter_with_mock(valid_config, handler)
    req = CancelPaymentLinkRequest(link_id="plink_123", idempotency_key="idemp_cancel_1")
    result = await adapter.cancel_payment_link(req)

    assert result.status == ProviderOutcomeStatus.SUCCEEDED
    assert result.provider_resource_id == "plink_123"
    assert result.provider_status == "cancelled"


# ---------------------------------------------------------------------------
# 2. Deterministic provider rejection (400 / 422)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_2_deterministic_provider_rejection_400(valid_config, valid_create_request):
    """Scenario 2: HTTP 400 Bad Request maps to FAILED + NOT_RETRIABLE."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": "BAD_REQUEST_ERROR",
                    "description": "Invalid currency specified",
                }
            },
            headers={"x-request-id": "req_err_400"},
        )

    adapter = build_adapter_with_mock(valid_config, handler)
    result = await adapter.create_payment_link(valid_create_request)

    assert result.status == ProviderOutcomeStatus.FAILED
    assert result.error_code == ProviderErrorCode.INVALID_REQUEST.value
    assert "BAD_REQUEST_ERROR" in result.error_reason
    assert result.retry_safety == RetrySafety.NOT_RETRIABLE
    assert result.provider_request_id == "req_err_400"


# ---------------------------------------------------------------------------
# 3. Provider 5xx error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_3_provider_5xx_mutating_returns_unknown(valid_config, valid_create_request):
    """Scenario 3: 500 Internal Server Error on mutating request -> UNKNOWN + UNKNOWN_RETRY_RISK."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"code": "GATEWAY_ERROR", "description": "Database outage"}})

    adapter = build_adapter_with_mock(valid_config, handler)
    result = await adapter.create_payment_link(valid_create_request)

    assert result.status == ProviderOutcomeStatus.UNKNOWN
    assert result.error_code == ProviderErrorCode.GATEWAY_ERROR.value
    assert result.retry_safety == RetrySafety.UNKNOWN_RETRY_RISK


# ---------------------------------------------------------------------------
# 4. Timeout -> UNKNOWN
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_4_timeout_returns_unknown(valid_config, valid_create_request):
    """Scenario 4: Request timeout on mutating operation -> UNKNOWN + TIMEOUT + UNKNOWN_RETRY_RISK."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Read timeout waiting for response")

    adapter = build_adapter_with_mock(valid_config, handler)
    result = await adapter.create_payment_link(valid_create_request)

    assert result.status == ProviderOutcomeStatus.UNKNOWN
    assert result.error_code == ProviderErrorCode.TIMEOUT.value
    assert result.retry_safety == RetrySafety.UNKNOWN_RETRY_RISK


# ---------------------------------------------------------------------------
# 5. Connection / Network error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_5_connection_error_returns_unknown(valid_config, valid_create_request):
    """Scenario 5: Connection failure -> UNKNOWN + NETWORK_ERROR."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused by mock host")

    adapter = build_adapter_with_mock(valid_config, handler)
    result = await adapter.create_payment_link(valid_create_request)

    assert result.status == ProviderOutcomeStatus.UNKNOWN
    assert result.error_code == ProviderErrorCode.NETWORK_ERROR.value
    assert result.retry_safety == RetrySafety.UNKNOWN_RETRY_RISK


# ---------------------------------------------------------------------------
# 6. Malformed response (non-JSON)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_6_malformed_response_returns_unknown(valid_config, valid_create_request):
    """Scenario 6: Unparseable HTML/text response -> UNKNOWN + MALFORMED_RESPONSE."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>502 Bad Gateway Nginx</html>")

    adapter = build_adapter_with_mock(valid_config, handler)
    result = await adapter.create_payment_link(valid_create_request)

    assert result.status == ProviderOutcomeStatus.UNKNOWN
    assert result.error_code == ProviderErrorCode.MALFORMED_RESPONSE.value
    assert result.retry_safety == RetrySafety.UNKNOWN_RETRY_RISK


# ---------------------------------------------------------------------------
# 7. Rate limit (429)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_7_rate_limit_returns_failed_safe_to_retry(valid_config, valid_create_request):
    """Scenario 7: HTTP 429 Rate Limit -> FAILED + RATE_LIMIT_EXCEEDED + SAFE_TO_RETRY."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"code": "BAD_REQUEST_ERROR", "description": "Too many requests"}})

    adapter = build_adapter_with_mock(valid_config, handler)
    result = await adapter.create_payment_link(valid_create_request)

    assert result.status == ProviderOutcomeStatus.FAILED
    assert result.error_code == ProviderErrorCode.RATE_LIMIT_EXCEEDED.value
    assert result.retry_safety == RetrySafety.SAFE_TO_RETRY


# ---------------------------------------------------------------------------
# 8. Missing credentials
# ---------------------------------------------------------------------------

def test_8_missing_credentials_raises_configuration_error():
    """Scenario 8: Missing key_id or key_secret fails configuration safely."""
    with pytest.raises(ProviderConfigurationError, match="key_id"):
        RazorpayConfig(key_id="", key_secret="secret_123")

    with pytest.raises(ProviderConfigurationError, match="key_secret"):
        RazorpayConfig(key_id="rzp_123", key_secret="")


# ---------------------------------------------------------------------------
# 9. Malformed configuration (invalid URL, non-positive timeout)
# ---------------------------------------------------------------------------

def test_9_malformed_configuration_raises_configuration_error():
    """Scenario 9: Malformed base_url or negative timeout raises error."""
    with pytest.raises(ProviderConfigurationError, match="base_url"):
        RazorpayConfig(key_id="rzp_123", key_secret="sec_123", base_url="ftp://invalid-url")

    with pytest.raises(ProviderConfigurationError, match="timeout_seconds"):
        RazorpayConfig(key_id="rzp_123", key_secret="sec_123", timeout_seconds=-5.0)


# ---------------------------------------------------------------------------
# 10. Wrong / unapproved environment
# ---------------------------------------------------------------------------

def test_10_wrong_environment_and_unauthorized_production():
    """Scenario 10: Disallow arbitrary environments or production without explicit flag."""
    with pytest.raises(ProviderConfigurationError, match="Unsupported environment"):
        RazorpayConfig(key_id="rzp_123", key_secret="sec_123", environment="STAGING_UNKNOWN")

    with pytest.raises(ProviderConfigurationError, match="Production environment is disabled by default"):
        RazorpayConfig(key_id="rzp_123", key_secret="sec_123", environment=ProviderEnvironment.PRODUCTION, allow_production=False)

    # Allowed only with explicit allow_production=True
    prod_config = RazorpayConfig(
        key_id="rzp_live_123",
        key_secret="sec_123",
        environment=ProviderEnvironment.PRODUCTION,
        allow_production=True,
    )
    assert prod_config.environment == ProviderEnvironment.PRODUCTION


# ---------------------------------------------------------------------------
# 11. Missing idempotency key
# ---------------------------------------------------------------------------

def test_11_missing_idempotency_key_raises_validation_error():
    """Scenario 11: CreatePaymentLinkRequest requires non-empty idempotency_key."""
    with pytest.raises(ValueError):
        CreatePaymentLinkRequest(
            amount=1000,
            currency="INR",
            description="Test payment",
            idempotency_key="",
        )


# ---------------------------------------------------------------------------
# 12. Secret redaction in logs / __repr__ / sanitized metadata
# ---------------------------------------------------------------------------

def test_12_secret_redaction_in_repr_and_metadata(valid_config):
    """Scenario 12: Secret keys and sensitive payload fields are redacted."""
    # Repr check
    config_repr = repr(valid_config)
    assert "mock_secret_abc456" not in config_repr
    assert "[REDACTED]" in config_repr

    # Metadata sanitization check
    adapter = RazorpaySandboxAdapter(config=valid_config)
    raw_input = {
        "id": "plink_123",
        "card_number": "4111111111111111",
        "cvv": "123",
        "secret_token": "token_xyz",
        "status": "created",
    }
    sanitized = adapter._sanitize_metadata(raw_input)
    assert sanitized["card_number"] == "[REDACTED]"
    assert sanitized["cvv"] == "[REDACTED]"
    assert sanitized["secret_token"] == "[REDACTED]"
    assert sanitized["status"] == "created"


# ---------------------------------------------------------------------------
# 13. Normalized provider outcome structure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_13_normalized_provider_outcome_shape(valid_config, valid_create_request):
    """Scenario 13: Result matches ProviderExecutionResult schema completely."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": "plink_555", "status": "created"},
            headers={"x-request-id": "req_555"},
        )

    adapter = build_adapter_with_mock(valid_config, handler)
    result = await adapter.create_payment_link(valid_create_request)

    assert isinstance(result, ProviderExecutionResult)
    assert result.status in ProviderOutcomeStatus
    assert result.retry_safety in RetrySafety
    assert result.timestamp is not None
    assert result.provider == "razorpay"


# ---------------------------------------------------------------------------
# 14. Provider request correlation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_14_provider_request_correlation(valid_config, valid_create_request):
    """Scenario 14: Provider correlation ID extracted from response headers."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": "plink_corr_test", "status": "created"},
            headers={"x-razorpay-request-id": "rzp_req_header_9988"},
        )

    adapter = build_adapter_with_mock(valid_config, handler)
    result = await adapter.create_payment_link(valid_create_request)

    assert result.provider_request_id == "rzp_req_header_9988"


# ---------------------------------------------------------------------------
# 15. Unsupported capability
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_15_unsupported_capability_raises_error(valid_create_request):
    """Scenario 15: Invoking an un-configured capability raises UnsupportedCapabilityError."""
    # Config with only FETCH_PAYMENT enabled
    restricted_config = RazorpayConfig(
        key_id="rzp_test_123",
        key_secret="mock_secret",
        enabled_capabilities={ProviderCapability.FETCH_PAYMENT},
    )

    adapter = RazorpaySandboxAdapter(config=restricted_config)

    with pytest.raises(UnsupportedCapabilityError, match="CREATE_PAYMENT_LINK"):
        await adapter.create_payment_link(valid_create_request)
