"""
ExecutionControlService — DB-backed global execution kill switch.

DESIGN PRINCIPLES
-----------------
1. FAIL-CLOSED: Any condition that prevents a definitive True read from the
   database results in execution being considered DISABLED.  This includes:
     - setting not found
     - value is not a JSON boolean
     - value is not exactly True
     - database query raises any exception

2. NO STALE CACHE: The DB is queried on every call to is_execution_enabled().
   Do not introduce application-level caching.  The round-trip cost is
   intentional — a production call must reflect the current DB state.

3. ENFORCEMENT POINT: This service must be called immediately before any
   provider mutation.  A queued job that was approved while execution was
   enabled is NOT exempt — it must re-check at the moment of mutation.

FUTURE ENFORCEMENT FLOW
-----------------------
    execution_control.is_execution_enabled()   ← this module
          ↓  (False → raise ExecutionDisabledError)
    PolicyEngine.evaluate()
          ↓  (Rejected → raise PolicyViolationError)
    ProviderAdapter.execute()
          ↓
    actual financial mutation
"""

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.system_settings import SystemSetting

logger = logging.getLogger("ariv.services.execution_control")

EXECUTION_ENABLED_KEY = "execution_enabled"


class ExecutionDisabledError(Exception):
    """
    Raised when the kill switch blocks execution.

    Carries a machine-readable reason so that a future execution worker can
    record why a particular attempt was blocked without inspecting log output.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Execution blocked: {reason}")


class ExecutionControlService:
    """
    Reads the authoritative execution_enabled flag from PostgreSQL.

    All methods are async because the flag is stored in the database and must
    never be served from a stale in-memory value.
    """

    @staticmethod
    async def is_execution_enabled(session: AsyncSession) -> bool:
        """
        Returns True only when the database contains:
            key='execution_enabled', value=true  (JSON boolean)

        Returns False for ALL other conditions (fail-closed):
            - row missing
            - value is not a JSON boolean
            - value is JSON false
            - database read raises any exception
        """
        try:
            result = await session.execute(
                select(SystemSetting).where(
                    SystemSetting.key == EXECUTION_ENABLED_KEY
                )
            )
            setting: Optional[SystemSetting] = result.scalar_one_or_none()

            if setting is None:
                logger.warning(
                    "execution_enabled setting not found in system_settings; "
                    "failing closed."
                )
                return False

            raw_value = setting.value

            if not isinstance(raw_value, bool):
                logger.error(
                    "execution_enabled value is not a boolean (got %r, type=%s); "
                    "failing closed.",
                    raw_value,
                    type(raw_value).__name__,
                )
                return False

            if raw_value is True:
                logger.debug("execution_enabled=True; execution is permitted.")
                return True

            logger.info("execution_enabled=False; execution is blocked by kill switch.")
            return False

        except Exception as exc:
            logger.error(
                "Database read failure while checking execution_enabled; "
                "failing closed. error=%r",
                exc,
            )
            return False

    @staticmethod
    async def guard(session: AsyncSession) -> None:
        """
        Convenience method for enforcement points.

        Raises ExecutionDisabledError if execution is not permitted.
        Call this immediately before any provider mutation.

        Usage:
            await ExecutionControlService.guard(session)
            # only reaches here if execution is enabled
            await provider_adapter.execute(...)
        """
        enabled = await ExecutionControlService.is_execution_enabled(session)
        if not enabled:
            raise ExecutionDisabledError(
                "execution_enabled is false or could not be confirmed from the database"
            )
