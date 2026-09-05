"""
Tests for Phase 5 Recovery API — tenant isolation.

Verifies:
  1. Missing auth headers → 422 (FastAPI validation error).
  2. Invalid HMAC signature → 401.
  3. Valid credentials but unknown case (wrong tenant) → 404.
  4. Cross-tenant access: tenant_A credentials cannot access tenant_B case.
  5. Metrics endpoint accepts valid auth (auth layer passes).
  6. Experiments endpoint enforces tenant scoping → 404 for unknown experiment.

All DB-touching tests override BOTH `get_current_tenant` AND `get_db_session`
so no live database is required.
"""

import hmac
import hashlib
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.recovery import get_current_tenant
from app.core.config import settings
from app.infrastructure.database import get_db_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TENANT_A_ID = uuid.uuid4()
TENANT_B_ID = uuid.uuid4()
ACCOUNT_A = "account_a"
ACCOUNT_B = "account_b"


def make_sig(account_id: str, key: str = settings.INTERNAL_API_KEY) -> str:
    return hmac.new(
        key.encode("utf-8"),
        account_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def auth_headers_for(account_id: str, key: str = settings.INTERNAL_API_KEY) -> dict:
    return {
        "X-Account-ID": account_id,
        "X-Signature": make_sig(account_id, key),
    }


# ---------------------------------------------------------------------------
# Fake domain objects
# ---------------------------------------------------------------------------

class FakeTenantA:
    id = TENANT_A_ID


class FakeTenantB:
    id = TENANT_B_ID


def make_tenant_dep(tenant):
    """Dependency override: skip HMAC and return a fixed tenant."""
    async def _dep():
        return tenant
    return _dep


def make_session_dep(scalar_result=None):
    """
    Dependency override: return an AsyncSession mock whose execute() returns
    a result whose scalar_one_or_none() returns `scalar_result`.
    """
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = scalar_result
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def _dep():
        yield mock_session

    return _dep


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

client = TestClient(app)


def test_missing_auth_headers_returns_422():
    """No auth headers → FastAPI 422 (missing required header)."""
    resp = client.get(f"/v1/recovery/cases/{uuid.uuid4()}")
    assert resp.status_code == 422


def test_invalid_signature_returns_401():
    """Correct X-Account-ID but wrong X-Signature → 401."""
    headers = {
        "X-Account-ID": ACCOUNT_A,
        "X-Signature": "bad_signature_value",
    }
    # Patch resolve_tenant so it is never reached (auth should fail before that)
    with patch("app.api.recovery.resolve_tenant", new_callable=AsyncMock) as mock_rt:
        mock_rt.return_value = FakeTenantA()
        # Also override DB so the session dependency doesn't try to connect
        app.dependency_overrides[get_db_session] = make_session_dep()
        try:
            resp = client.get(f"/v1/recovery/cases/{uuid.uuid4()}", headers=headers)
        finally:
            app.dependency_overrides.pop(get_db_session, None)

    assert resp.status_code == 401
    assert "Invalid signature" in resp.json()["detail"]


def test_valid_credentials_unknown_case_returns_404():
    """
    Valid auth + tenant resolved, but case_id not found (simulate no DB row) → 404.
    """
    app.dependency_overrides[get_current_tenant] = make_tenant_dep(FakeTenantA())
    app.dependency_overrides[get_db_session] = make_session_dep(scalar_result=None)
    try:
        resp = client.get(
            f"/v1/recovery/cases/{uuid.uuid4()}",
            headers=auth_headers_for(ACCOUNT_A),
        )
    finally:
        app.dependency_overrides.pop(get_current_tenant, None)
        app.dependency_overrides.pop(get_db_session, None)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Case not found"


def test_cross_tenant_isolation_returns_404():
    """
    Tenant B valid credentials → cannot see a case that belongs to Tenant A.

    The query WHERE clause includes `tenant_id == tenant.id`, so the DB mock
    returning None simulates the cross-tenant filter producing no row.
    """
    app.dependency_overrides[get_current_tenant] = make_tenant_dep(FakeTenantB())
    app.dependency_overrides[get_db_session] = make_session_dep(scalar_result=None)
    try:
        resp = client.get(
            f"/v1/recovery/cases/{uuid.uuid4()}",
            headers=auth_headers_for(ACCOUNT_B),
        )
    finally:
        app.dependency_overrides.pop(get_current_tenant, None)
        app.dependency_overrides.pop(get_db_session, None)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Case not found"


def test_metrics_auth_accepted():
    """
    Valid auth for Tenant A → metrics endpoint auth layer passes.
    The mock returns scalar_result=None which maps to 0 total.
    """
    app.dependency_overrides[get_current_tenant] = make_tenant_dep(FakeTenantA())
    app.dependency_overrides[get_db_session] = make_session_dep(scalar_result=None)
    try:
        resp = client.get(
            "/v1/recovery/metrics",
            headers=auth_headers_for(ACCOUNT_A),
        )
    finally:
        app.dependency_overrides.pop(get_current_tenant, None)
        app.dependency_overrides.pop(get_db_session, None)

    assert resp.status_code == 200
    assert "total_incremental_recovery" in resp.json()


def test_metrics_returns_aggregate_total():
    """
    GET /v1/recovery/metrics returns the aggregated incremental recovery sum for the tenant.
    """
    app.dependency_overrides[get_current_tenant] = make_tenant_dep(FakeTenantA())
    app.dependency_overrides[get_db_session] = make_session_dep(scalar_result=150000)
    try:
        resp = client.get(
            "/v1/recovery/metrics",
            headers=auth_headers_for(ACCOUNT_A),
        )
    finally:
        app.dependency_overrides.pop(get_current_tenant, None)
        app.dependency_overrides.pop(get_db_session, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_incremental_recovery"] == 150000
    assert data["incremental_recovery_estimate"] == 150000
    assert data["baseline_method"] == "deterministic_heuristic"
    assert data["is_estimate"] is True
    assert data["label"] == "ESTIMATE"


def test_experiment_cross_tenant_returns_404():
    """Tenant B valid credentials → cannot see Tenant A experiment."""
    app.dependency_overrides[get_current_tenant] = make_tenant_dep(FakeTenantB())
    app.dependency_overrides[get_db_session] = make_session_dep(scalar_result=None)
    try:
        resp = client.get(
            f"/v1/recovery/experiments/{uuid.uuid4()}",
            headers=auth_headers_for(ACCOUNT_B),
        )
    finally:
        app.dependency_overrides.pop(get_current_tenant, None)
        app.dependency_overrides.pop(get_db_session, None)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Experiment not found"


def test_case_outcome_cross_tenant_returns_404():
    """Tenant B valid credentials → cannot see Tenant A case/outcome."""
    app.dependency_overrides[get_current_tenant] = make_tenant_dep(FakeTenantB())
    app.dependency_overrides[get_db_session] = make_session_dep(scalar_result=None)
    try:
        resp = client.get(
            f"/v1/recovery/cases/{uuid.uuid4()}/outcome",
            headers=auth_headers_for(ACCOUNT_B),
        )
    finally:
        app.dependency_overrides.pop(get_current_tenant, None)
        app.dependency_overrides.pop(get_db_session, None)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Case not found"


def test_full_case_detail_not_found_returns_404():
    """GET /v1/recovery/cases/{id}/full returns 404 when case not found."""
    app.dependency_overrides[get_current_tenant] = make_tenant_dep(FakeTenantA())
    with patch("app.services.dashboard.DashboardService.get_full_case_detail", new_callable=AsyncMock) as mock_detail:
        mock_detail.return_value = None
        try:
            resp = client.get(
                f"/v1/recovery/cases/{uuid.uuid4()}/full",
                headers=auth_headers_for(ACCOUNT_A),
            )
        finally:
            app.dependency_overrides.pop(get_current_tenant, None)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Case not found"


def test_full_case_detail_returns_200_and_payload():
    """GET /v1/recovery/cases/{id}/full returns 200 and full case aggregation."""
    case_id = uuid.uuid4()
    mock_payload = {
        "case": {"id": str(case_id), "status": "RECOVERED", "recovery_stage": "RECOVERED"},
        "classification": {"failure_category": "CUSTOMER_ACTION_REQUIRED"},
        "decision": {"proposed_action": "GENERATE_PAYMENT_LINK", "policy_status": "APPROVED"},
        "execution": {"action_type": "GENERATE_PAYMENT_LINK", "status": "SUCCEEDED"},
        "recovery": {"outcome_status": "RECOVERED", "recovered_amount_minor": 10000},
        "timeline": [{"stage": "CASE_CREATED", "status": "COMPLETED"}],
    }
    app.dependency_overrides[get_current_tenant] = make_tenant_dep(FakeTenantA())
    with patch("app.services.dashboard.DashboardService.get_full_case_detail", new_callable=AsyncMock) as mock_detail:
        mock_detail.return_value = mock_payload
        try:
            resp = client.get(
                f"/v1/recovery/cases/{case_id}/full",
                headers=auth_headers_for(ACCOUNT_A),
            )
        finally:
            app.dependency_overrides.pop(get_current_tenant, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["case"]["id"] == str(case_id)
    assert data["case"]["status"] == "RECOVERED"
    assert data["recovery"]["outcome_status"] == "RECOVERED"
    assert data["recovery"]["recovered_amount_minor"] == 10000

