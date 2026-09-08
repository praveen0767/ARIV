"""app/services/qdrant_indexer.py

Durable Outbox Worker for Knowledge / Qdrant Vector Indexing.
Decoupled from financial ExecutionWorker.

Key properties:
- PostgreSQL-backed durable queue (KnowledgeOutbox).
- Atomic claiming with row-level locks (FOR UPDATE SKIP LOCKED) and leasing.
- Retryable with max retry limit and dead-lettering.
- Qdrant outage does not block or roll back PostgreSQL financial transactions.
- Idempotent: exactly one indexing task per RecoveryMeasurement.
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.domain.recovery.knowledge_outbox import KnowledgeOutbox, KnowledgeOutboxStatus
from app.services.qdrant_memory import QdrantMemoryService, QdrantIndexingError

logger = logging.getLogger("ariv.services.qdrant_indexer")

# Increment whenever the indexing target collection or payload shape changes.
# COMPLETED entries carrying an older (or missing) version are re-drained into
# the CURRENT collection so Postgres-authoritative memory is always propagated.
# Legacy vectors in other collections are never deleted or rewritten.
KNOWLEDGE_INDEX_VERSION = 2


def _needs_processing(
    item: "KnowledgeOutbox",
    now: datetime,
    version: int = KNOWLEDGE_INDEX_VERSION,
) -> bool:
    """Decide whether a KnowledgeOutbox row still needs to be indexed.

    - PENDING / FAILED rows are always eligible (subject to retry budget).
    - CLAIMED rows are claimable again once their lease expires (crash recovery).
    - COMPLETED rows are re-drained only when their payload predates the CURRENT
      index version (e.g. a collection rename) so the durable outbox remains the
      single reconciliation mechanism for Postgres -> Qdrant memory.
    """
    if item.attempt_count >= item.max_retries:
        return False
    if item.status in (KnowledgeOutboxStatus.PENDING, KnowledgeOutboxStatus.FAILED):
        return True
    if item.status == KnowledgeOutboxStatus.CLAIMED:
        return item.lease_expires_at is not None and item.lease_expires_at < now
    if item.status == KnowledgeOutboxStatus.COMPLETED:
        return bool((item.payload or {}).get("index_version", 0) != version)
    return False


class QdrantIndexerWorker:
    """
    Manages durable outbox lifecycle and background processing for Qdrant vector indexing.
    """

    @staticmethod
    async def create_outbox_entry(
        session: AsyncSession,
        measurement_id: uuid.UUID,
        tenant_id: uuid.UUID,
        payload: dict,
    ) -> KnowledgeOutbox:
        """
        Transactionally create a PENDING KnowledgeOutbox record.
        Idempotent: if an entry already exists for this measurement_id, returns it.
        """
        # Check existing
        existing = await session.execute(
            select(KnowledgeOutbox).where(KnowledgeOutbox.measurement_id == measurement_id)
        )
        found = existing.scalar_one_or_none()
        if found:
            logger.info("KnowledgeOutbox already exists for measurement %s", measurement_id)
            return found

        # Copy payload so the outbox row owns its data; stamp the current index
        # version so the drainer can detect collection-rename re-drains later.
        stored_payload = dict(payload or {})
        stored_payload["index_version"] = KNOWLEDGE_INDEX_VERSION

        outbox = KnowledgeOutbox(
            tenant_id=tenant_id,
            measurement_id=measurement_id,
            payload=stored_payload,
            status=KnowledgeOutboxStatus.PENDING,
            attempt_count=0,
            max_retries=3,
        )
        session.add(outbox)
        try:
            await session.flush()
        except IntegrityError:
            # Concurrent race caught by unique constraint
            await session.rollback()
            existing = await session.execute(
                select(KnowledgeOutbox).where(KnowledgeOutbox.measurement_id == measurement_id)
            )
            return existing.scalar_one()

        logger.info("Created durable KnowledgeOutbox entry %s for measurement %s", outbox.id, measurement_id)
        return outbox

    @staticmethod
    async def claim_pending_items(
        session: AsyncSession,
        worker_id: str,
        batch_size: int = 10,
        lease_seconds: int = 30,
    ) -> List[KnowledgeOutbox]:
        """
        Atomically claims up to batch_size outbox items using PostgreSQL FOR UPDATE SKIP LOCKED.
        Recovers stale leases if a previous worker crashed.
        """
        now = datetime.now(timezone.utc)
        lease_expiry = now + timedelta(seconds=lease_seconds)

        stmt = (
            select(KnowledgeOutbox)
            .where(
                and_(
                    or_(
                        KnowledgeOutbox.status == KnowledgeOutboxStatus.PENDING,
                        KnowledgeOutbox.status == KnowledgeOutboxStatus.FAILED,
                        and_(
                            KnowledgeOutbox.status == KnowledgeOutboxStatus.CLAIMED,
                            KnowledgeOutbox.lease_expires_at < now,
                        ),
                        # COMPLETED rows are filtered in Python by known index
                        # version (_needs_processing) — the payload column is
                        # generic JSON, so the version predicate is kept portable.
                        KnowledgeOutbox.status == KnowledgeOutboxStatus.COMPLETED,
                    ),
                    KnowledgeOutbox.attempt_count < KnowledgeOutbox.max_retries,
                )
            )
            .order_by(KnowledgeOutbox.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(batch_size)
        )

        result = await session.execute(stmt)
        items = [item for item in result.scalars().all() if _needs_processing(item, now)]

        for item in items:
            item.status = KnowledgeOutboxStatus.CLAIMED
            item.claimed_by = worker_id
            item.claimed_at = now
            item.lease_expires_at = lease_expiry
            item.attempt_count += 1

        if items:
            await session.flush()
            logger.info("Worker %s claimed %d knowledge outbox item(s)", worker_id, len(items))

        return items

    @staticmethod
    async def process_item(
        session: AsyncSession,
        item: KnowledgeOutbox,
        client=None,
    ) -> bool:
        """
        Process a single claimed KnowledgeOutbox item.
        Upserts into Qdrant. On success, marks COMPLETED.
        On failure, updates last_error and increments retries.
        """
        try:
            await QdrantMemoryService.index_recovery_measurement(
                measurement_id=item.measurement_id,
                tenant_id=item.tenant_id,
                payload=item.payload,
                client=client,
            )
            item.status = KnowledgeOutboxStatus.COMPLETED
            item.last_error = None
            item.lease_expires_at = None
            stored_payload = dict(item.payload or {})
            stored_payload["index_version"] = KNOWLEDGE_INDEX_VERSION
            item.payload = stored_payload
            await session.flush()
            logger.info("KnowledgeOutbox %s marked COMPLETED", item.id)
            return True
        except Exception as exc:
            error_msg = str(exc)
            logger.error("Failed to index KnowledgeOutbox %s: %s", item.id, error_msg)
            item.last_error = error_msg
            if item.attempt_count >= item.max_retries:
                item.status = KnowledgeOutboxStatus.DEAD_LETTERED
                logger.warning("KnowledgeOutbox %s reached max retries (%d) -> DEAD_LETTERED",
                               item.id, item.max_retries)
            else:
                item.status = KnowledgeOutboxStatus.FAILED
            item.lease_expires_at = None
            await session.flush()
            return False

    @classmethod
    async def process_outbox_item_safe(
        cls,
        session_factory,
        outbox_id: uuid.UUID,
        worker_id: str = "trigger_worker",
        client=None,
    ) -> bool:
        """
        Safe background processing trigger for a specific outbox item.
        Never throws exceptions or interferes with caller transactions.
        """
        try:
            async with session_factory() as session:
                async with session.begin():
                    res = await session.execute(
                        select(KnowledgeOutbox)
                        .where(KnowledgeOutbox.id == outbox_id)
                        .with_for_update(skip_locked=True)
                    )
                    item = res.scalar_one_or_none()
                    if not item or item.status == KnowledgeOutboxStatus.COMPLETED:
                        return False

                    now = datetime.now(timezone.utc)
                    item.status = KnowledgeOutboxStatus.CLAIMED
                    item.claimed_by = worker_id
                    item.claimed_at = now
                    item.lease_expires_at = now + timedelta(seconds=30)
                    item.attempt_count += 1
                    await session.flush()

                    return await cls.process_item(session, item, client=client)
        except Exception as exc:
            logger.error("process_outbox_item_safe encountered error for outbox %s: %s", outbox_id, exc)
            return False
