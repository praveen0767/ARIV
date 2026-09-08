import hmac
import hashlib
import logging
from uuid import UUID
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Header, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.infrastructure.database import get_db_session
from app.core.config import settings
from app.services.ingestion import resolve_tenant
from app.services.dashboard import DashboardService
from app.domain.tenant import Tenant
from app.domain.recovery.recovery_outcome import RecoveryOutcome
from app.domain.recovery.recovery_measurement import RecoveryMeasurement
from app.domain.recovery.experiment import Experiment
from app.domain.recovery_case import RecoveryCase

logger = logging.getLogger("ariv.api.recovery")

router = APIRouter(prefix="/v1/recovery", tags=["recovery"])


# ---------------------------------------------------------------------------
# Auth dependency — mirrors the existing Razorpay webhook trust pattern:
#   X-Signature (HMAC-SHA256 of account_id with INTERNAL_API_KEY)
#   X-Account-ID (identifies the tenant)
# ---------------------------------------------------------------------------
async def get_current_tenant(
    request: Request,
    x_account_id: str = Header(..., alias="X-Account-ID"),
    x_signature: str = Header(..., alias="X-Signature"),
    session: AsyncSession = Depends(get_db_session),
) -> Tenant:
    """
    Resolves the calling tenant using the same trust mechanism as the Razorpay
    webhook:  an HMAC-SHA256 signature of `account_id` using INTERNAL_API_KEY.

    Callers must set:
        X-Account-ID: <account_id>
        X-Signature:  HMAC-SHA256(key=INTERNAL_API_KEY, msg=account_id).hexdigest()
    """
    expected = hmac.new(
        settings.INTERNAL_API_KEY.encode("utf-8"),
        x_account_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, x_signature):
        logger.warning("Recovery API: invalid X-Signature for account_id=%s", x_account_id)
        raise HTTPException(status_code=401, detail="Invalid signature")

    tenant = await resolve_tenant(session, x_account_id)
    if tenant is None:
        raise HTTPException(status_code=401, detail="Unknown account")
    return tenant


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/cases/{case_id}")
async def get_case_measurement(
    case_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    tenant: Tenant = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Get recovery case with outcome and measurement — tenant-scoped."""
    res = await session.execute(
        select(RecoveryCase).where(
            RecoveryCase.id == case_id,
            RecoveryCase.tenant_id == tenant.id,
        )
    )
    case = res.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    outcome_res = await session.execute(
        select(RecoveryOutcome).where(RecoveryOutcome.case_id == case.id)
    )
    outcome = outcome_res.scalar_one_or_none()

    measurement = None
    if outcome:
        meas_res = await session.execute(
            select(RecoveryMeasurement).where(
                RecoveryMeasurement.outcome_id == outcome.id
            )
        )
        measurement = meas_res.scalar_one_or_none()

    return {
        "case": {
            "id": str(case.id),
            "tenant_id": str(case.tenant_id),
            "domain": case.domain.value if hasattr(case.domain, "value") else str(case.domain),
            "case_type": case.case_type.value if hasattr(case.case_type, "value") else str(case.case_type),
            "status": case.status.value if hasattr(case.status, "value") else str(case.status),
            "amount_minor": case.amount or 0,
            "created_at": case.created_at.isoformat() if case.created_at else None,
            "updated_at": case.updated_at.isoformat() if case.updated_at else None,
        },
        "outcome": {
            "id": str(outcome.id),
            "case_id": str(outcome.case_id),
            "outcome_status": outcome.outcome_status.value if hasattr(outcome.outcome_status, "value") else str(outcome.outcome_status),
            "recovered_amount": outcome.recovered_amount,
            "currency": outcome.currency,
            "recovery_source": outcome.recovery_source.value if hasattr(outcome.recovery_source, "value") else str(outcome.recovery_source),
            "recovered_at": outcome.recovered_at.isoformat() if outcome.recovered_at else None,
        } if outcome else None,
        "measurement": {
            "id": str(measurement.id),
            "treatment_recovery": measurement.treatment_recovery,
            "control_recovery": measurement.control_recovery,
            "incremental_recovery": measurement.incremental_recovery,
            "estimated_control_recovery": measurement.estimated_control_recovery,
            "is_counterfactual_estimate": measurement.is_counterfactual_estimate,
        } if measurement else None,
    }


@router.get("/cases/{case_id}/outcome")
async def get_case_outcome(
    case_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    tenant: Tenant = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Get outcome for a case — tenant-scoped."""
    res = await session.execute(
        select(RecoveryCase).where(
            RecoveryCase.id == case_id,
            RecoveryCase.tenant_id == tenant.id,
        )
    )
    case = res.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    out_res = await session.execute(
        select(RecoveryOutcome).where(RecoveryOutcome.case_id == case.id)
    )
    outcome = out_res.scalar_one_or_none()
    if not outcome:
        raise HTTPException(status_code=404, detail="Outcome not found")
    return {
        "outcome": {
            "id": str(outcome.id),
            "case_id": str(outcome.case_id),
            "outcome_status": outcome.outcome_status.value if hasattr(outcome.outcome_status, "value") else str(outcome.outcome_status),
            "recovered_amount": outcome.recovered_amount,
            "currency": outcome.currency,
            "recovery_source": outcome.recovery_source.value if hasattr(outcome.recovery_source, "value") else str(outcome.recovery_source),
            "recovered_at": outcome.recovered_at.isoformat() if outcome.recovered_at else None,
            "provider_reference": outcome.provider_reference,
            "attribution_decision": outcome.attribution_decision,
        }
    }


@router.get("/metrics")
async def get_recovery_metrics(
    session: AsyncSession = Depends(get_db_session),
    tenant: Tenant = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """
    Aggregate recovery metrics for the authenticated tenant.
    Clearly distinguishes:
    - VERIFIED RECOVERIES (provider-confirmed, persisted outcomes)
    - PIPELINE (actions/payment links dispatched, not yet recovered)
    - AT RISK (outstanding revenue)
    - OBSERVED vs ESTIMATED counterfactual recovery
    """
    return await DashboardService.get_tenant_metrics(session=session, tenant=tenant)


@router.get("/experiments/{experiment_id}")
async def get_experiment(
    experiment_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    tenant: Tenant = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Get experiment details — tenant-scoped."""
    res = await session.execute(
        select(Experiment).where(
            Experiment.id == experiment_id,
            Experiment.tenant_id == tenant.id,
        )
    )
    experiment = res.scalar_one_or_none()
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return {
        "experiment": {
            "id": str(experiment.id),
            "tenant_id": str(experiment.tenant_id),
            "name": experiment.name,
            "status": experiment.status.value if hasattr(experiment.status, "value") else str(experiment.status),
            "allocation_percentage": experiment.allocation_percentage,
            "policy_version": experiment.policy_version,
            "created_at": experiment.created_at.isoformat() if experiment.created_at else None,
            "start_at": experiment.start_at.isoformat() if experiment.start_at else None,
            "end_at": experiment.end_at.isoformat() if experiment.end_at else None,
        }
    }


@router.get("/dashboard")
async def get_recovery_dashboard(
    session: AsyncSession = Depends(get_db_session),
    tenant: Tenant = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Aggregate dashboard KPIs, recovery funnel, and action analytics for authenticated tenant."""
    return await DashboardService.get_dashboard_data(session=session, tenant=tenant)


@router.get("/activity")
async def get_activity_stream(
    limit: int = Query(25, ge=1, le=100),
    case_id: Optional[UUID] = Query(None),
    session: AsyncSession = Depends(get_db_session),
    tenant: Tenant = Depends(get_current_tenant),
) -> List[Dict[str, Any]]:
    """Returns authoritative operational activity timeline for the tenant."""
    from app.services.activity import ActivityService
    return await ActivityService.get_recent_activity(session=session, tenant_id=tenant.id, case_id=case_id, limit=limit)


@router.get("/cases")
async def get_recovery_cases(
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    tenant: Tenant = Depends(get_current_tenant),
) -> List[Dict[str, Any]]:
    """List recovery cases with optional status filter and pagination — tenant-scoped."""
    return await DashboardService.get_case_list(
        session=session, tenant=tenant, status=status, limit=limit, offset=offset
    )


@router.get("/cases/{case_id}/full")
async def get_full_case_detail(
    case_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    tenant: Tenant = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """
    Single aggregated view of recovery case:
    - Failure classification & recoverability
    - ARIV proposed action vs PolicyEngine evaluation (safety boundary)
    - Execution attempts and status timeline (with UNKNOWN highlighted)
    - Recovery outcome, attribution, and incremental measurement
    - Tenant-isolated similar past cases from Qdrant memory
    """
    detail = await DashboardService.get_full_case_detail(
        session=session, tenant=tenant, case_id=case_id
    )
    if not detail:
        raise HTTPException(status_code=404, detail="Case not found")
    return detail


@router.get("/cases/{case_id}/similar")
async def get_similar_cases(
    case_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    tenant: Tenant = Depends(get_current_tenant),
) -> List[Dict[str, Any]]:
    """Retrieve similar past recovery cases from Qdrant vector memory — tenant-isolated."""
    detail = await DashboardService.get_full_case_detail(
        session=session, tenant=tenant, case_id=case_id
    )
    if not detail:
        raise HTTPException(status_code=404, detail="Case not found")
    return detail.get("similar_cases", [])


@router.post("/demo/seed")
async def seed_demo_data(
    session: AsyncSession = Depends(get_db_session),
    tenant: Tenant = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """
    Seed 4 deterministic sandbox demo recovery scenarios.
    Security:
    - Requires explicit DEMO_MODE=True in settings
    - HMAC-authenticated via X-Account-ID and X-Signature
    - Strictly tenant-scoped to the authenticated account
    - Deterministic and idempotent
    - Marked with context={'is_demo': True}
    - Rejects with 403 Forbidden if DEMO_MODE is disabled
    """
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=403, detail="Demo seeding is disabled outside demo mode")
    try:
        return await DashboardService.seed_demo_cases(session=session, tenant=tenant)
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))

