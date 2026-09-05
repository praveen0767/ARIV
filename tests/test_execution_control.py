"""
tests/test_execution_control.py

Phase 4A focused tests for the DB-backed execution kill switch.

COVERAGE
--------
- execution_enabled = true   → is_execution_enabled() returns True
- execution_enabled = false  → returns False
- setting missing            → returns False  (fail-closed)
- value is not a boolean     → returns False  (fail-closed)
- value is an integer 1      → returns False  (strict boolean check)
- value is string "true"     → returns False  (strict boolean check)
- DB read raises exception   → returns False  (fail-closed)
- guard() when enabled       → does not raise
- guard() when disabled      → raises ExecutionDisabledError
- DB authoritativeness:
    false → true  transition reflected without restart
    true  → false transition reflected without restart

All tests use AsyncMock sessions to isolate the service from the
actual database.  The DB-authoritativeness tests simulate two sequential
reads returning different values to prove the service does not cache.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.system_settings import SystemSetting
from app.services.execution_control import (
    ExecutionControlService,
    ExecutionDisabledError,
    EXECUTION_ENABLED_KEY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_setting(value) -> SystemSetting:
    """Return an unsaved SystemSetting with the given value."""
    s = SystemSetting()
    s.key = EXECUTION_ENABLED_KEY
    s.value = value
    return s


def _session_returning(setting_or_none):
    """
    Build an AsyncMock session whose execute() returns a result whose
    scalar_one_or_none() yields setting_or_none.
    """
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none.return_value = setting_or_none
    session.execute = AsyncMock(return_value=result)
    return session


# ---------------------------------------------------------------------------
# is_execution_enabled() — basic cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enabled_true_returns_true():
    """execution_enabled = true → permitted."""
    session = _session_returning(_make_setting(True))
    assert await ExecutionControlService.is_execution_enabled(session) is True


@pytest.mark.asyncio
async def test_enabled_false_returns_false():
    """execution_enabled = false → blocked."""
    session = _session_returning(_make_setting(False))
    assert await ExecutionControlService.is_execution_enabled(session) is False


@pytest.mark.asyncio
async def test_missing_setting_returns_false():
    """Setting row absent → fail-closed."""
    session = _session_returning(None)
    assert await ExecutionControlService.is_execution_enabled(session) is False


# ---------------------------------------------------------------------------
# is_execution_enabled() — malformed values
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_malformed_integer_one_returns_false():
    """value = 1 (integer) is NOT a boolean True → fail-closed."""
    session = _session_returning(_make_setting(1))
    assert await ExecutionControlService.is_execution_enabled(session) is False


@pytest.mark.asyncio
async def test_malformed_string_true_returns_false():
    """value = "true" (string) is NOT a boolean → fail-closed."""
    session = _session_returning(_make_setting("true"))
    assert await ExecutionControlService.is_execution_enabled(session) is False


@pytest.mark.asyncio
async def test_malformed_none_value_returns_false():
    """value = None inside the setting → fail-closed."""
    session = _session_returning(_make_setting(None))
    assert await ExecutionControlService.is_execution_enabled(session) is False


@pytest.mark.asyncio
async def test_malformed_dict_value_returns_false():
    """value = {} (dict) is not a boolean → fail-closed."""
    session = _session_returning(_make_setting({}))
    assert await ExecutionControlService.is_execution_enabled(session) is False


# ---------------------------------------------------------------------------
# is_execution_enabled() — database failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_db_exception_returns_false():
    """Database read failure → fail-closed (never raises to caller)."""
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(side_effect=Exception("connection reset"))
    assert await ExecutionControlService.is_execution_enabled(session) is False


@pytest.mark.asyncio
async def test_db_timeout_returns_false():
    """Simulate a timeout error → fail-closed."""
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(side_effect=TimeoutError("query timed out"))
    assert await ExecutionControlService.is_execution_enabled(session) is False


# ---------------------------------------------------------------------------
# guard() method
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_guard_when_enabled_does_not_raise():
    """guard() passes through when execution is enabled."""
    session = _session_returning(_make_setting(True))
    # Must NOT raise
    await ExecutionControlService.guard(session)


@pytest.mark.asyncio
async def test_guard_when_disabled_raises():
    """guard() raises ExecutionDisabledError when execution is disabled."""
    session = _session_returning(_make_setting(False))
    with pytest.raises(ExecutionDisabledError) as exc_info:
        await ExecutionControlService.guard(session)
    assert "execution_enabled" in str(exc_info.value).lower() or \
           "blocked" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_guard_when_missing_raises():
    """guard() raises ExecutionDisabledError when setting is absent."""
    session = _session_returning(None)
    with pytest.raises(ExecutionDisabledError):
        await ExecutionControlService.guard(session)


@pytest.mark.asyncio
async def test_guard_on_db_error_raises():
    """guard() raises ExecutionDisabledError (not a raw DB exception) on failure."""
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(side_effect=Exception("db down"))
    with pytest.raises(ExecutionDisabledError):
        await ExecutionControlService.guard(session)


# ---------------------------------------------------------------------------
# DB authoritativeness — no stale cache
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_false_to_true_transition_reflected_immediately():
    """
    Simulates an operator flipping execution_enabled from false → true.
    The service must return False on the first call and True on the second
    WITHOUT any application restart — proving the DB is the source of truth
    and the service does not cache.
    """
    result_false = MagicMock()
    result_false.scalar_one_or_none.return_value = _make_setting(False)

    result_true = MagicMock()
    result_true.scalar_one_or_none.return_value = _make_setting(True)

    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(side_effect=[result_false, result_true])

    first_call = await ExecutionControlService.is_execution_enabled(session)
    second_call = await ExecutionControlService.is_execution_enabled(session)

    assert first_call is False,  "Should be blocked before operator enables execution"
    assert second_call is True,  "Should be permitted after operator enables execution"
    assert session.execute.call_count == 2, "Must query DB on every call (no cache)"


@pytest.mark.asyncio
async def test_true_to_false_transition_reflected_immediately():
    """
    Simulates an operator flipping execution_enabled from true → false
    (emergency kill).  The service must return True on the first call and
    False on the second — immediately blocking execution.
    """
    result_true = MagicMock()
    result_true.scalar_one_or_none.return_value = _make_setting(True)

    result_false = MagicMock()
    result_false.scalar_one_or_none.return_value = _make_setting(False)

    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(side_effect=[result_true, result_false])

    first_call = await ExecutionControlService.is_execution_enabled(session)
    second_call = await ExecutionControlService.is_execution_enabled(session)

    assert first_call is True,  "Should be permitted before operator kills execution"
    assert second_call is False, "Emergency kill must take effect immediately"
    assert session.execute.call_count == 2, "Must query DB on every call (no cache)"


# ---------------------------------------------------------------------------
# ExecutionDisabledError shape
# ---------------------------------------------------------------------------

def test_execution_disabled_error_carries_reason():
    """ExecutionDisabledError exposes a machine-readable reason attribute."""
    reason = "execution_enabled is false"
    err = ExecutionDisabledError(reason)
    assert err.reason == reason
    assert reason in str(err)
