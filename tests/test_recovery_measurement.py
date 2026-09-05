"""
tests/test_recovery_measurement.py

Verifies that RecoveryService.create_measurement():
  1. Persists a RecoveryMeasurement record (flush is called).
  2. Creates a KnowledgeOutbox entry in PENDING status.
  3. Does NOT require a live PostgreSQL database (fully mocked session).

Root-cause of the original failure:
  - The file used `getattr(settings, 'TEST_DATABASE_URL', None)` which returns
    None (no such setting exists), causing `create_async_engine(None)` to crash
    at collection time — before a single test ran.
  - Additionally the test passed a raw `RecoveryMeasurement()` where a
    `RecoveryOutcome` was expected, and used a plain class instead of the
    required `DecisionContext`-compatible object.

Fix strategy: mock the AsyncSession entirely (same pattern as other ARIV tests).
No live database is needed; the assertions verify the *intent* (objects flushed,
outbox status PENDING) not raw SQL.
"""

import uuid
import asyncio
from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from app.domain.recovery.recovery_measurement import RecoveryMeasurement
from app.domain.recovery.knowledge_outbox import KnowledgeOutbox, KnowledgeOutboxStatus
from app.domain.recovery.recovery_outcome import RecoveryOutcome, RecoveryOutcomeStatus, RecoverySource
from app.domain.classification import FailureCategory, Retryability
from app.domain.recovery_case import RecoveryCase, RecoveryDomain, CaseType
from app.domain.action import Action
from app.domain.provider import ProviderExecutionResult, ProviderOutcomeStatus, RetrySafety
from app.domain.recovery.baseline_decision import BaselineDecision
from app.services.recovery import RecoveryService
from app.services.baseline import BaselineService
from app.services.qdrant_memory import QdrantMemoryService, QdrantIndexingError
from app.services.qdrant_indexer import QdrantIndexerWorker
from app.services.embedding import EmbeddingService


# ---------------------------------------------------------------------------
# Helpers: build realistic stub objects
# ---------------------------------------------------------------------------

def make_outcome(tenant_id=None, case_id=None):
    """Build a RecoveryOutcome-like stub with all fields create_measurement reads."""
    o = MagicMock(spec=RecoveryOutcome)
    o.id = uuid.uuid4()
    o.tenant_id = tenant_id or uuid.uuid4()
    o.recovered_amount = 1000
    o.outcome_status = RecoveryOutcomeStatus.RECOVERED
    o.recovery_source = RecoverySource.ACTION_ATTRIBUTED
    o.time_to_recovery = None
    o.case_id = case_id or uuid.uuid4()
    return o


class StubTenant:
    def __init__(self):
        self.id = uuid.uuid4()


class StubCase:
    def __init__(self, tenant_id):
        self.id = uuid.uuid4()
        self.domain = RecoveryDomain.B2C
        self.amount = 1000
        self.amount_minor = 1000
        self.context = {}
        self.tenant_id = tenant_id
        self.created_at = datetime(2026, 9, 1, 9, 0, 0, tzinfo=timezone.utc)


class StubClassification:
    failure_category = FailureCategory.TRANSIENT_TECHNICAL
    retryability = Retryability.LATER_RETRY_POSSIBLE


class StubContext:
    def __init__(self):
        self.tenant = StubTenant()
        self.case = StubCase(self.tenant.id)
        self.classification = StubClassification()


def make_scalar_result(value):
    """Return an awaitable mock that behaves like session.execute(...).scalar_one_or_none()."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalar_one.return_value = value
    return result


def build_mock_session():
    """
    Build an AsyncSession mock that handles all sequential execute() calls made
    by RecoveryService.create_measurement():

    Call order (in service code):
      1. select(RecoveryMeasurement) — idempotency check → None (no existing)
      2. select(SystemSetting) for attribution_window → None (use default 86400)
      3. select(Experiment) for assign_experiment → None (no active experiment)
      4. select(KnowledgeOutbox) in create_outbox_entry → None (no existing entry)

    After those 4 selects the service calls session.add() and session.flush()
    for baseline, measurement, and outbox objects.
    """
    session = AsyncMock()
    session.add = MagicMock()  # sync method

    # Pre-define sequenced return values for execute()
    session.execute = AsyncMock(side_effect=[
        make_scalar_result(None),   # 1. idempotency check on RecoveryMeasurement
        make_scalar_result(None),   # 2. SystemSetting lookup → default
        make_scalar_result(None),   # 3. Experiment lookup → no active experiment
        make_scalar_result(None),   # 4. KnowledgeOutbox idempotency check
    ])

    # flush() is called multiple times (baseline, measurement, outbox) — let them succeed
    session.flush = AsyncMock(return_value=None)

    return session


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recovery_measurement_creates_outbox():
    """
    RecoveryService.create_measurement() must:
      - Persist a RecoveryMeasurement (session.flush() called).
      - Create a KnowledgeOutbox entry with status PENDING.
      - Not require a live database.
    """
    context = StubContext()
    outcome = make_outcome(
        tenant_id=context.tenant.id,
        case_id=context.case.id,
    )
    session = build_mock_session()

    # Patch the background task trigger so it doesn't spawn real asyncio tasks.
    # create_task receives a coroutine — close it immediately to avoid the
    # "coroutine was never awaited" RuntimeWarning.
    def _close_coro(coro):
        coro.close()
        return MagicMock()

    with patch.object(asyncio, "get_running_loop") as mock_loop:
        mock_loop.return_value = MagicMock()
        mock_loop.return_value.create_task = MagicMock(side_effect=_close_coro)

        # Also patch QdrantMemoryService helpers (pure functions, no DB)
        with patch("app.services.recovery.QdrantMemoryService.get_amount_bucket", return_value="1000-5000"), \
             patch("app.services.recovery.QdrantMemoryService.get_ttr_bucket", return_value="unknown"):

            measurement = await RecoveryService.create_measurement(
                session=session,
                outcome=outcome,
                context=context,
                action=None,
                cost_of_recovery=0,
            )

    # 1. A RecoveryMeasurement object was returned
    assert measurement is not None
    assert isinstance(measurement, RecoveryMeasurement)

    # 2. session.flush() was called at least twice (baseline + measurement/outbox)
    assert session.flush.call_count >= 2

    # 3. session.add() was called for baseline, measurement, and outbox
    #    (at minimum 3 objects: BaselineDecision, RecoveryMeasurement, KnowledgeOutbox)
    assert session.add.call_count >= 3

    # 4. Verify a KnowledgeOutbox object was added with PENDING status
    added_objects = [c.args[0] for c in session.add.call_args_list]
    outbox_entries = [o for o in added_objects if isinstance(o, KnowledgeOutbox)]
    assert len(outbox_entries) == 1, "Expected exactly one KnowledgeOutbox entry to be created"
    assert outbox_entries[0].status == KnowledgeOutboxStatus.PENDING
    assert outbox_entries[0].measurement_id == measurement.id


def test_authoritative_monetary_fields_integer_minor_units():
    """Authoritative monetary fields must use integer minor units across all recovery models."""
    # 1. RecoveryCase
    case = RecoveryCase(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        domain=RecoveryDomain.B2C,
        case_type=CaseType.PAYMENT_FAILED,
        amount_minor=10500,  # 105.00 in minor units (paise/cents)
    )
    assert isinstance(case.amount_minor, int)
    assert case.amount == 10500
    assert isinstance(case.amount, int)

    # 2. RecoveryOutcome
    outcome = RecoveryOutcome(
        id=uuid.uuid4(),
        case_id=case.id,
        tenant_id=case.tenant_id,
        recovered_amount=10500,
        currency="INR",
        outcome_status=RecoveryOutcomeStatus.RECOVERED,
    )
    assert isinstance(outcome.recovered_amount, int)
    assert outcome.recovered_amount_minor == 10500
    outcome.recovered_amount_minor = 20000
    assert outcome.recovered_amount == 20000

    # 3. RecoveryMeasurement
    measurement = RecoveryMeasurement(
        id=uuid.uuid4(),
        outcome_id=outcome.id,
        treatment_recovery=20000,
        estimated_control_recovery=1000,
        incremental_recovery=19000,
        cost_of_recovery=250,
        attribution_window_seconds=86400,
    )
    assert isinstance(measurement.treatment_recovery, int)
    assert isinstance(measurement.estimated_control_recovery, int)
    assert isinstance(measurement.incremental_recovery, int)
    assert isinstance(measurement.cost_of_recovery, int)
    assert measurement.treatment_recovery_minor == 20000
    assert measurement.estimated_control_recovery_minor == 1000
    assert measurement.incremental_recovery_minor == 19000
    assert measurement.action_cost_minor == 250


def test_qdrant_model_and_embedding_dimension():
    """Verify Qdrant memory service model, dimension (768), and vector normalization."""
    assert EmbeddingService.get_dimension() == 768
    assert EmbeddingService.get_model_name() == "BAAI/bge-base-en-v1.5"
    assert QdrantMemoryService.DIMENSION == 768
    assert QdrantMemoryService.DISTANCE == "Cosine"

    vec = EmbeddingService.embed_text("domain:B2C category:TRANSIENT_TECHNICAL action:RETRY outcome:RECOVERED")
    assert len(vec) == 768
    assert all(isinstance(x, float) for x in vec)
    # Check L2 normalization (sum of squares == 1.0)
    norm = sum(x * x for x in vec)
    assert abs(norm - 1.0) < 1e-4


@pytest.mark.asyncio
async def test_attribution_action_attributed():
    """Recovery within attribution window after action -> ACTION_ATTRIBUTED."""
    case = StubCase(uuid.uuid4())
    case.amount_minor = 10000
    tenant = StubTenant()

    action = Action(
        id=uuid.uuid4(),
        case_id=case.id,
        tenant_id=tenant.id,
        created_at=datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
    )

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        make_scalar_result(None),  # idempotency check on action_id
        make_scalar_result(None),  # attribution window default 86400
    ])
    session.add = MagicMock()
    session.flush = AsyncMock()

    provider_result = ProviderExecutionResult(
        status=ProviderOutcomeStatus.SUCCEEDED,
        provider="razorpay",
        retry_safety=RetrySafety.SAFE_TO_RETRY,
        raw_metadata={"amount": 10000},
    )

    recovered_at = datetime(2026, 9, 1, 11, 0, 0, tzinfo=timezone.utc)  # 1 hour after action
    outcome = await RecoveryService.record_outcome(
        session=session,
        case=case,
        tenant=tenant,
        action=action,
        provider_result=provider_result,
        recovered_at_override=recovered_at,
    )

    assert outcome.recovery_source == RecoverySource.ACTION_ATTRIBUTED
    assert outcome.outcome_status == RecoveryOutcomeStatus.RECOVERED
    assert outcome.recovered_amount == 10000


@pytest.mark.asyncio
async def test_attribution_organic_recovery_no_action():
    """Recovery with no action taken -> ORGANIC_RECOVERY."""
    case = StubCase(uuid.uuid4())
    case.amount_minor = 10000
    tenant = StubTenant()

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        make_scalar_result(None),  # attribution window default 86400
    ])
    session.add = MagicMock()
    session.flush = AsyncMock()

    provider_result = ProviderExecutionResult(
        status=ProviderOutcomeStatus.SUCCEEDED,
        provider="razorpay",
        retry_safety=RetrySafety.SAFE_TO_RETRY,
        raw_metadata={"amount": 10000},
    )

    outcome = await RecoveryService.record_outcome(
        session=session,
        case=case,
        tenant=tenant,
        action=None,
        provider_result=provider_result,
    )

    assert outcome.recovery_source == RecoverySource.ORGANIC_RECOVERY
    assert outcome.outcome_status == RecoveryOutcomeStatus.RECOVERED


@pytest.mark.asyncio
async def test_attribution_organic_recovery_action_after_payment():
    """Payment completed before action was created -> ORGANIC_RECOVERY."""
    case = StubCase(uuid.uuid4())
    case.amount_minor = 10000
    tenant = StubTenant()

    action = Action(
        id=uuid.uuid4(),
        case_id=case.id,
        tenant_id=tenant.id,
        created_at=datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc),
    )

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        make_scalar_result(None),  # idempotency check
        make_scalar_result(None),  # attribution window default 86400
    ])
    session.add = MagicMock()
    session.flush = AsyncMock()

    provider_result = ProviderExecutionResult(
        status=ProviderOutcomeStatus.SUCCEEDED,
        provider="razorpay",
        retry_safety=RetrySafety.SAFE_TO_RETRY,
        raw_metadata={"amount": 10000},
    )

    # Payment succeeded at 11:00, action was at 12:00
    recovered_at = datetime(2026, 9, 1, 11, 0, 0, tzinfo=timezone.utc)
    outcome = await RecoveryService.record_outcome(
        session=session,
        case=case,
        tenant=tenant,
        action=action,
        provider_result=provider_result,
        recovered_at_override=recovered_at,
    )

    assert outcome.recovery_source == RecoverySource.ORGANIC_RECOVERY


@pytest.mark.asyncio
async def test_attribution_unknown_outside_window():
    """Recovery outside attribution window (>86400s) -> UNKNOWN."""
    case = StubCase(uuid.uuid4())
    case.amount_minor = 10000
    tenant = StubTenant()

    action = Action(
        id=uuid.uuid4(),
        case_id=case.id,
        tenant_id=tenant.id,
        created_at=datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
    )

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        make_scalar_result(None),  # idempotency check
        make_scalar_result(None),  # attribution window default 86400
    ])
    session.add = MagicMock()
    session.flush = AsyncMock()

    provider_result = ProviderExecutionResult(
        status=ProviderOutcomeStatus.SUCCEEDED,
        provider="razorpay",
        retry_safety=RetrySafety.SAFE_TO_RETRY,
        raw_metadata={"amount": 10000},
    )

    # 3 days later (> 86400s)
    recovered_at = datetime(2026, 9, 4, 10, 0, 0, tzinfo=timezone.utc)
    outcome = await RecoveryService.record_outcome(
        session=session,
        case=case,
        tenant=tenant,
        action=action,
        provider_result=provider_result,
        recovered_at_override=recovered_at,
    )

    assert outcome.recovery_source in (RecoverySource.UNKNOWN, RecoverySource.UNKNOWN_ATTRIBUTION)


@pytest.mark.asyncio
async def test_attribution_failed_outcome_is_unknown():
    """Failed provider execution results in FAILED status and UNKNOWN attribution."""
    case = StubCase(uuid.uuid4())
    tenant = StubTenant()

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        make_scalar_result(None),  # attribution window default 86400
    ])
    session.add = MagicMock()
    session.flush = AsyncMock()

    provider_result = ProviderExecutionResult(
        status=ProviderOutcomeStatus.FAILED,
        provider="razorpay",
        retry_safety=RetrySafety.NOT_RETRIABLE,
        error_code="PAYMENT_DECLINED",
    )

    outcome = await RecoveryService.record_outcome(
        session=session,
        case=case,
        tenant=tenant,
        action=None,
        provider_result=provider_result,
    )

    assert outcome.outcome_status == RecoveryOutcomeStatus.FAILED
    assert outcome.recovered_amount == 0
    assert outcome.recovery_source in (RecoverySource.UNKNOWN, RecoverySource.UNKNOWN_ATTRIBUTION)


@pytest.mark.asyncio
async def test_measurement_idempotency_returns_existing():
    """create_measurement must return existing record if outcome_id already measured."""
    context = StubContext()
    outcome = make_outcome(tenant_id=context.tenant.id, case_id=context.case.id)

    existing_measurement = RecoveryMeasurement(
        id=uuid.uuid4(),
        outcome_id=outcome.id,
        treatment_recovery=1000,
        incremental_recovery=950,
    )

    session = AsyncMock()
    # First execute call is the idempotency check
    session.execute = AsyncMock(return_value=make_scalar_result(existing_measurement))
    session.add = MagicMock()
    session.flush = AsyncMock()

    res = await RecoveryService.create_measurement(
        session=session,
        outcome=outcome,
        context=context,
        action=None,
    )

    assert res is existing_measurement
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_baseline_vs_actual_action_treatment_and_control():
    """
    Treatment variant: IRV = treatment - baseline control recovery.
    Control variant: IRV = 0 (holdout).
    """
    def _close_coro(coro):
        coro.close()
        return MagicMock()

    # 1. Treatment variant
    context_t = StubContext()
    context_t.case.amount = 10000  # 10000 minor units
    context_t.case.amount_minor = 10000
    outcome_t = make_outcome(tenant_id=context_t.tenant.id, case_id=context_t.case.id)
    outcome_t.recovered_amount = 10000

    session_t = build_mock_session()

    with patch.object(asyncio, "get_running_loop") as mock_loop:
        mock_loop.return_value = MagicMock()
        mock_loop.return_value.create_task = MagicMock(side_effect=_close_coro)
        with patch.object(RecoveryService, "assign_experiment", return_value=(None, "TREATMENT")):
            meas_treatment = await RecoveryService.create_measurement(
                session=session_t,
                outcome=outcome_t,
                context=context_t,
                action=None,
            )

    # Baseline expected recovery: 5% of 10000 = 500
    assert meas_treatment.estimated_control_recovery == 500
    assert meas_treatment.treatment_recovery == 10000
    # Incremental recovery = 10000 - 500 = 9500
    assert meas_treatment.incremental_recovery == 9500
    assert meas_treatment.experiment_variant == "TREATMENT"

    # 2. Control variant (holdout)
    context_c = StubContext()
    context_c.case.amount = 10000
    context_c.case.amount_minor = 10000
    outcome_c = make_outcome(tenant_id=context_c.tenant.id, case_id=context_c.case.id)
    outcome_c.recovered_amount = 10000

    session_c = build_mock_session()

    with patch.object(asyncio, "get_running_loop") as mock_loop:
        mock_loop.return_value = MagicMock()
        mock_loop.return_value.create_task = MagicMock(side_effect=_close_coro)
        with patch.object(RecoveryService, "assign_experiment", return_value=(None, "CONTROL")):
            meas_control = await RecoveryService.create_measurement(
                session=session_c,
                outcome=outcome_c,
                context=context_c,
                action=None,
            )

    # For control, observed recovery is in control_recovery, treatment_recovery is 0
    assert meas_control.control_recovery == 10000
    assert meas_control.treatment_recovery == 0
    assert meas_control.incremental_recovery == 0
    assert meas_control.experiment_variant == "CONTROL"


@pytest.mark.asyncio
async def test_qdrant_indexing_failure_is_non_fatal():
    """Qdrant indexing failure must not raise or roll back; marks outbox FAILED gracefully."""
    session = AsyncMock()
    session.flush = AsyncMock()

    item = KnowledgeOutbox(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        measurement_id=uuid.uuid4(),
        payload={"category": "TEST"},
        status=KnowledgeOutboxStatus.CLAIMED,
        attempt_count=1,
        max_retries=3,
    )

    with patch("app.services.qdrant_indexer.QdrantMemoryService.index_recovery_measurement",
               side_effect=QdrantIndexingError("Qdrant cluster unavailable")):
        success = await QdrantIndexerWorker.process_item(session, item)

    assert success is False
    assert item.status == KnowledgeOutboxStatus.FAILED
    assert "Qdrant cluster unavailable" in item.last_error
    assert session.flush.called


@pytest.mark.asyncio
async def test_qdrant_indexing_dead_letters_after_max_retries():
    """KnowledgeOutbox reaches max_retries -> DEAD_LETTERED."""
    session = AsyncMock()
    session.flush = AsyncMock()

    item = KnowledgeOutbox(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        measurement_id=uuid.uuid4(),
        payload={"category": "TEST"},
        status=KnowledgeOutboxStatus.CLAIMED,
        attempt_count=3,
        max_retries=3,
    )

    with patch("app.services.qdrant_indexer.QdrantMemoryService.index_recovery_measurement",
               side_effect=QdrantIndexingError("Permanent failure")):
        success = await QdrantIndexerWorker.process_item(session, item)

    assert success is False
    assert item.status == KnowledgeOutboxStatus.DEAD_LETTERED


# ===========================================================================
# Phase 5 Final Hardening: 10 Explicit Verification Tests
# ===========================================================================

def test_1_heuristic_baseline_is_labeled_as_estimate():
    """1. Heuristic baseline is explicitly modeled and labeled as an unvalidated estimate."""
    context = StubContext()
    context.case.amount = 20000  # 200.00 minor units
    context.case.amount_minor = 20000

    baseline = BaselineService.get_deterministic_baseline(context)

    # Must be explicitly modeled as deterministic heuristic estimate
    assert baseline.baseline_method == "deterministic_heuristic"
    assert baseline.is_estimate is True
    assert "estimate" in baseline.provenance.lower()
    assert "counterfactual" in baseline.provenance.lower()
    assert baseline.policy_version == "v1.0.0-baseline"
    assert baseline.baseline_policy_version == "v1.0.0-baseline"
    # 5% of 20000 = 1000
    assert baseline.expected_recovery_amount == 1000
    assert baseline.baseline_expected_recovery == 1000


@pytest.mark.asyncio
async def test_2_treatment_observed_recovery():
    """2. Case assigned to TREATMENT tracks observed treatment recovery."""
    context = StubContext()
    context.case.amount = 10000
    outcome = make_outcome(tenant_id=context.tenant.id, case_id=context.case.id)
    outcome.recovered_amount = 8000

    session = build_mock_session()

    def _close_coro(coro):
        coro.close()
        return MagicMock()

    with patch.object(asyncio, "get_running_loop") as mock_loop:
        mock_loop.return_value = MagicMock()
        mock_loop.return_value.create_task = MagicMock(side_effect=_close_coro)
        with patch.object(RecoveryService, "assign_experiment", return_value=(None, "TREATMENT")):
            meas = await RecoveryService.create_measurement(
                session=session,
                outcome=outcome,
                context=context,
                action=None,
            )

    assert meas.treatment_recovery == 8000
    assert meas.treatment_recovery_minor == 8000
    assert meas.control_recovery == 0
    assert meas.observed_recovery == 8000
    assert meas.experiment_variant == "TREATMENT"


@pytest.mark.asyncio
async def test_3_control_observed_recovery():
    """3. Case assigned to CONTROL tracks observed control recovery separately."""
    context = StubContext()
    context.case.amount = 10000
    outcome = make_outcome(tenant_id=context.tenant.id, case_id=context.case.id)
    outcome.recovered_amount = 7500

    session = build_mock_session()

    def _close_coro(coro):
        coro.close()
        return MagicMock()

    with patch.object(asyncio, "get_running_loop") as mock_loop:
        mock_loop.return_value = MagicMock()
        mock_loop.return_value.create_task = MagicMock(side_effect=_close_coro)
        with patch.object(RecoveryService, "assign_experiment", return_value=(None, "CONTROL")):
            meas = await RecoveryService.create_measurement(
                session=session,
                outcome=outcome,
                context=context,
                action=None,
            )

    # Under control holdout: treatment was not given -> treatment_recovery is 0
    assert meas.treatment_recovery == 0
    # Observed control recovery is tracked in control_recovery
    assert meas.control_recovery == 7500
    assert meas.control_recovery_minor == 7500
    assert meas.observed_recovery == 7500
    assert meas.experiment_variant == "CONTROL"


@pytest.mark.asyncio
async def test_4_incremental_estimate_from_treatment_and_control():
    """4. Incremental recovery estimate distinguishes observed treatment/control from baseline estimate."""
    context = StubContext()
    context.case.amount = 10000  # 10000 minor units
    outcome = make_outcome(tenant_id=context.tenant.id, case_id=context.case.id)
    outcome.recovered_amount = 10000

    session = build_mock_session()

    def _close_coro(coro):
        coro.close()
        return MagicMock()

    with patch.object(asyncio, "get_running_loop") as mock_loop:
        mock_loop.return_value = MagicMock()
        mock_loop.return_value.create_task = MagicMock(side_effect=_close_coro)
        with patch.object(RecoveryService, "assign_experiment", return_value=(None, "TREATMENT")):
            meas = await RecoveryService.create_measurement(
                session=session,
                outcome=outcome,
                context=context,
                action=None,
            )

    # Baseline counterfactual estimate: 5% of 10000 = 500
    assert meas.estimated_control_recovery == 500
    assert meas.baseline_expected_recovery == 500
    # Incremental estimate = 10000 - 500 = 9500
    assert meas.incremental_recovery == 9500
    assert meas.incremental_recovery_estimate == 9500
    assert meas.is_counterfactual_estimate is True
    assert meas.baseline_method == "deterministic_heuristic"


@pytest.mark.asyncio
async def test_5_recovery_outside_attribution_window():
    """5. Recovery outside attribution window exceeds threshold and records provenance."""
    case = StubCase(uuid.uuid4())
    case.amount_minor = 10000
    tenant = StubTenant()

    action = Action(
        id=uuid.uuid4(),
        case_id=case.id,
        tenant_id=tenant.id,
        created_at=datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
    )

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        make_scalar_result(None),  # idempotency check
        make_scalar_result(None),  # default window 86400
    ])
    session.add = MagicMock()
    session.flush = AsyncMock()

    provider_result = ProviderExecutionResult(
        status=ProviderOutcomeStatus.SUCCEEDED,
        provider="razorpay",
        retry_safety=RetrySafety.SAFE_TO_RETRY,
        raw_metadata={"amount": 10000},
    )

    # Succeeded 48 hours later (> 86400s window)
    recovered_at = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)
    outcome = await RecoveryService.record_outcome(
        session=session,
        case=case,
        tenant=tenant,
        action=action,
        provider_result=provider_result,
        recovered_at_override=recovered_at,
    )

    assert outcome.outcome_status == RecoveryOutcomeStatus.RECOVERED
    assert outcome.recovery_source == RecoverySource.UNKNOWN_ATTRIBUTION
    assert outcome.attribution_provenance["attribution_window_seconds"] == 86400
    assert "outside attribution window" in outcome.attribution_decision.lower()


@pytest.mark.asyncio
async def test_6_recovered_but_unknown_attribution():
    """6. Recovered payment outside window separates outcome_status from attribution_source."""
    case = StubCase(uuid.uuid4())
    tenant = StubTenant()

    action = Action(
        id=uuid.uuid4(),
        case_id=case.id,
        tenant_id=tenant.id,
        created_at=datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
    )

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        make_scalar_result(None),
        make_scalar_result(None),
    ])
    session.add = MagicMock()
    session.flush = AsyncMock()

    provider_result = ProviderExecutionResult(
        status=ProviderOutcomeStatus.SUCCEEDED,
        provider="razorpay",
        retry_safety=RetrySafety.SAFE_TO_RETRY,
        raw_metadata={"amount": 10000},
    )

    recovered_at = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)
    outcome = await RecoveryService.record_outcome(
        session=session,
        case=case,
        tenant=tenant,
        action=action,
        provider_result=provider_result,
        recovered_at_override=recovered_at,
    )

    # Must NOT collapse unrecovered outcome status into attribution
    assert outcome.outcome_status == RecoveryOutcomeStatus.RECOVERED
    assert outcome.recovered_amount == 10000
    assert outcome.recovery_source == RecoverySource.UNKNOWN_ATTRIBUTION
    assert outcome.attribution_source == RecoverySource.UNKNOWN_ATTRIBUTION


@pytest.mark.asyncio
async def test_7_failed_outcome_plus_unknown_attribution():
    """7. Failed provider execution results in FAILED outcome_status and UNKNOWN_ATTRIBUTION."""
    case = StubCase(uuid.uuid4())
    tenant = StubTenant()

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        make_scalar_result(None),
    ])
    session.add = MagicMock()
    session.flush = AsyncMock()

    provider_result = ProviderExecutionResult(
        status=ProviderOutcomeStatus.FAILED,
        provider="razorpay",
        retry_safety=RetrySafety.NOT_RETRIABLE,
        error_code="PAYMENT_DECLINED",
    )

    outcome = await RecoveryService.record_outcome(
        session=session,
        case=case,
        tenant=tenant,
        action=None,
        provider_result=provider_result,
    )

    assert outcome.outcome_status == RecoveryOutcomeStatus.FAILED
    assert outcome.recovered_amount == 0
    assert outcome.recovery_source == RecoverySource.UNKNOWN_ATTRIBUTION
    assert outcome.attribution_source == RecoverySource.UNKNOWN_ATTRIBUTION
    assert "failed" in outcome.attribution_decision.lower()


@pytest.mark.asyncio
async def test_8_action_attributed_recovery():
    """8. Action exists and payment succeeds within window -> ACTION_ATTRIBUTED with provenance."""
    case = StubCase(uuid.uuid4())
    tenant = StubTenant()

    action_ts = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    action = Action(
        id=uuid.uuid4(),
        case_id=case.id,
        tenant_id=tenant.id,
        created_at=action_ts,
    )

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        make_scalar_result(None),
        make_scalar_result(None),
    ])
    session.add = MagicMock()
    session.flush = AsyncMock()

    provider_result = ProviderExecutionResult(
        status=ProviderOutcomeStatus.SUCCEEDED,
        provider="razorpay",
        retry_safety=RetrySafety.SAFE_TO_RETRY,
        raw_metadata={"amount": 10000},
    )

    recovered_at = datetime(2026, 9, 1, 10, 30, 0, tzinfo=timezone.utc)  # 30 mins after action
    outcome = await RecoveryService.record_outcome(
        session=session,
        case=case,
        tenant=tenant,
        action=action,
        provider_result=provider_result,
        recovered_at_override=recovered_at,
    )

    assert outcome.outcome_status == RecoveryOutcomeStatus.RECOVERED
    assert outcome.recovery_source == RecoverySource.ACTION_ATTRIBUTED
    assert outcome.attribution_source == RecoverySource.ACTION_ATTRIBUTED
    # Check lightweight provenance capture
    prov = outcome.attribution_provenance
    assert prov is not None
    assert prov["attribution_window_seconds"] == 86400
    assert prov["attribution_policy_version"] == "v1.0.0-attribution"
    assert prov["action_timestamp"] == action_ts.isoformat()
    assert prov["recovery_timestamp"] == recovered_at.isoformat()
    assert prov["attribution_source"] == "ACTION_ATTRIBUTED"
    assert "following action dispatch" in outcome.attribution_decision


@pytest.mark.asyncio
async def test_9_organic_recovery():
    """9. Recovery without action or prior to action is attributed as ORGANIC_RECOVERY."""
    # Scenario A: No action taken
    case_a = StubCase(uuid.uuid4())
    tenant_a = StubTenant()

    session_a = AsyncMock()
    session_a.execute = AsyncMock(side_effect=[make_scalar_result(None)])
    session_a.add = MagicMock()
    session_a.flush = AsyncMock()

    provider_result = ProviderExecutionResult(
        status=ProviderOutcomeStatus.SUCCEEDED,
        provider="razorpay",
        retry_safety=RetrySafety.SAFE_TO_RETRY,
        raw_metadata={"amount": 5000},
    )

    outcome_a = await RecoveryService.record_outcome(
        session=session_a,
        case=case_a,
        tenant=tenant_a,
        action=None,
        provider_result=provider_result,
    )

    assert outcome_a.outcome_status == RecoveryOutcomeStatus.RECOVERED
    assert outcome_a.recovery_source == RecoverySource.ORGANIC_RECOVERY
    assert "without automated recovery action" in outcome_a.attribution_decision

    # Scenario B: Payment completed before action was created
    case_b = StubCase(uuid.uuid4())
    tenant_b = StubTenant()

    action_b = Action(
        id=uuid.uuid4(),
        case_id=case_b.id,
        tenant_id=tenant_b.id,
        created_at=datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc),
    )

    session_b = AsyncMock()
    session_b.execute = AsyncMock(side_effect=[
        make_scalar_result(None),
        make_scalar_result(None),
    ])
    session_b.add = MagicMock()
    session_b.flush = AsyncMock()

    outcome_b = await RecoveryService.record_outcome(
        session=session_b,
        case=case_b,
        tenant=tenant_b,
        action=action_b,
        provider_result=provider_result,
        recovered_at_override=datetime(2026, 9, 1, 11, 0, 0, tzinfo=timezone.utc),
    )

    assert outcome_b.outcome_status == RecoveryOutcomeStatus.RECOVERED
    assert outcome_b.recovery_source == RecoverySource.ORGANIC_RECOVERY
    assert "before recovery action was created" in outcome_b.attribution_decision


@pytest.mark.asyncio
async def test_10_duplicate_measurement():
    """10. Duplicate measurement for the same outcome_id returns existing record idempotently."""
    context = StubContext()
    outcome = make_outcome(tenant_id=context.tenant.id, case_id=context.case.id)

    existing_measurement = RecoveryMeasurement(
        id=uuid.uuid4(),
        outcome_id=outcome.id,
        treatment_recovery=5000,
        incremental_recovery=4750,
    )

    session = AsyncMock()
    # Idempotency check finds existing record
    session.execute = AsyncMock(return_value=make_scalar_result(existing_measurement))
    session.add = MagicMock()
    session.flush = AsyncMock()

    result = await RecoveryService.create_measurement(
        session=session,
        outcome=outcome,
        context=context,
        action=None,
    )

    assert result is existing_measurement
    assert result.id == existing_measurement.id
    session.add.assert_not_called()
