"""
app/services/outbox.py

Durable Outbox service for ARIV execution pipeline.
Provides transactional authorization and atomic row-level claiming with leasing.
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple

from sqlalchemy import select, and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.action import (
    Action,
    ActionStatus,
    ExecutionOutbox,
    OutboxStatus,
)
from app.domain.decision import RecoveryAction
from app.domain.events import AuditEvent

logger = logging.getLogger("ariv.services.outbox")


class OutboxService:
    """
    Manages transactional creation and atomic claiming of ExecutionOutbox records.
    """

    @staticmethod
    async def create_authorized_action(
        session: AsyncSession,
        case_id: uuid.UUID,
        tenant_id: uuid.UUID,
        decision_id: uuid.UUID,
        action_type: RecoveryAction,
        payload: dict,
    ) -> Tuple[Action, ExecutionOutbox]:
        """
        Atomically creates an AUTHORIZED Action and a PENDING ExecutionOutbox record.
        Guarantees that no authorized action is lost if worker or queue restarts.
        """
        action = Action(
            case_id=case_id,
            tenant_id=tenant_id,
            decision_id=decision_id,
            action_type=action_type,
            status=ActionStatus.AUTHORIZED,
        )
        # Add action to session; handle async mock gracefully
        result = session.add(action)
        if hasattr(result, "__await__"):
            await result
        await session.flush()  # Generate action.id

        outbox = ExecutionOutbox(
            action_id=action.id,
            payload=payload,
            status=OutboxStatus.PENDING,
            attempt_count=0,
            max_retries=3,
        )
        result = session.add(outbox)
        if hasattr(result, "__await__"):
            await result

        audit = AuditEvent(
            case_id=case_id,
            event_type="ACTION_AUTHORIZED",
            details={
                "action_id": str(action.id),
                "decision_id": str(decision_id),
                "tenant_id": str(tenant_id),
                "action_type": action_type.value,
                "outbox_status": OutboxStatus.PENDING.value,
            },
        )
        result = session.add(audit)
        if hasattr(result, "__await__"):
            await result
        await session.flush()

        logger.info(
            "Transactionally created Action %s (AUTHORIZED) and Outbox %s (PENDING)",
            action.id,
            outbox.id,
        )
        return action, outbox

    @staticmethod
    async def claim_pending_items(
        session: AsyncSession,
        worker_id: str,
        batch_size: int = 10,
        lease_seconds: int = 30,
    ) -> List[ExecutionOutbox]:
        """
        Atomically claims up to batch_size outbox items that are either:
        1. status == PENDING
        2. status == CLAIMED and lease_expires_at < now() (stale lease recovery)
        and attempt_count < max_retries.

        Uses PostgreSQL FOR UPDATE SKIP LOCKED to guarantee concurrency safety
        across multiple concurrent workers without race conditions or deadlocks.
        """
        now = datetime.now(timezone.utc)
        lease_expiry = now + timedelta(seconds=lease_seconds)

        # Select candidate outbox items with row-level lock skipping already locked rows
        stmt = (
            select(ExecutionOutbox)
            .where(
                and_(
                    or_(
                        ExecutionOutbox.status == OutboxStatus.PENDING,
                        and_(
                            ExecutionOutbox.status == OutboxStatus.CLAIMED,
                            ExecutionOutbox.lease_expires_at < now,
                        ),
                    ),
                    ExecutionOutbox.attempt_count < ExecutionOutbox.max_retries,
                )
            )
            .order_by(ExecutionOutbox.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(batch_size)
        )

        result = await session.execute(stmt)
        items = list(result.scalars().all())

        if not items:
            return []

        # Claim each locked item
        claimed_ids = []
        for item in items:
            item.status = OutboxStatus.CLAIMED
            item.claimed_by = worker_id
            item.claimed_at = now
            item.lease_expires_at = lease_expiry
            item.attempt_count += 1
            claimed_ids.append(item.id)

        await session.flush()
        logger.info("Worker %s claimed %d outbox item(s)", worker_id, len(claimed_ids))
        return items
