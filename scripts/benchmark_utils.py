#!/usr/bin/env python3
"""
scripts/benchmark_utils.py

Shared helpers for the ARIV REAL TEST-MODE webhook benchmark.

The benchmark exercises the EXISTING ARIV ingestion path:
    TEST INPUT -> POST /webhooks/razorpay -> signature verify -> ProviderEvent
    -> RecoveryCase -> Failure Intelligence -> Decision Context -> Qdrant (where available)
    -> AI/decision layer -> PolicyEngine -> Execution Outbox / worker -> recovery outcomes
    -> attribution -> measurement.

It NEVER inserts RecoveryCase/RecoveryOutcome rows directly and NEVER forces a
case into RECOVERED. Every metric is computed from rows the ARIV pipeline itself
persisted in PostgreSQL.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import random
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("ariv.benchmark")

# Ensure the project root is importable when running from any CWD.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select, and_, or_

from app.core.config import settings
from app.domain.events import ProviderEvent
from app.domain.recovery_case import RecoveryCase, CaseStatus
from app.domain.decision import DecisionRecord, PolicyStatus, AutonomyLevel
from app.domain.action import Action, ActionStatus, ExecutionAttempt, ExecutionStatus
from app.domain.recovery.recovery_outcome import RecoveryOutcome, RecoveryOutcomeStatus, RecoverySource
from app.domain.tenant import Tenant, TenantType
from app.infrastructure.database import async_session_factory


# ---------------------------------------------------------------------------
# Identifiers & payload construction
# ---------------------------------------------------------------------------

def generate_benchmark_id() -> str:
    """Unique, sortable benchmark identifier, e.g. bench_20260907_9a2c1e."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suffix = uuid.uuid4().hex[:6]
    return f"bench_{stamp}_{suffix}"


def generate_amounts(count: int, minimum: int, maximum: int, seed: Optional[int] = None) -> List[int]:
    """
    Deterministic varied minor-unit (paise) amounts in [minimum, maximum].

    Uses a seeded RNG so a benchmark run is reproducible while still varied.
    Amounts are rounded to whole rupees (multiple of 100 paise).
    """
    if count <= 0:
        raise ValueError("count must be > 0")
    if minimum < 100 or maximum < minimum:
        raise ValueError("invalid amount bounds (minor units)")

    rng = random.Random(seed if seed is not None else int(time.time()))
    lo = (minimum // 100) * 100
    hi = (maximum // 100) * 100
    if hi < lo:
        hi = lo

    unique = set()
    amounts: List[int] = []
    while len(amounts) < count:
        val = rng.randint(lo, hi)
        if val not in unique:
            unique.add(val)
            amounts.append(val)

    return amounts


@dataclass
class ScenarioSpec:
    """Explicit failure scenario used to build one benchmark case.

    `label` names the taxonomy category this case is meant to exercise (input
    metadata only — it is never used to fabricate a persisted outcome).
    `amount_minor`, `error_code`, and `error_reason` are the webhook inputs
    that the EXISTING pipeline classifies deterministically.
    """
    label: str
    amount_minor: int
    error_code: str
    error_reason: str


def build_failure_payload(
    *,
    benchmark_id: str,
    index: int,
    amount_minor: int,
    account_id: str,
    event_id: str,
    payment_id: str,
    error_code: str = "BAD_REQUEST_ERROR",
    error_reason: str = "Insufficient balance",
) -> Dict[str, Any]:
    """
    Builds a payment.failed webhook payload following the exact shape used by
    scripts/send_test_failure.py. The payment id embeds the benchmark id so the
    resulting RecoveryCase.context["payment_id"] survives ingestion and can be
    correlated back to this benchmark run without any schema change.
    """
    return {
        "event": "payment.failed",
        "account_id": account_id,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "amount": amount_minor,
                    "currency": "INR",
                    "email": f"benchmark_{benchmark_id}_{index}@example.com",
                    "contact": "9876543210",
                    "error_code": error_code,
                    "error_reason": error_reason,
                    "notes": {
                        "case_id": "",
                        "action_id": "",
                        "benchmark_id": benchmark_id,
                    },
                }
            }
        },
    }


def sign_payload(payload: Dict[str, Any], secret: str) -> str:
    """HMAC-SHA256 signature over the exact UTF-8 bytes as razorpay does."""
    raw = json.dumps(payload).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def make_event_id(benchmark_id: str, index: int) -> str:
    return f"evt_{benchmark_id}_{index}"


def make_payment_id(benchmark_id: str, index: int) -> str:
    return f"pay_{benchmark_id}_{index}"


def resolve_webhook_secret() -> str:
    """Webhook secret from config, mirroring send_test_failure.py semantics."""
    secret = getattr(settings, "RAZORPAY_WEBHOOK_SECRET", "") or ""
    return secret if secret and secret != "test_secret" else "test_secret"


async def resolve_benchmark_account_id(default_account_id: str = "acc_benchmark") -> str:
    """
    Returns an account_id that maps to a tenant for this benchmark.

    resolve_tenant() requires an exact Tenant.config["account_id"] match and
    fails closed for unknown accounts once any tenant exists. To guarantee the
    benchmark events are processed (rather than dropped at resolution), this:

      1. reuses an existing mapped account_id when one is already provisioned;
      2. otherwise PROVISIONS a dedicated benchmark tenant bound to
         default_account_id via the ORM.

    Tenant provisioning is operator configuration, NOT a benchmark result row:
    no RecoveryCase/RecoveryOutcome/Decision/Action/Attempt is inserted here.
    """
    async with async_session_factory() as session:
        tenants = (await session.execute(select(Tenant))).scalars().all()
        for tenant in tenants:
            cfg = tenant.config or {}
            mapped = str(cfg.get("account_id", "")).strip()
            if mapped:
                return mapped

        # Provision a dedicated benchmark tenant (idempotent per account_id).
        existing = (
            await session.execute(
                select(Tenant).where(
                    Tenant.config["account_id"].as_string() == default_account_id
                )
            )
        ).scalars().first()
        if existing is None:
            session.add(
                Tenant(
                    type=TenantType.CONSUMER,
                    name=f"Benchmark {default_account_id}",
                    config={"account_id": default_account_id},
                )
            )
            await session.commit()
            logger.info("Provisioned benchmark tenant for account_id=%s", default_account_id)
        return default_account_id


# ---------------------------------------------------------------------------
# Webhook delivery
# ---------------------------------------------------------------------------

@dataclass
class SentEvent:
    index: int
    event_id: str
    payment_id: str
    amount_minor: int
    http_status: int
    response_body: str = ""
    accepted: bool = False


async def send_events(
    *,
    events: List[Dict[str, Any]],
    webhook_url: str,
    webhook_secret: str,
    event_ids: List[str],
    settle_delay: float = 0.0,
) -> List[SentEvent]:
    """POSTs each prepared payload to the existing webhook endpoint with a
    valid Razorpay-style signature. Returns per-event delivery results.

    settle_delay > 0 (scenario mode) sleeps between deliveries so each webhook's
    background decision completes before the next is sent, preserving delivery
    order against the in-memory systemic corridor buffer.
    """
    results: List[SentEvent] = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for i, payload in enumerate(events):
            event_id = event_ids[i]
            signature = sign_payload(payload, webhook_secret)
            headers = {
                "Content-Type": "application/json",
                "x-razorpay-signature": signature,
                "x-razorpay-event-id": event_id,
            }
            try:
                resp = await client.post(webhook_url, content=json.dumps(payload), headers=headers)
                accepted = resp.status_code == 200 and "accepted" in resp.text
                results.append(
                    SentEvent(
                        index=i,
                        event_id=event_id,
                        payment_id=payload["payload"]["payment"]["entity"]["id"],
                        amount_minor=payload["payload"]["payment"]["entity"]["amount"],
                        http_status=resp.status_code,
                        response_body=resp.text[:200],
                        accepted=accepted,
                    )
                )
            except Exception as exc:
                results.append(
                    SentEvent(
                        index=i,
                        event_id=event_id,
                        payment_id=payload["payload"]["payment"]["entity"]["id"],
                        amount_minor=payload["payload"]["payment"]["entity"]["amount"],
                        http_status=0,
                        response_body=f"delivery error: {exc}",
                        accepted=False,
                    )
                )
            if settle_delay > 0:
                await asyncio.sleep(settle_delay)
    return results


# ---------------------------------------------------------------------------
# Persisted-results observation (reads only)
# ---------------------------------------------------------------------------

PAYMENT_ID_PREFIX_KEY = "payment_id"


def _case_payment_id_like(benchmark_id: str):
    """Match RecoveryCase.context->>payment_id LIKE pay_<benchmark_id>_%."""
    return RecoveryCase.context[PAYMENT_ID_PREFIX_KEY].as_string().like(f"pay_{benchmark_id}%")


async def should_keep_polling(benchmark_id: str, expected_count: int) -> bool:
    """True until the pipeline has persisted a case for every expected payment."""
    async with async_session_factory() as session:
        row = (
            await session.execute(
                select(RecoveryCase.id)
                .where(_case_payment_id_like(benchmark_id))
                .limit(expected_count + 1)
            )
        ).scalars().all()
        return len(list(row)) < expected_count


@dataclass
class CaseObservation:
    case_id: str
    payment_id: str
    amount_minor: int
    case_status: str
    recovery_stage: Optional[str] = None
    scenario: Optional[str] = None
    error_code: Optional[str] = None
    error_reason: Optional[str] = None
    route_status: Optional[str] = None
    decision_actions: List[str] = field(default_factory=list)
    decision_policy_statuses: List[str] = field(default_factory=list)
    decision_autonomy_levels: List[str] = field(default_factory=list)
    action_statuses: List[str] = field(default_factory=list)
    attempt_statuses: List[str] = field(default_factory=list)
    execution_failures: int = 0
    outcome_status: Optional[str] = None
    recovered_amount_minor: int = 0
    recovery_source: Optional[str] = None
    human_escalation: bool = False


async def observe_single_case(session, case: RecoveryCase, lookup_payment_id: str, scenario_meta: Optional[Dict[str, Any]] = None) -> CaseObservation:
    ctx = case.context or {}
    decisions = list(
        (
            await session.execute(
                select(DecisionRecord).where(DecisionRecord.case_id == case.id)
            )
        ).scalars().all()
    )

    route_status = None
    for d in decisions:
        prov = d.provenance or {}
        systemic = prov.get("systemic") or {}
        if systemic.get("status"):
            route_status = systemic["status"]
            break

    actions = list(
        (
            await session.execute(
                select(Action).where(Action.case_id == case.id)
            )
        ).scalars().all()
    )

    attempt_statuses: List[str] = []
    execution_failures = 0
    for action in actions:
        attempts = list(
            (
                await session.execute(
                    select(ExecutionAttempt).where(ExecutionAttempt.action_id == action.id)
                )
            ).scalars().all()
        )
        attempt_statuses.extend(a.status.value for a in attempts)
        execution_failures += sum(1 for a in attempts if a.status == ExecutionStatus.FAILED)

    outcomes = list(
        (
            await session.execute(
                select(RecoveryOutcome).where(RecoveryOutcome.case_id == case.id)
            )
        ).scalars().all()
    )
    outcome = outcomes[0] if outcomes else None

    human_escalation = any(
        d.autonomy_level == AutonomyLevel.HUMAN_APPROVAL
        or d.policy_status == PolicyStatus.NEEDS_REVIEW
        for d in decisions
    )

    return CaseObservation(
        case_id=str(case.id),
        payment_id=lookup_payment_id or str(ctx.get("payment_id", "")),
        amount_minor=case.amount_minor or 0,
        case_status=case.status.value if hasattr(case.status, "value") else str(case.status),
        recovery_stage=ctx.get("recovery_stage"),
        scenario=scenario_meta.get("scenario") if scenario_meta else None,
        error_code=scenario_meta.get("error_code") if scenario_meta else None,
        error_reason=scenario_meta.get("error_reason") if scenario_meta else None,
        route_status=route_status,
        decision_actions=[d.proposed_action.value for d in decisions],
        decision_policy_statuses=[d.policy_status.value for d in decisions],
        decision_autonomy_levels=[d.autonomy_level.value for d in decisions],
        action_statuses=[a.status.value for a in actions],
        attempt_statuses=attempt_statuses,
        execution_failures=execution_failures,
        outcome_status=(
            outcome.outcome_status.value
            if outcome and hasattr(outcome.outcome_status, "value")
            else (str(outcome.outcome_status) if outcome else None)
        ),
        recovered_amount_minor=outcome.recovered_amount if outcome else 0,
        recovery_source=(
            outcome.recovery_source.value
            if outcome and hasattr(outcome.recovery_source, "value")
            else (str(outcome.recovery_source) if outcome else None)
        ),
        human_escalation=human_escalation,
    )


async def observe_cases(
    benchmark_id: str,
    expected_payment_ids: List[str],
    scenario_by_payment: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[CaseObservation]:
    """Per-case observations of the persisted pipeline results, scoped strictly
    to the cases tagged with this benchmark_id.

    scenario_by_payment maps an expected payment_id to input metadata
    (scenario/error_code/error_reason) captured at send time — this is purely
    descriptive input context, never treated as a persisted pipeline result.
    """
    scenario_by_payment = scenario_by_payment or {}
    payment_id_to_case: Dict[str, RecoveryCase] = {}
    async with async_session_factory() as session:
        cases = (
            await session.execute(select(RecoveryCase).where(_case_payment_id_like(benchmark_id)))
        ).scalars().all()
        for case in cases:
            pid = str((case.context or {}).get("payment_id", ""))
            payment_id_to_case[pid] = case

        observations: List[CaseObservation] = []
        for pid in expected_payment_ids:
            meta = scenario_by_payment.get(pid, {})
            case = payment_id_to_case.get(pid)
            if case is None:
                observations.append(
                    CaseObservation(
                        case_id="",
                        payment_id=pid,
                        amount_minor=0,
                        case_status="NOT_OBSERVED",
                        scenario=meta.get("scenario"),
                        error_code=meta.get("error_code"),
                        error_reason=meta.get("error_reason"),
                    )
                )
                continue
            observations.append(await observe_single_case(session, case, pid, meta))
        return observations


# ---------------------------------------------------------------------------
# Report computation & serialization
# ---------------------------------------------------------------------------

def summarize_metrics(observed: List[CaseObservation]) -> Dict[str, Any]:
    """
    Pure, DB-free aggregation of persisted per-case observations into the
    authoritative metric block. All inputs come from rows the ARIV pipeline
    itself wrote; this function never reads from or writes to the database.

    Metric definitions:
      cases_observed          = cases persisted and correlated by benchmark_id
      total_amount_at_risk    = sum over observed cases of amount_minor
      decision_engine_cases   = observed cases with >= 1 DecisionRecord
      policy_evaluated        = decision_engine_cases (every decided case had
                                a PolicyEngine evaluation)
      policy_approved         = cases whose decision(s) include an APPROVED policy
      needs_review            = cases whose decision(s) include NEEDS_REVIEW
      policy_blocked          = cases whose decision(s) include a REJECTED final
                                (final decision rejected and not re-approved)
      human_approval          = cases whose decision(s) require HUMAN_APPROVAL
      execution_attempts      = total ExecutionAttempt rows (one per provider dispatch)
      execution_failures      = ExecutionAttempt rows with status FAILED
      provider_actions_succeeded = ExecutionAttempt rows with status SUCCEEDED
                                (real provider mutation completed)
      verified_recoveries     = cases with final status RECOVERED
      attributed_recoveries   = cases with an outcome whose recovery_source is
                                ACTION_ATTRIBUTED
      revenue_recovered       = recovered_amount over outcomes with status
                                RECOVERED or PARTIALLY_RECOVERED
    """
    total_amount_at_risk = sum(o.amount_minor for o in observed)
    decision_engine_cases = sum(1 for o in observed if o.decision_actions)
    policy_evaluated = decision_engine_cases
    policy_approved = sum(
        1 for o in observed
        if any(s == PolicyStatus.APPROVED.value for s in o.decision_policy_statuses)
    )
    needs_review = sum(
        1 for o in observed
        if any(s == PolicyStatus.NEEDS_REVIEW.value for s in o.decision_policy_statuses)
    )
    policy_blocked = sum(
        1 for o in observed
        if any(s == PolicyStatus.REJECTED.value for s in o.decision_policy_statuses)
    )
    human_approval = sum(
        1 for o in observed
        if any(s == AutonomyLevel.HUMAN_APPROVAL.value for s in o.decision_autonomy_levels)
    )

    attempt_statuses = [s for o in observed for s in o.attempt_statuses if s]
    execution_attempts = len(attempt_statuses)
    execution_failures = sum(o.execution_failures for o in observed)
    provider_actions_succeeded = attempt_statuses.count(ExecutionStatus.SUCCEEDED.value)

    verified_recoveries = sum(1 for o in observed if o.case_status == CaseStatus.RECOVERED.value)
    attributed_recoveries = sum(
        1 for o in observed if o.recovery_source == RecoverySource.ACTION_ATTRIBUTED.value
    )
    revenue_recovered = sum(
        o.recovered_amount_minor
        for o in observed
        if o.outcome_status in (
            RecoveryOutcomeStatus.RECOVERED.value,
            RecoveryOutcomeStatus.PARTIALLY_RECOVERED.value,
        )
    )
    human_escalations = sum(1 for o in observed if o.human_escalation)

    decisions_by_action: Dict[str, int] = {}
    for o in observed:
        seen = set()
        for action in o.decision_actions:
            if action not in seen:
                seen.add(action)
                decisions_by_action[action] = decisions_by_action.get(action, 0) + 1

    return {
        "cases_observed": len(observed),
        "total_amount_at_risk_minor": total_amount_at_risk,
        "total_amount_at_risk_inr": round(total_amount_at_risk / 100.0, 2),
        "decision_engine_cases": decision_engine_cases,
        "policy_evaluated": policy_evaluated,
        "policy_approved": policy_approved,
        "needs_review": needs_review,
        "policy_blocked": policy_blocked,
        "human_approval": human_approval,
        "execution_attempts": execution_attempts,
        "execution_failures": execution_failures,
        "provider_actions_succeeded": provider_actions_succeeded,
        "verified_recoveries": verified_recoveries,
        "attributed_recoveries": attributed_recoveries,
        "revenue_recovered_minor": revenue_recovered,
        "revenue_recovered_inr": round(revenue_recovered / 100.0, 2),
        "human_escalations": human_escalations,
        "decisions_by_action": decisions_by_action,
    }


def _safe_rate(numerator: float, denominator: float) -> Any:
    """Returns a percentage rounded to 1 decimal as a number, or the literal
    string 'NOT_APPLICABLE' when the denominator is zero. Never returns NaN,
    Infinity, or a misleading 0% for a zero denominator."""
    if denominator is None or float(denominator) == 0.0:
        return "NOT_APPLICABLE"
    return round((float(numerator) / float(denominator)) * 100.0, 1)


def derive_metrics(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pure derived-rate computation from summarize_metrics() output.

    Zero-denominator rates are reported as the string 'NOT_APPLICABLE' rather
    than NaN/Infinity/0% so they can never be misread as a measured value.
    Recovery rate uses cases_observed as the denominator (provider-confirmed
    recoveries / cohort); attribution rate uses verified_recoveries and is
    therefore NOT_APPLICABLE when there are no verified recoveries.
    """
    cases = raw.get("cases_observed", 0)
    decisioned = raw.get("decision_engine_cases", 0)
    evaluated = raw.get("policy_evaluated", 0)
    attempts = raw.get("execution_attempts", 0)
    verified = raw.get("verified_recoveries", 0)

    return {
        "decision_coverage": _safe_rate(decisioned, cases),
        "policy_approval_rate": _safe_rate(raw.get("policy_approved", 0), evaluated),
        "human_review_rate": _safe_rate(raw.get("needs_review", 0), cases),
        "execution_attempt_rate": _safe_rate(attempts, cases),
        "provider_action_success_rate": _safe_rate(
            raw.get("provider_actions_succeeded", 0), attempts
        ),
        "execution_failure_rate": _safe_rate(raw.get("execution_failures", 0), attempts),
        "recovery_rate": _safe_rate(verified, cases),
        "attribution_rate": _safe_rate(raw.get("attributed_recoveries", 0), verified),
    }


def compute_report(
    *,
    benchmark_id: str,
    start_time: str,
    end_time: str,
    cases_requested: int,
    observations: List[CaseObservation],
    sent_delivery: List[SentEvent],
) -> Dict[str, Any]:
    observed = [o for o in observations if o.case_status != "NOT_OBSERVED"]
    metrics = summarize_metrics(observed)
    derived = derive_metrics(metrics)

    base = {
        "benchmark_id": benchmark_id,
        "mode": "TEST_MODE",
        "start_time": start_time,
        "end_time": end_time,
        "cases_requested": cases_requested,
        "total_cases": len(observed),
    }
    base.update(metrics)
    base["recovery_rate"] = derived["recovery_rate"]
    base["derived_metrics"] = derived
    base["delivery"] = [
        {
            "index": s.index,
            "event_id": s.event_id,
            "payment_id": s.payment_id,
            "amount_minor": s.amount_minor,
            "http_status": s.http_status,
            "accepted": s.accepted,
        }
        for s in sent_delivery
    ]
    base["cases"] = [
        {
            "case_id": o.case_id,
            "payment_id": o.payment_id,
            "amount_minor": o.amount_minor,
            "scenario": o.scenario,
            "error_code": o.error_code,
            "error_reason": o.error_reason,
            "route_status_at_decision": o.route_status,
            "final_status": o.case_status,
            "recovery_stage": o.recovery_stage,
            "proposed_actions": o.decision_actions,
            "policy_statuses": o.decision_policy_statuses,
            "autonomy_levels": o.decision_autonomy_levels,
            "action_statuses": o.action_statuses,
            "attempt_statuses": o.attempt_statuses,
            "outcome_status": o.outcome_status,
            "recovered_amount_minor": o.recovered_amount_minor,
            "recovery_source": o.recovery_source,
            "human_escalation": o.human_escalation,
        }
        for o in observations
    ]
    return base


def write_report(report: Dict[str, Any], output_dir: Path = Path(".")) -> Path:
    filename = output_dir / f"benchmark_report_{report['benchmark_id']}.json"
    filename.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return filename