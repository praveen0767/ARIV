"""tests/test_persistence_consistency.py

Focused regression coverage for the PostgreSQL <-> Qdrant persistence
consistency work:

1. Claims: only PENDING / FAILED / lease-expired CLAIMED / version-stale COMPLETED
   KnowledgeOutbox rows are eligible, and the retry budget is respected.
2. process_item COMPLETED / FAILED / DEAD_LETTERED transitions and index stamping.
3. The safe background trigger never raises and uses a fresh session.
4. Tenant isolation on the ONLY Qdrant write path.
5. Confidence is never fabricated (no more hard-coded 88).
6. The SSE stream emits a structured `error` event instead of a bare close.
"""

import json
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.recovery.knowledge_outbox import KnowledgeOutbox, KnowledgeOutboxStatus
from app.domain.decision import DecisionRecord
from app.services.qdrant_indexer import (
    KNOWLEDGE_INDEX_VERSION,
    QdrantIndexerWorker,
    _needs_processing,
)
from app.services.qdrant_memory import QdrantIndexingError, QdrantMemoryService
from app.api.agent import _agent_stream, format_ai_confidence


def make_outbox(
    status=KnowledgeOutboxStatus.PENDING,
    attempt_count=0,
    max_retries=3,
    payload=None,
    lease_expires_at=None,
    measurement_id=None,
):
    o = MagicMock(spec=KnowledgeOutbox)
    o.id = uuid.uuid4()
    o.tenant_id = uuid.uuid4()
    o.measurement_id = measurement_id or uuid.uuid4()
    o.payload = payload or {}
    o.status = status
    o.attempt_count = attempt_count
    o.max_retries = max_retries
    o.last_error = None
    o.lease_expires_at = lease_expires_at
    return o


# ---------------------------------------------------------------------------
# 1. Claiming eligibility (incl. version-aware re-drain after collection rename)
# ---------------------------------------------------------------------------

def test_needs_processing_eligibility_matrix():
    now = datetime.now(timezone.utc)
    expired = now - timedelta(seconds=10)
    future = now + timedelta(seconds=10)

    assert _needs_processing(make_outbox(KnowledgeOutboxStatus.PENDING), now)
    assert _needs_processing(make_outbox(KnowledgeOutboxStatus.FAILED), now)
    assert _needs_processing(
        make_outbox(KnowledgeOutboxStatus.CLAIMED, lease_expires_at=expired), now
    )
    assert not _needs_processing(
        make_outbox(KnowledgeOutboxStatus.CLAIMED, lease_expires_at=future), now
    )

    # COMPLETED rows predating the CURRENT index version (e.g. written into the
    # legacy 'recovery_measurements' collection) must be re-drained into the
    # current collection via the durable outbox — never by a direct Qdrant write.
    assert _needs_processing(
        make_outbox(KnowledgeOutboxStatus.COMPLETED, payload={}), now
    )
    assert _needs_processing(
        make_outbox(KnowledgeOutboxStatus.COMPLETED, payload={"index_version": 1}), now
    )
    assert not _needs_processing(
        make_outbox(KnowledgeOutboxStatus.COMPLETED,
                    payload={"index_version": KNOWLEDGE_INDEX_VERSION}),
        now,
    )

    # Retry budget and terminal statuses are never touched.
    assert not _needs_processing(
        make_outbox(KnowledgeOutboxStatus.PENDING, attempt_count=3, max_retries=3), now
    )
    assert not _needs_processing(make_outbox(KnowledgeOutboxStatus.DEAD_LETTERED), now)


@pytest.mark.asyncio
async def test_claim_pending_items_only_claims_eligible():
    now = datetime.now(timezone.utc)
    expired = now - timedelta(seconds=10)
    future = now + timedelta(seconds=60)

    pending = make_outbox(KnowledgeOutboxStatus.PENDING)
    failed = make_outbox(KnowledgeOutboxStatus.FAILED)
    stale = make_outbox(KnowledgeOutboxStatus.CLAIMED, lease_expires_at=expired)
    held = make_outbox(KnowledgeOutboxStatus.CLAIMED, lease_expires_at=future)
    legacy = make_outbox(KnowledgeOutboxStatus.COMPLETED, payload={})
    current = make_outbox(KnowledgeOutboxStatus.COMPLETED,
                          payload={"index_version": KNOWLEDGE_INDEX_VERSION})
    maxed = make_outbox(KnowledgeOutboxStatus.PENDING, attempt_count=3, max_retries=3)

    result = MagicMock()
    result.scalars.return_value.all.return_value = [
        pending, failed, stale, held, legacy, current, maxed
    ]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    items = await QdrantIndexerWorker.claim_pending_items(
        session, worker_id="w", batch_size=10, lease_seconds=30
    )

    claimed = {str(item.id) for item in items}
    assert claimed == {str(pending.id), str(failed.id), str(stale.id), str(legacy.id)}
    assert str(held.id) not in claimed
    assert str(current.id) not in claimed
    assert str(maxed.id) not in claimed

    for item in items:
        assert item.status is KnowledgeOutboxStatus.CLAIMED
        assert item.attempt_count == 1
        assert item.claimed_by == "w"


# ---------------------------------------------------------------------------
# 2. process_item transitions + index version stamping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_item_completes_and_stamps_index_version():
    item = make_outbox(
        KnowledgeOutboxStatus.CLAIMED, payload={"failure_category": "TRANSIENT_TECHNICAL"}
    )
    session = AsyncMock()

    with patch.object(
        QdrantMemoryService, "index_recovery_measurement", new_callable=AsyncMock,
        return_value=True,
    ) as indexer:
        ok = await QdrantIndexerWorker.process_item(session, item, client="fake")

    assert ok is True
    assert item.status is KnowledgeOutboxStatus.COMPLETED
    assert item.last_error is None
    assert item.payload["index_version"] == KNOWLEDGE_INDEX_VERSION
    indexer.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_item_fails_then_dead_letters():
    session = AsyncMock()
    failer = AsyncMock(side_effect=QdrantIndexingError("qdrant down"))

    with patch.object(QdrantMemoryService, "index_recovery_measurement", failer):
        item = make_outbox(KnowledgeOutboxStatus.CLAIMED)
        ok = await QdrantIndexerWorker.process_item(session, item, client="fake")

    assert ok is False
    assert item.status is KnowledgeOutboxStatus.FAILED
    assert "qdrant down" in (item.last_error or "")

    with patch.object(QdrantMemoryService, "index_recovery_measurement", failer):
        item2 = make_outbox(KnowledgeOutboxStatus.CLAIMED, attempt_count=3, max_retries=3)
        ok2 = await QdrantIndexerWorker.process_item(session, item2, client="fake")

    assert ok2 is False
    assert item2.status is KnowledgeOutboxStatus.DEAD_LETTERED


# ---------------------------------------------------------------------------
# 3. Safe background trigger (fresh session, never raises)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_outbox_item_safe_never_raises_and_uses_fresh_session():
    item = make_outbox(KnowledgeOutboxStatus.PENDING)
    fresh_session = AsyncMock()

    class _Txn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    result = MagicMock()
    result.scalar_one_or_none.return_value = item
    fresh_session.execute = AsyncMock(return_value=result)
    fresh_session.begin = MagicMock(return_value=_Txn())

    class _Ctx:
        def __init__(self, session):
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, *a):
            return False

    class _Factory:
        def __init__(self, session):
            self._session = session

        def __call__(self):
            return _Ctx(self._session)

    with patch.object(
        QdrantIndexerWorker, "process_item", new_callable=AsyncMock, return_value=True
    ) as process:
        outcome = await QdrantIndexerWorker.process_outbox_item_safe(
            _Factory(fresh_session), item.id, client="fake"
        )
    assert outcome is True
    process.assert_awaited_once()

    async def _boom(session, item, client=None):
        raise RuntimeError("inner worker failure")

    with patch.object(QdrantIndexerWorker, "process_item", new=_boom):
        outcome2 = await QdrantIndexerWorker.process_outbox_item_safe(
            _Factory(fresh_session), item.id, client="fake"
        )
    assert outcome2 is False


# ---------------------------------------------------------------------------
# 4. Tenant isolation on the sole Qdrant write path + payload sanitization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_index_requires_tenant_id():
    with pytest.raises(ValueError):
        await QdrantMemoryService.index_recovery_measurement(
            measurement_id=uuid.uuid4(), tenant_id=None, payload={}, client="fake"
        )


@pytest.mark.asyncio
async def test_index_stamps_tenant_and_strips_sensitive_keys():
    with patch(
        "app.services.qdrant_memory.EmbeddingService.embed_text",
        return_value=[0.0] * QdrantMemoryService.DIMENSION,
    ):
        client = AsyncMock()
        await QdrantMemoryService.index_recovery_measurement(
            measurement_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            payload={
                "card_number": "4111111111111111",
                "cvv": "123",
                "failure_category": "TRANSIENT_TECHNICAL",
            },
            client=client,
        )

    points = client.upsert.await_args.kwargs["points"]
    payload = points[0].payload
    assert "card_number" not in payload
    assert "cvv" not in payload
    assert payload["tenant_id"]
    assert payload["measurement_id"]
    assert points[0].id == payload["measurement_id"]


# ---------------------------------------------------------------------------
# 5. Confidence is never fabricated (no hard-coded 88 / 0.88)
# ---------------------------------------------------------------------------

def test_format_ai_confidence_never_fabricates():
    assert format_ai_confidence(None) == "Confidence unavailable"

    no_conf = MagicMock(spec=DecisionRecord)
    no_conf.ai_confidence = None
    assert format_ai_confidence(no_conf) == "Confidence unavailable"

    zero = MagicMock(spec=DecisionRecord)
    zero.ai_confidence = 0.0
    assert format_ai_confidence(zero) == "0%"

    real = MagicMock(spec=DecisionRecord)
    real.ai_confidence = 0.88
    assert format_ai_confidence(real) == "88%"


# ---------------------------------------------------------------------------
# 6. SSE stream emits a structured error event instead of a bare close
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_stream_emits_structured_error_event():
    db = AsyncMock()

    async def _boom(*a, **k):
        raise RuntimeError("query failed hard")

    db.execute = _boom

    events = []
    done = False
    async for raw in _agent_stream("Is ARIV healthy?", str(uuid.uuid4()), db):
        if raw == "data: [DONE]\n\n":
            done = True
            continue
        events.append(json.loads(raw[len("data: "):]))

    assert done
    errors = [e for e in events if e.get("type") == "error"]
    assert errors, f"expected a structured error event, got {events}"
    assert errors[0]["code"] == "OPERATIONAL_ERROR"
    assert "query failed hard" in errors[0]["message"]