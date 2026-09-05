import pytest
import uuid
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from app.domain.recovery_case import RecoveryCase, RecoveryDomain, CaseType, CaseStatus
from app.domain.action import Action, ActionStatus, RecoveryAction
from app.domain.events import ProviderEvent
from app.domain.tenant import Tenant, TenantType
from app.domain.recovery.recovery_outcome import RecoveryOutcome, RecoveryOutcomeStatus, RecoverySource
from app.domain.recovery.recovery_measurement import RecoveryMeasurement
from app.services.ingestion import _handle_payment_success_event, process_provider_event
from app.api.webhooks.razorpay import _process_event_with_own_session


@pytest.mark.asyncio
async def test_fresh_session_background_processing_opens_session_and_processes():
    """
    Proves that _process_event_with_own_session:
    1. Opens its own fresh session from async_session_factory (independent of closed request-scoped session).
    2. Reloads the ProviderEvent by ID.
    3. Calls process_provider_event with the fresh session.
    """
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_event = MagicMock(spec=ProviderEvent)
    mock_event.id = uuid.uuid4()
    mock_event.external_id = "ev_test_123"
    mock_event.payload = {
        "event": "payment_link.paid",
        "account_id": "acc_test",
        "payload": {
            "payment_link": {
                "entity": {
                    "id": "plink_test_123",
                    "amount": 10000,
                    "status": "paid",
                    "notes": {"case_id": str(uuid.uuid4()), "action_id": str(uuid.uuid4())},
                }
            }
        },
    }

    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = mock_event
    mock_session.execute.return_value = mock_res

    # async_session_factory returns a context manager
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session
    mock_factory.return_value.__aexit__.return_value = None

    with patch("app.api.webhooks.razorpay.async_session_factory", mock_factory), \
         patch("app.api.webhooks.razorpay.process_provider_event", new_callable=AsyncMock) as mock_process:
        await _process_event_with_own_session(
            event_id="ev_test_123",
            provider_event_id=str(mock_event.id),
            event_type="payment_link.paid",
        )

        mock_factory.assert_called_once()
        mock_process.assert_called_once_with(mock_session, mock_event)


@pytest.mark.asyncio
async def test_handle_payment_success_event_transitions_case_and_records_measurement():
    """
    Proves that _handle_payment_success_event:
    1. Reconciles the case and action.
    2. Transitions Case to RECOVERED.
    3. Sets case.context['recovery_stage'] = 'RECOVERED'.
    4. Transitions Action to ActionStatus.SUCCEEDED.
    5. Calls RecoveryService.record_outcome.
    6. Calls RecoveryService.create_measurement.
    """
    session = AsyncMock()
    tenant = Tenant(id=uuid.uuid4(), type=TenantType.CONSUMER, name="Test Tenant")

    case_id = uuid.uuid4()
    action_id = uuid.uuid4()

    case = RecoveryCase(
        id=case_id,
        tenant_id=tenant.id,
        domain=RecoveryDomain.B2C,
        case_type=CaseType.PAYMENT_FAILED,
        status=CaseStatus.OPEN,
        amount_minor=10000,
        context={"recovery_stage": "WAITING_FOR_PAYMENT"},
    )

    action = Action(
        id=action_id,
        case_id=case.id,
        action_type=RecoveryAction.GENERATE_PAYMENT_LINK,
        status=ActionStatus.AUTHORIZED,
    )

    event = ProviderEvent(
        id=uuid.uuid4(),
        provider="razorpay",
        external_id="ev_test_success",
        payload={
            "event": "payment_link.paid",
            "payload": {
                "payment_link": {
                    "entity": {
                        "id": "plink_test_abc",
                        "amount": 10000,
                        "status": "paid",
                        "notes": {"case_id": str(case_id), "action_id": str(action_id)},
                    }
                },
                "payment": {
                    "entity": {
                        "id": "pay_test_xyz",
                        "amount": 10000,
                        "status": "captured",
                    }
                },
            },
        },
        idempotency_key="razorpay_ev_test_success",
    )

    # Mock execute queries for case and action
    async def mock_execute(query, *args, **kwargs):
        res = MagicMock()
        q_str = str(query)
        if "recovery_case" in q_str:
            res.scalar_one_or_none.return_value = case
        elif "action" in q_str:
            res.scalar_one_or_none.return_value = action
        elif "recovery_classification" in q_str:
            res.scalar_one_or_none.return_value = None
        else:
            res.scalar_one_or_none.return_value = None
        return res

    session.execute = AsyncMock(side_effect=mock_execute)

    mock_outcome = MagicMock(spec=RecoveryOutcome)
    mock_outcome.id = uuid.uuid4()
    mock_outcome.recovered_amount = 10000
    mock_outcome.recovery_source = RecoverySource.ACTION_ATTRIBUTED
    mock_outcome.outcome_status = RecoveryOutcomeStatus.RECOVERED

    with patch("app.services.ingestion.RecoveryService.record_outcome", new_callable=AsyncMock, return_value=mock_outcome) as mock_rec_outcome, \
         patch("app.services.ingestion.RecoveryService.create_measurement", new_callable=AsyncMock) as mock_create_meas, \
         patch("app.services.ingestion.ActivityService.record_event", new_callable=AsyncMock), \
         patch("app.services.ingestion.TelegramNotifier.notify_recovery_verified", new_callable=AsyncMock):

        await _handle_payment_success_event(session, event, tenant)

        # Assert case transitioned
        assert case.status == CaseStatus.RECOVERED
        assert case.context["recovery_stage"] == "RECOVERED"
        assert case.context["payment_link_id"] == "plink_test_abc"
        assert case.context["payment_id"] == "pay_test_xyz"

        # Assert action transitioned
        assert action.status == ActionStatus.SUCCEEDED

        # Assert outcome and measurement recorded
        mock_rec_outcome.assert_called_once()
        mock_create_meas.assert_called_once()


@pytest.mark.asyncio
async def test_idempotent_replay_of_persisted_event():
    """
    Proves that replaying an already-recovered case via _handle_payment_success_event
    is safe and idempotent, preserving RECOVERED status and calling record_outcome.
    """
    session = AsyncMock()
    tenant = Tenant(id=uuid.uuid4(), type=TenantType.CONSUMER, name="Test Tenant")

    case_id = uuid.uuid4()
    action_id = uuid.uuid4()

    case = RecoveryCase(
        id=case_id,
        tenant_id=tenant.id,
        domain=RecoveryDomain.B2C,
        case_type=CaseType.PAYMENT_FAILED,
        status=CaseStatus.RECOVERED,
        amount_minor=10000,
        context={"recovery_stage": "RECOVERED"},
    )

    action = Action(
        id=action_id,
        case_id=case.id,
        action_type=RecoveryAction.GENERATE_PAYMENT_LINK,
        status=ActionStatus.SUCCEEDED,
    )

    event = ProviderEvent(
        id=uuid.uuid4(),
        provider="razorpay",
        external_id="ev_test_replay",
        payload={
            "event": "payment_link.paid",
            "payload": {
                "payment_link": {
                    "entity": {
                        "id": "plink_test_replay",
                        "amount": 10000,
                        "notes": {"case_id": str(case_id), "action_id": str(action_id)},
                    }
                }
            },
        },
        idempotency_key="razorpay_ev_test_replay",
    )

    async def mock_execute(query, *args, **kwargs):
        res = MagicMock()
        q_str = str(query)
        if "recovery_case" in q_str:
            res.scalar_one_or_none.return_value = case
        elif "action" in q_str:
            res.scalar_one_or_none.return_value = action
        elif "recovery_classification" in q_str:
            res.scalar_one_or_none.return_value = None
        else:
            res.scalar_one_or_none.return_value = None
        return res

    session.execute = AsyncMock(side_effect=mock_execute)

    mock_outcome = MagicMock(spec=RecoveryOutcome)
    mock_outcome.id = uuid.uuid4()
    mock_outcome.recovered_amount = 10000
    mock_outcome.recovery_source = RecoverySource.ACTION_ATTRIBUTED

    with patch("app.services.ingestion.RecoveryService.record_outcome", new_callable=AsyncMock, return_value=mock_outcome) as mock_rec_outcome, \
         patch("app.services.ingestion.RecoveryService.create_measurement", new_callable=AsyncMock) as mock_create_meas, \
         patch("app.services.ingestion.ActivityService.record_event", new_callable=AsyncMock), \
         patch("app.services.ingestion.TelegramNotifier.notify_recovery_verified", new_callable=AsyncMock):

        await _handle_payment_success_event(session, event, tenant)

        # Still RECOVERED
        assert case.status == CaseStatus.RECOVERED
        assert case.context["recovery_stage"] == "RECOVERED"
        mock_rec_outcome.assert_called_once()
        mock_create_meas.assert_called_once()
