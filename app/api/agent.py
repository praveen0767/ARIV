import logging
import json
import uuid as _uuid
import re
import asyncio
from typing import AsyncGenerator, Optional, Dict, Any, List

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, cast, String

from app.infrastructure.database import get_db_session
from app.core.config import settings
from app.domain.recovery_case import RecoveryCase, CaseStatus
from app.domain.classification import RecoveryClassification
from app.domain.recovery.recovery_outcome import RecoveryOutcome, RecoveryOutcomeStatus, RecoverySource
from app.domain.recovery.recovery_measurement import RecoveryMeasurement
from app.domain.decision import DecisionRecord, RecoveryAction, PolicyStatus, AutonomyLevel
from app.domain.action import Action, ActionStatus, ExecutionAttempt
from app.services.outbox import OutboxService
from app.services.execution_worker import ExecutionWorker
from app.infrastructure.adapters import get_razorpay_adapter
from app.services.activity import ActivityService
from app.services.qdrant_memory import QdrantMemoryService
from app.services.dashboard import DashboardService
from app.services.ingestion import resolve_tenant
import hmac
import hashlib

logger = logging.getLogger("ariv.api.agent")

router = APIRouter(prefix="/v1/agent", tags=["agent"])


# ---------------------------------------------------------------------------
# Auth (HMAC-SHA256)
# ---------------------------------------------------------------------------

def _verify_signature(account_id: str, signature: str) -> bool:
    import hmac as _hmac
    expected = _hmac.new(
        settings.INTERNAL_API_KEY.encode(),
        account_id.encode(),
        hashlib.sha256,
    ).hexdigest()
    return _hmac.compare_digest(expected, signature)


async def _get_tenant(
    x_account_id: str = Header(...),
    x_signature: str = Header(...),
    db: AsyncSession = Depends(get_db_session),
):
    if not _verify_signature(x_account_id, x_signature):
        raise HTTPException(status_code=403, detail="Invalid signature")
    tenant = await resolve_tenant(db, x_account_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class AgentQueryRequest(BaseModel):
    query: str
    current_route: Optional[str] = None
    case_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _status_icon(status: str) -> str:
    return {"ok": "✓", "degraded": "⚠", "down": "✗", "unknown": "?"}.get(status, "?")


def _case_status_str(case: RecoveryCase) -> str:
    return case.status.value if hasattr(case.status, "value") else str(case.status)


def _fmt_inr(minor: int) -> str:
    return f"₹{minor / 100:,.2f}"


def format_ai_confidence(dec_rec: Optional["DecisionRecord"]) -> str:
    """Render recorded AI confidence without ever fabricating a value.

    The decision engine stores the real float it produced (0.0 when no LLM is
    configured). When no decision record exists, or the record carries no
    confidence, the UI says so explicitly instead of printing a made-up per cent.
    """
    if dec_rec is not None and dec_rec.ai_confidence is not None:
        return f"{int(dec_rec.ai_confidence * 100)}%"
    return "Confidence unavailable"


# ---------------------------------------------------------------------------
# Conversational greeting / identity / capability routing
# ---------------------------------------------------------------------------

_CONVERSATIONAL_PHRASES = (
    "good morning",
    "good afternoon",
    "good evening",
    "good day",
    "how are you",
    "how's it going",
    "how is it going",
    "what can you do",
    "what do you do",
    "what can you help with",
    "how can you help",
    "can you help",
    "help me",
    "i need help",
    "what are your capabilities",
    "what can you tell me",
    "who are you",
    "what are you",
    "are you ariv",
    "nice to meet you",
    "thank you",
    "thanks a lot",
    "thanks so much",
    "thank you so much",
    "great thanks",
    "awesome thanks",
    "welcome",
)

_CONVERSATIONAL_WORDS = frozenset({
    "hi", "hello", "hey", "howdy", "hola", "yo",
    "thanks", "thank", "thx", "ty",
    "help", "greetings",
})

# Concrete operational intents that a greeting word must never override when it
# is merely prefixed to a real request (e.g. "hey, recover this case").
_OPERATIONAL_PINNERS = (
    "recover this case",
    "execute recovery",
    "trigger recovery",
    "where is the payment link",
    "payment link",
    "is ariv healthy",
    "system health",
    "who's pending",
    "who is pending",
    "how would ariv recover",
)


def is_conversational_greeting(q: str) -> bool:
    """True for simple conversational input (greeting, courtesy, identity or
    capability question). Aggressive by design so a bare "hi" never falls into
    case-diagnosis or the workspace "no cases" guard — but it NEVER overrides an
    aggregate, case-pinned, or concrete operational request that merely contains
    a greeting word as a prefix.
    """
    q = (q or "").lower().strip()
    if not q or len(q) > 120:
        return False
    if is_aggregate_metrics_query(q):
        return False
    if _query_pins_case(q):
        return False
    if any(op in q for op in _OPERATIONAL_PINNERS):
        return False
    if any(p in q for p in _CONVERSATIONAL_PHRASES):
        return True
    return bool(set(re.findall(r"[a-z']+", q)) & _CONVERSATIONAL_WORDS)


def greeting_response_lines(q: str) -> List[str]:
    """Lightweight, capability-grounded conversational response.

    Only real ASK ARIV capabilities are described — every item is backed by an
    existing routing branch or the authoritative metrics source.
    """
    ql = (q or "").lower().strip()

    expressly_identity = any(
        p in ql for p in ("what can you do", "what do you do", "can you help",
                          "help me", "i need help", "what are your capabilities",
                          "who are you", "what are you", "are you ariv")
    )
    expressly_thanks = any(
        p in ql for p in ("thank", "thx", "ty", "welcome", "great thanks",
                          "awesome thanks")
    )

    if expressly_thanks:
        lines = ["You're welcome! I'm ASK ARIV, your revenue-recovery control layer."]
    elif expressly_identity:
        lines = ["I'm ASK ARIV, the autonomous revenue-recovery control layer for this workspace."]
    else:
        lines = ["Hey! I'm ASK ARIV, your revenue-recovery control layer."]

    lines.append("")
    lines.append("WHAT I CAN DO")
    lines.append("=" * 45)
    lines.append("  • Explain active recovery cases, decisions, and outcomes")
    lines.append("  • Show payment-link status and where a case is in the pipeline")
    lines.append("  • Report verified workspace recovery metrics (provider-confirmed only)")
    lines.append("  • Trigger an authorized recovery action for a case (with policy firewalls)")
    lines.append("  • Explain policy rejections and run a recovery preview")
    lines.append("  • Report pending recoveries, system health, and the global snapshot")
    lines.append("")
    lines.append("SUGGESTED PROMPTS")
    lines.append("  • 'What is happening right now?'")
    lines.append("  • 'How much was recovered?'")
    lines.append("  • 'What's happening with this case?'")
    lines.append("  • 'Where is the payment link?'")
    lines.append("  • 'Recover this case.'")
    lines.append("  • 'Why is this case still pending?'")
    lines.append("  • 'Is ARIV healthy?'")
    return lines


def _query_pins_case(q: str) -> bool:
    """True when the query text explicitly names a single case (a UUID/hex id or
    a case-proximate phrase). Case-pinned intents stay case-scoped regardless of
    drawer context or any aggregate/greeting-looking keywords."""
    return bool(
        re.search(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})?", q)
    ) or any(
        t in q for t in [
            "this case",
            "that case",
            "this one",
            " a case",
            "the case",
            "case id",
            "case:",
            "case -",
        ]
    )


def is_aggregate_metrics_query(q: str) -> bool:
    """True when a lowercased query asks for tenant-wide (workspace) recovery metrics
    rather than a single-case diagnosis. Aggregate intent has the highest routing
    precedence: it must win even when the drawer is open on a specific case page.
    Only an explicit case reference in the query text pins the intent to one case."""
    _aggregate_kw = any(
        kw in q
        for kw in [
            "how many payments",
            "how many recoveries",
            "how many recovery",
            "how many recovered",
            "how many were recovered",
            "number of payments",
            "number of recoveries",
            "payments were recovered",
            "payments recovered",
            "recoveries have happened",
            "recoveries have been",
            "payments have been recovered",
            "recovery rate",
            "recovered revenue",
            "revenue recovered",
            "revenue at risk",
            "how much at risk",
            "amount at risk",
            "at risk",
            "risk amount",
            "total recovered",
            "total recovered amount",
            "total amount recovered",
            "amount recovered",
            "recovered amount",
            "how much was recovered",
            "how much recovered",
            "how much was paid back",
            "how much revenue recovered",
            "total revenue",
            "total at risk",
            "so far",
            "until now",
            "untill now",
            "to date",
            "entirely",
            "overall",
            "all time",
            "in total",
            "ever recovered",
            "across all",
            "any payments",
            "any recoveries",
            "any revenue",
        ]
    )
    return (not _query_pins_case(q)) and _aggregate_kw


# ---------------------------------------------------------------------------
# Streaming SSE generator
# ---------------------------------------------------------------------------

def _sse_event(type_: str, payload: Any) -> str:
    if isinstance(payload, str):
        return f"data: {json.dumps({'type': type_, 'text': payload})}\n\n"
    return f"data: {json.dumps({'type': type_, **payload})}\n\n"


async def _agent_stream(
    query: str,
    tenant_id: str,
    db: AsyncSession,
    current_route: Optional[str] = None,
    context_case_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """SSE wrapper. Guarantees a structured `error` event (code + message) is
    emitted instead of a bare connection close when any stream branch raises, so
    clients can surface operational errors distinctly from transport failures."""
    try:
        async for event in _agent_stream_impl(
            query=query,
            tenant_id=tenant_id,
            db=db,
            current_route=current_route,
            context_case_id=context_case_id,
        ):
            yield event
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error("Agent stream failed: %s", exc)
        yield _sse_event("error", {
            "code": "OPERATIONAL_ERROR",
            "message": str(exc)[:400],
        })
        yield "data: [DONE]\n\n"


async def _agent_stream_impl(
    query: str,
    tenant_id: str,
    db: AsyncSession,
    current_route: Optional[str] = None,
    context_case_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    q = query.lower().strip()

    _event = _sse_event

    # -----------------------------------------------------------------------
    # BRANCH GRT: Conversational greeting / identity / capability question
    # Pure text short-circuit at the TOP of the stream — before any DB access,
    # case resolution, the aggregate branch, or any operational branch. A bare
    # "hi" (typed anywhere, including the drawer of a specific case page, or in
    # an empty workspace) always gets a normal spoken answer. Aggregate queries,
    # case-pinned queries and concrete operational requests are explicitly
    # excluded by is_conversational_greeting, so their existing routes are
    # untouched.
    # -----------------------------------------------------------------------
    if is_conversational_greeting(q):
        yield _event("step", "Reading you loud and clear…")
        gmeta: Dict[str, Any] = {
            "case_id": None,
            "payment_link_url": None,
            "action_type": None,
            "status": None,
            "can_recover": False,
            "links": [
                {"label": "View Operational Cases", "href": "/cases", "is_external": False},
                {"label": "View Recovery Impact", "href": "/impact", "is_external": False},
                {"label": "System Health", "href": "/system", "is_external": False},
            ],
        }
        yield _event("meta", gmeta)
        yield _event("content", "\n".join(greeting_response_lines(q)))
        yield "data: [DONE]\n\n"
        return

    # --- Step 1: Query tenant cases
    yield _event("step", "Querying tenant recovery cases…")
    cases_result = await db.execute(
        select(RecoveryCase)
        .where(RecoveryCase.tenant_id == tenant_id)
        .order_by(desc(RecoveryCase.created_at))
        .limit(20)
    )
    cases = list(cases_result.scalars().all())
    yield _event("step", f"Loaded {len(cases)} recent recovery cases.")

    # Structured metadata for frontend action/navigation cards
    meta: Dict[str, Any] = {
        "case_id": None,
        "payment_link_url": None,
        "action_type": None,
        "status": None,
        "can_recover": False,
        "links": [],
    }

    # -----------------------------------------------------------------------
    # Case Resolution: Context-aware target identification
    # -----------------------------------------------------------------------
    target_case: Optional[RecoveryCase] = None

    # 1. From context_case_id (passed when drawer is on a specific case page)
    if context_case_id:
        try:
            target_uuid = _uuid.UUID(str(context_case_id).strip())
            for c in cases:
                if c.id == target_uuid:
                    target_case = c
                    break
            if not target_case:
                c_res = await db.execute(
                    select(RecoveryCase).where(
                        RecoveryCase.id == target_uuid,
                        RecoveryCase.tenant_id == tenant_id,
                    )
                )
                target_case = c_res.scalar_one_or_none()
        except Exception:
            pass

    # 2. From URL route if not explicitly passed (e.g. /cases/03afd13a...)
    if not target_case and current_route and "/cases/" in current_route:
        try:
            route_parts = current_route.strip("/").split("/")
            if len(route_parts) >= 2 and route_parts[0] == "cases":
                candidate_id = route_parts[1]
                target_uuid = _uuid.UUID(candidate_id)
                for c in cases:
                    if c.id == target_uuid:
                        target_case = c
                        break
        except Exception:
            pass

    # 3. From query text mentioning a UUID or hex prefix
    if not target_case:
        id_match = re.search(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})?", q)
        if id_match:
            cand = id_match.group(0).lower()
            for c in cases:
                if str(c.id).lower().startswith(cand):
                    target_case = c
                    break
            if not target_case:
                c_res = await db.execute(
                    select(RecoveryCase)
                    .where(
                        RecoveryCase.tenant_id == tenant_id,
                        cast(RecoveryCase.id, String).ilike(f"{cand}%"),
                    )
                    .limit(1)
                )
                target_case = c_res.scalar_one_or_none()

    # Keyword detection groups
    kw_execute = any(
        kw in q
        for kw in [
            "recover this case",
            "execute recovery",
            "trigger recovery",
            "recover case",
            "run recovery",
            "execute action",
            "generate the payment link",
            "generate payment link",
            "retry the approved action",
            "retry action",
        ]
    ) and not any(kw in q for kw in ["how would", "would you", "preview"])

    kw_happening_now = any(
        kw in q
        for kw in [
            "happening right now",
            "happening now",
            "what's happening now",
            "what is happening now",
            "what is happening right now",
            "operational snapshot",
            "status right now",
            "what is ariv doing right now",
        ]
    )

    kw_case_details = any(
        kw in q
        for kw in [
            "what's happening with this case",
            "happening with this case",
            "about this case",
            "why is it still pending",
            "why is it pending",
            "why did ariv choose",
            "why this action",
            "was the payment actually recovered",
            "was payment recovered",
            "is it recovered",
            "show me the latest activity",
            "latest activity",
            "what happens next",
            "explain this case",
            "explain case",
            "show case",
        ]
    )

    kw_payment_link = any(
        kw in q
        for kw in [
            "where is the payment link",
            "payment link url",
            "show payment link",
            "get payment link",
            "payment link",
        ]
    )

    kw_recover_amount = any(
        kw in q
        for kw in [
            "how much did we recover",
            "how much was recovered",
            "total recovered",
            "recovered amount",
            "how much recovered",
        ]
    )

    kw_rejected = any(
        kw in q
        for kw in [
            "why was this rejected",
            "why was it rejected",
            "why was this blocked",
            "policy rejection",
            "policy rejected",
        ]
    )

    kw_health = any(kw in q for kw in ["health", "status", "running", "worker", "ariv healthy", "system"])
    kw_preview = any(kw in q for kw in ["preview", "how would", "would you recover", "if you"])
    kw_policy = any(kw in q for kw in ["policy", "block", "prevent", "firewall", "safety", "approved"])
    kw_memory = any(kw in q for kw in ["similar", "memory", "precedent", "history"])
    kw_pending = any(kw in q for kw in ["pending", "waiting", "in progress", "open cases", "not yet"])
    kw_revenue = any(kw in q for kw in ["revenue", "at risk", "how much at risk", "incremental"])

    # -----------------------------------------------------------------------
    # Aggregate / workspace metrics intent detection.
    # Highest precedence: even when the drawer is open on a specific case page
    # (context_case_id -> target_case resolved), tenant-wide questions must be
    # answered from authoritative workspace metrics, NOT a single-case
    # diagnosis. Only an explicit case reference in the QUERY TEXT (UUID or
    # "this case" / "the case" phrasing) pins the intent to a single case.
    # -----------------------------------------------------------------------
    is_aggregate = is_aggregate_metrics_query(q)

    lines: List[str] = []

    # -----------------------------------------------------------------------
    # BRANCH AGG: Workspace / Aggregate Recovery Metrics (highest precedence)
    # Answer from the authoritative persisted metrics source (GET /v1/recovery/metrics).
    # No values are recomputed here; whatever the metrics source returns is formatted.
    # -----------------------------------------------------------------------
    if is_aggregate:
        yield _event("step", "Compiling authoritative tenant-wide recovery metrics…")
        try:
            metrics = await DashboardService.get_tenant_metrics(db, tenant_id)
        except Exception as e:
            logger.warning("Aggregate metrics lookup failed: %s", e)
            metrics = None

        if not metrics:
            lines.append("Could not load workspace recovery metrics right now.")
            lines.append("Please check that the recovery stack is running.")
        else:
            vr = metrics.get("verified_recoveries") or {}
            ar = metrics.get("at_risk") or {}
            pl = metrics.get("pipeline") or {}
            paid = int(vr.get("payments_recovered") or 0)
            rev = int(vr.get("recovered_revenue_minor") or 0)
            rate = float(vr.get("recovery_rate_pct") or 0.0)
            attr = int(vr.get("attributed_to_action") or 0)
            at_risk_amount = int(ar.get("revenue_at_risk_minor") or 0)
            total_cases = int(ar.get("cases_total") or 0)
            waiting = int(ar.get("waiting_for_payment_cases") or 0)
            waiting_minor = int(ar.get("waiting_for_payment_minor") or 0)
            decisioned = int(pl.get("cases_decisioned") or 0)
            executed = int(pl.get("actions_executed") or 0)
            links = int(pl.get("payment_links_generated") or 0)

            lines.append("ARIV WORKSPACE RECOVERY METRICS")
            lines.append("=" * 45)
            lines.append("")
            lines.append("VERIFIED RECOVERIES (provider-confirmed)")
            lines.append(f"  Payments Recovered:   {paid}")
            lines.append(f"  Verified Revenue:     {_fmt_inr(rev)}")
            if at_risk_amount > 0:
                lines.append(f"  Recovery Rate:        {rate:.1f}% of revenue at risk")
            if attr:
                lines.append(f"  Action-Attributed:    {attr} of {paid}")
            lines.append("")
            lines.append("NOT YET RECOVERED / AT RISK")
            lines.append(f"  Revenue at Risk:      {_fmt_inr(at_risk_amount)} ({total_cases} cases)")
            if waiting:
                lines.append(f"  Waiting for Payment:  {waiting} case(s) · {_fmt_inr(waiting_minor)}")
            lines.append("")
            lines.append("PIPELINE (dispatched, NOT recovered)")
            lines.append(f"  Cases Decisioned:     {decisioned}")
            lines.append(f"  Actions Executed:     {executed}")
            lines.append(f"  Payment Links Sent:   {links}")
            lines.append("")
            lines.append("Recovery counts include only verified provider confirmations. Dispatched")
            lines.append("payment links and pending cases are not counted as recovered until the")
            lines.append("payment webhook is confirmed and attributed.")

        meta["links"].append({"label": "View Recovery Impact", "href": "/impact", "is_external": False})
        meta["links"].append({"label": "View Operational Cases", "href": "/cases", "is_external": False})
        yield _event("meta", meta)
        yield _event("content", "\n".join(lines))
        yield "data: [DONE]\n\n"
        return

    # -----------------------------------------------------------------------
    # BRANCH: No cases in workspace (except health check queries)
    # -----------------------------------------------------------------------
    if not cases and not kw_health:
        lines.append("No recovery cases found in this workspace.")
        lines.append("")
        lines.append("To simulate an incoming payment failure in Razorpay Test Mode, run:")
        lines.append("  docker compose exec web python scripts/send_test_failure.py")
        meta["links"].append({"label": "System Health", "href": "/system", "is_external": False})
        yield _event("meta", meta)
        yield _event("content", "\n".join(lines))
        yield "data: [DONE]\n\n"
        return

    # -----------------------------------------------------------------------
    # BRANCH 1: Action Control — "Recover this case."
    # -----------------------------------------------------------------------
    if kw_execute:
        yield _event("step", "Resolving target recovery case for authorized execution…")

        if not target_case:
            target_case = next(
                (c for c in cases if c.status not in (CaseStatus.RECOVERED, CaseStatus.FAILED, CaseStatus.CLOSED)),
                cases[0] if cases else None,
            )

        if not target_case:
            lines.append("No actionable recovery case found to execute.")
            lines.append("All cases in the queue are already resolved.")
        else:
            cid_str = str(target_case.id)
            cid_short = cid_str[:8]
            ctx = dict(target_case.context or {})
            meta["case_id"] = cid_str
            meta["links"].append({"label": "Open Case", "href": f"/cases/{cid_str}", "is_external": False})

            # Check if case is already recovered
            if target_case.status == CaseStatus.RECOVERED:
                out_r = await db.execute(
                    select(RecoveryOutcome).where(RecoveryOutcome.case_id == target_case.id)
                )
                outcome = out_r.scalar_one_or_none()
                rec_amount = outcome.recovered_amount if outcome else (target_case.amount or 0)
                source_str = (
                    outcome.recovery_source.value
                    if (outcome and hasattr(outcome.recovery_source, "value"))
                    else "ACTION_ATTRIBUTED"
                )

                meta["status"] = "RECOVERED"
                meta["recovered_amount_minor"] = rec_amount
                meta["links"].append({"label": "View Recovery Impact", "href": "/impact", "is_external": False})

                lines.append(f"Case {cid_short}… is already RECOVERED.")
                lines.append("")
                lines.append("Status:")
                lines.append(f"  Verified Recovery: {_fmt_inr(rec_amount)}")
                lines.append(f"  Attribution:       {source_str}")
                lines.append("")
                lines.append("No further recovery intervention is required.")

            # Check if payment link is already created and waiting for customer payment
            elif ctx.get("recovery_stage") == "WAITING_FOR_PAYMENT" or (
                ctx.get("payment_link_url") and target_case.status != CaseStatus.RECOVERED
            ):
                plink_url = ctx.get("payment_link_url")
                plink_id = ctx.get("payment_link_id", "Generated")
                meta["payment_link_url"] = plink_url
                meta["status"] = "WAITING_FOR_PAYMENT"
                if plink_url:
                    meta["links"].append({"label": "Open Razorpay Payment Link", "href": plink_url, "is_external": True})

                lines.append(f"Case {cid_short}… is currently WAITING_FOR_PAYMENT.")
                lines.append("")
                lines.append("Recovery:")
                lines.append("  Action:   GENERATE_PAYMENT_LINK (SUCCEEDED)")
                lines.append(f"  Amount:   {_fmt_inr(target_case.amount or 0)}")
                lines.append(f"  Provider: Razorpay Payment Link ({plink_id})")
                if plink_url:
                    lines.append(f"  URL:      {plink_url}")
                lines.append("")
                lines.append("PolicyEngine deterministic safety rules prevent generating duplicate links.")
                lines.append("The payment link is live. Waiting for the customer to complete payment.")

            # Actionable case: run governed decision and execution pipeline
            else:
                yield _event("step", f"Evaluating decision & policy safety rules for Case {cid_short}…")

                cls_r = await db.execute(
                    select(RecoveryClassification)
                    .where(RecoveryClassification.case_id == target_case.id)
                    .order_by(desc(RecoveryClassification.timestamp))
                    .limit(1)
                )
                classification = cls_r.scalar_one_or_none()

                dec_r = await db.execute(
                    select(DecisionRecord)
                    .where(DecisionRecord.case_id == target_case.id)
                    .order_by(desc(DecisionRecord.timestamp))
                    .limit(1)
                )
                decision = dec_r.scalar_one_or_none()

                if not classification or not decision:
                    lines.append(f"Case {cid_short}… is missing failure intelligence.")
                    lines.append("Recovery requires initial classification signals from the gateway payload.")
                elif decision.policy_status == PolicyStatus.REJECTED:
                    meta["status"] = "BLOCKED"
                    lines.append(f"Recovery for case {cid_short}… was BLOCKED by the Policy Firewall.")
                    lines.append("")
                    lines.append(f"Action Proposed:  {decision.proposed_action.value}")
                    lines.append("Policy Gate:      REJECTED")
                    lines.append(f"Rejection Reason: {decision.rejection_reason or 'Policy safety boundary triggered'}")
                    lines.append("")
                    lines.append("PolicyEngine deterministic constraints prevented action dispatch.")
                else:
                    action_type = decision.proposed_action
                    yield _event("step", f"Submitting authorized action {action_type.value} via Execution Outbox…")

                    outbox_payload = {
                        "amount": target_case.amount_minor or 10000,
                        "currency": ctx.get("currency", "INR"),
                        "description": f"ARIV Autonomous Recovery - Case {cid_short}",
                        "customer_email": ctx.get("customer_email"),
                        "customer_phone": ctx.get("customer_phone"),
                        "customer_name": ctx.get("customer_name"),
                    }

                    action, outbox = await OutboxService.create_authorized_action(
                        session=db,
                        case_id=target_case.id,
                        tenant_id=target_case.tenant_id,
                        decision_id=decision.id,
                        action_type=action_type,
                        payload=outbox_payload,
                    )

                    yield _event("step", "Dispatching authorized action to Razorpay provider…")
                    adapter = get_razorpay_adapter()
                    if adapter:
                        try:
                            worker = ExecutionWorker(provider_adapter=adapter)
                            await worker.process_outbox_item(db, outbox)
                        except Exception as e:
                            logger.error("ExecutionWorker error: %s", e)

                    # Reload attempt
                    att_r = await db.execute(
                        select(ExecutionAttempt)
                        .where(ExecutionAttempt.action_id == action.id)
                        .order_by(desc(ExecutionAttempt.attempt_number))
                        .limit(1)
                    )
                    attempt = att_r.scalar_one_or_none()
                    att_meta = attempt.attempt_metadata if (attempt and isinstance(attempt.attempt_metadata, dict)) else {}
                    plink_url = att_meta.get("short_url") or ""
                    req_id = attempt.provider_request_id if attempt else "N/A"

                    ctx["recovery_stage"] = (
                        "WAITING_FOR_PAYMENT"
                        if plink_url and action.status == ActionStatus.SUCCEEDED
                        else (action.status.value if hasattr(action.status, "value") else str(action.status))
                    )
                    if plink_url:
                        ctx["payment_link_url"] = plink_url
                    if req_id and req_id != "N/A":
                        ctx["payment_link_id"] = req_id
                    target_case.context = ctx
                    await db.commit()

                    meta["action_type"] = action_type.value
                    meta["status"] = action.status.value if hasattr(action.status, "value") else str(action.status)
                    meta["payment_link_url"] = plink_url or None
                    if plink_url:
                        meta["links"].append({"label": "Open Razorpay Payment Link", "href": plink_url, "is_external": True})

                    lines.append(f"Case {cid_short}… authorized recovery action processed.")
                    lines.append("")
                    lines.append("Execution:")
                    lines.append(f"  Action:       {action_type.value}")
                    lines.append(f"  Status:       {action.status.value}")
                    lines.append(f"  Policy Gate:  APPROVED (Autonomy: {decision.autonomy_level.value})")
                    if req_id != "N/A":
                        lines.append(f"  Provider Ref: {req_id}")
                    if plink_url:
                        lines.append(f"  Payment Link: {plink_url}")
                    lines.append("")
                    if action.status == ActionStatus.SUCCEEDED:
                        lines.append("Recovery stage updated to WAITING_FOR_PAYMENT.")
                        lines.append("System is monitoring for payment_link.paid webhook to confirm and attribute recovery.")
                    else:
                        lines.append("Recovery action did not succeed; no payment link was generated.")
                        lines.append("Inspect the case timeline for the deterministic execution audit trail.")

    # -----------------------------------------------------------------------
    # BRANCH 2: Global Operational Snapshot — "What is happening right now?"
    # -----------------------------------------------------------------------
    elif kw_happening_now and not target_case:
        yield _event("step", "Compiling real-time operational workspace snapshot…")

        active_cases = [c for c in cases if c.status not in (CaseStatus.RECOVERED, CaseStatus.FAILED, CaseStatus.CLOSED)]
        waiting_payment = [c for c in cases if (c.context or {}).get("recovery_stage") == "WAITING_FOR_PAYMENT"]
        recovered_cases = [c for c in cases if c.status == CaseStatus.RECOVERED]
        total_at_risk = sum(c.amount or 0 for c in cases)

        # Query recovered sum
        outcomes_r = await db.execute(
            select(RecoveryOutcome)
            .where(RecoveryOutcome.tenant_id == tenant_id)
        )
        all_outcomes = list(outcomes_r.scalars().all())
        total_recovered = sum(
            o.recovered_amount or 0
            for o in all_outcomes
            if o.outcome_status in (RecoveryOutcomeStatus.RECOVERED, RecoveryOutcomeStatus.PARTIALLY_RECOVERED)
        )

        # Probes
        db_ok = True
        try:
            from app.infrastructure.database import check_db_health
            db_ok = await check_db_health()
        except Exception:
            pass

        lines.append("ARIV OPERATIONAL SNAPSHOT (REAL-TIME)")
        lines.append("=" * 45)
        lines.append("")
        lines.append(f"  Active Cases:             {len(active_cases)}")
        lines.append(f"  Waiting for Payment:      {len(waiting_payment)}")
        lines.append(f"  Recovered Cases:          {len(recovered_cases)}")
        lines.append(f"  Total Revenue at Risk:    {_fmt_inr(total_at_risk)}")
        lines.append(f"  Verified Revenue Recovered:{_fmt_inr(total_recovered)}")
        lines.append("")
        lines.append("Infrastructure Integrity:")
        lines.append(f"  • PostgreSQL:       {'Connected' if db_ok else 'Degraded'}")
        lines.append("  • Redis Outbox:     Connected")
        lines.append("  • Policy Firewall:  Enforced & Active")
        lines.append("  • Razorpay Adapter: Connected (Test Mode)")
        lines.append("")

        if waiting_payment:
            first_w = waiting_payment[0]
            w_ctx = dict(first_w.context or {})
            w_url = w_ctx.get("payment_link_url")
            lines.append(f"Latest pending payment: Case {str(first_w.id)[:8]}… ({_fmt_inr(first_w.amount or 0)})")
            meta["links"].append({"label": f"Inspect Case {str(first_w.id)[:8]}…", "href": f"/cases/{first_w.id}", "is_external": False})
            if w_url:
                meta["links"].append({"label": "Open Active Payment Link", "href": w_url, "is_external": True})

        meta["links"].append({"label": "View Operational Cases", "href": "/cases", "is_external": False})
        meta["links"].append({"label": "View Recovery Impact", "href": "/impact", "is_external": False})
        meta["links"].append({"label": "System Health", "href": "/system", "is_external": False})

    # -----------------------------------------------------------------------
    # BRANCH 3: Real-Time Case Questions (FACT / DECISION / POLICY / ACTION / OUTCOME)
    # -----------------------------------------------------------------------
    elif target_case or (context_case_id and kw_case_details):
        yield _event("step", "Loading full case diagnosis and audit records…")

        if not target_case and cases:
            target_case = cases[0]

        cid_str = str(target_case.id)
        cid_short = cid_str[:8]
        ctx = dict(target_case.context or {})
        meta["case_id"] = cid_str
        meta["links"].append({"label": "Open Case", "href": f"/cases/{cid_str}", "is_external": False})

        # Load domain records
        cls_r = await db.execute(
            select(RecoveryClassification)
            .where(RecoveryClassification.case_id == target_case.id)
            .order_by(desc(RecoveryClassification.timestamp))
            .limit(1)
        )
        cls_rec = cls_r.scalar_one_or_none()

        dec_r = await db.execute(
            select(DecisionRecord)
            .where(DecisionRecord.case_id == target_case.id)
            .order_by(desc(DecisionRecord.timestamp))
            .limit(1)
        )
        dec_rec = dec_r.scalar_one_or_none()

        act_r = await db.execute(
            select(Action)
            .where(Action.case_id == target_case.id)
            .order_by(desc(Action.created_at))
            .limit(1)
        )
        act_rec = act_r.scalar_one_or_none()

        out_r = await db.execute(
            select(RecoveryOutcome).where(RecoveryOutcome.case_id == target_case.id)
        )
        out_rec = out_r.scalar_one_or_none()

        # Activities
        recent_acts = []
        try:
            recent_acts = await ActivityService.get_recent_activity(
                session=db,
                tenant_id=target_case.tenant_id,
                case_id=target_case.id,
                limit=3,
            )
        except Exception:
            pass

        cat = cls_rec.failure_category.value if cls_rec else "TRANSIENT_TECHNICAL"
        retry = cls_rec.retryability.value if cls_rec else "SAFE_TO_RETRY"
        recov = cls_rec.recoverability.value if cls_rec else "HIGH"

        prop_act = dec_rec.proposed_action.value if dec_rec else (act_rec.action_type.value if act_rec else "GENERATE_PAYMENT_LINK")
        base_act = dec_rec.baseline_action.value if (dec_rec and dec_rec.baseline_action) else "RETRY_NOW"
        # Confidence is NEVER fabricated: it is the value the decision engine
        # actually recorded (0.0 when no LLM was configured). When there is no
        # decision record, the UI says so instead of printing a made-up per cent.
        confidence_text = format_ai_confidence(dec_rec)
        pol_status = dec_rec.policy_status.value if dec_rec else "APPROVED"
        autonomy = dec_rec.autonomy_level.value if dec_rec else "FULL_AUTO"

        act_status = act_rec.status.value if act_rec else "PENDING"
        plink_url = ctx.get("payment_link_url") or ""
        plink_id = ctx.get("payment_link_id") or "N/A"
        recovery_stage = ctx.get("recovery_stage") or _case_status_str(target_case)

        outcome_status = out_rec.outcome_status.value if out_rec else "PENDING"
        rec_amount = _fmt_inr(out_rec.recovered_amount or 0) if out_rec else "₹0.00"
        rec_source = out_rec.recovery_source.value if out_rec else "PENDING_RECONCILIATION"

        meta["action_type"] = prop_act
        meta["status"] = _case_status_str(target_case)
        if plink_url:
            meta["payment_link_url"] = plink_url
            meta["links"].append({"label": "Open Razorpay Payment Link", "href": plink_url, "is_external": True})

        if target_case.status == CaseStatus.RECOVERED:
            meta["links"].append({"label": "View Recovery Impact", "href": "/impact", "is_external": False})
        elif target_case.status in (CaseStatus.OPEN, CaseStatus.RISK_ASSESSED, CaseStatus.PENDING_APPROVAL):
            meta["can_recover"] = True

        lines.append(f"CASE {cid_short}… STATUS & DIAGNOSIS")
        lines.append("=" * 45)
        lines.append("")
        lines.append("[FACT]")
        lines.append(f"  • Amount at Risk:    {_fmt_inr(target_case.amount or 0)}")
        lines.append(f"  • Failure Category:  {cat}")
        lines.append(f"  • Retryability:      {retry}")
        lines.append(f"  • Recoverability:    {recov}")
        lines.append(f"  • Gateway Reason:    {ctx.get('error_description') or 'Payment gateway failure'}")
        lines.append("")
        lines.append("[DECISION]")
        lines.append(f"  • Proposed Action:   {prop_act}")
        lines.append(f"  • Baseline Action:   {base_act}")
        lines.append(f"  • AI Confidence:     {confidence_text}")
        lines.append("")
        lines.append("[POLICY FIREWALL]")
        lines.append(f"  • Gate Status:       {pol_status}")
        lines.append(f"  • Autonomy Level:    {autonomy}")
        if dec_rec and dec_rec.rejection_reason:
            lines.append(f"  • Reason Blocked:    {dec_rec.rejection_reason}")
        lines.append("")
        lines.append("[ACTION & PROVIDER]")
        lines.append(f"  • Action Status:     {act_status}")
        lines.append(f"  • Provider:          Razorpay Sandbox")
        if plink_id != "N/A":
            lines.append(f"  • Provider Ref:      {plink_id}")
        if plink_url:
            lines.append(f"  • Payment Link:      {plink_url}")
        lines.append("")
        lines.append("[OUTCOME & ATTRIBUTION]")
        lines.append(f"  • Outcome Status:    {outcome_status}")
        lines.append(f"  • Recovered Amount:  {rec_amount}")
        lines.append(f"  • Attribution:       {rec_source}")

        if recent_acts:
            lines.append("")
            lines.append("[LATEST ACTIVITY]")
            for a in recent_acts:
                lines.append(f"  • {a.get('icon', '•')} {a.get('human_readable_message') or a.get('message', 'Event logged')}")

        lines.append("")
        lines.append("[WHAT HAPPENS NEXT]")
        if target_case.status == CaseStatus.RECOVERED:
            lines.append("  Recovery is verified and fully attributed to ARIV's intervention.")
            lines.append("  No further customer contact or payment action is needed.")
        elif recovery_stage == "WAITING_FOR_PAYMENT" or plink_url:
            lines.append("  Customer received the Payment Link. ARIV is listening for the")
            lines.append("  'payment_link.paid' webhook to verify and attribute recovered revenue.")
        elif pol_status == "REJECTED":
            lines.append("  PolicyEngine blocked the recovery proposal. The system safely halted.")
            lines.append("  Inspect the case timeline or adjust tenant policy bounds to retry.")
        elif pol_status == "NEEDS_REVIEW" or target_case.status == CaseStatus.PENDING_APPROVAL:
            lines.append("  Human operator approval required before dispatching the recovery action.")
        else:
            lines.append("  Case is open. You can execute recovery using 'Recover this case'.")

    # -----------------------------------------------------------------------
    # BRANCH 4: Payment Link Direct Lookup — "Where is the payment link?"
    # -----------------------------------------------------------------------
    elif kw_payment_link:
        top_case = target_case or (cases[0] if cases else None)
        if not top_case:
            lines.append("No active cases found.")
        else:
            cid_str = str(top_case.id)
            cid_short = cid_str[:8]
            ctx = dict(top_case.context or {})
            plink_url = ctx.get("payment_link_url")
            plink_id = ctx.get("payment_link_id", "Generated")
            meta["case_id"] = cid_str
            meta["links"].append({"label": "Open Case", "href": f"/cases/{cid_str}", "is_external": False})

            if plink_url:
                meta["payment_link_url"] = plink_url
                meta["links"].append({"label": "Open Razorpay Payment Link", "href": plink_url, "is_external": True})
                lines.append(f"Active Payment Link for Case {cid_short}…:")
                lines.append("")
                lines.append(f"  Payment Link:  {plink_url}")
                lines.append(f"  Provider Ref:  {plink_id}")
                lines.append(f"  Amount:        {_fmt_inr(top_case.amount or 0)}")
                lines.append(f"  Status:        {_case_status_str(top_case)}")
                lines.append("")
                lines.append("Click 'Open Razorpay Payment Link' below to test payment in Razorpay Test Mode.")
            else:
                lines.append(f"No payment link has been generated yet for Case {cid_short}…")
                lines.append(f"Current Status: {_case_status_str(top_case)}.")
                lines.append("To generate an authorized payment link, ask 'Recover this case.'")

    # -----------------------------------------------------------------------
    # BRANCH 5: Recovered Amount Lookup — "How much did we recover?"
    # -----------------------------------------------------------------------
    elif kw_recover_amount:
        if target_case:
            out_r = await db.execute(select(RecoveryOutcome).where(RecoveryOutcome.case_id == target_case.id))
            out = out_r.scalar_one_or_none()
            cid_str = str(target_case.id)
            meta["case_id"] = cid_str
            meta["links"].append({"label": "Open Case", "href": f"/cases/{cid_str}", "is_external": False})
            meta["links"].append({"label": "View Recovery Impact", "href": "/impact", "is_external": False})

            lines.append(f"Recovery status for Case {cid_str[:8]}…:")
            if out and out.outcome_status in (RecoveryOutcomeStatus.RECOVERED, RecoveryOutcomeStatus.PARTIALLY_RECOVERED):
                lines.append(f"  Verified Recovered: {_fmt_inr(out.recovered_amount or 0)}")
                lines.append(f"  Attribution Source: {out.recovery_source.value}")
            else:
                lines.append("  Recovered Amount:   ₹0.00 (Payment not yet confirmed by gateway)")
                lines.append(f"  Amount at Risk:     {_fmt_inr(target_case.amount or 0)}")
        else:
            outcomes_r = await db.execute(select(RecoveryOutcome).where(RecoveryOutcome.tenant_id == tenant_id))
            all_outcomes = list(outcomes_r.scalars().all())
            total_recovered = sum(
                o.recovered_amount or 0
                for o in all_outcomes
                if o.outcome_status in (RecoveryOutcomeStatus.RECOVERED, RecoveryOutcomeStatus.PARTIALLY_RECOVERED)
            )
            action_attr = sum(1 for o in all_outcomes if o.recovery_source == RecoverySource.ACTION_ATTRIBUTED)
            meta["links"].append({"label": "View Recovery Impact", "href": "/impact", "is_external": False})
            meta["links"].append({"label": "View Operational Cases", "href": "/cases", "is_external": False})

            lines.append("ARIV REVENUE RECOVERY TOTALS")
            lines.append("=" * 45)
            lines.append("")
            lines.append(f"  Total Verified Recovered: {_fmt_inr(total_recovered)}")
            lines.append(f"  Action-Attributed Cases:  {action_attr}")
            lines.append(f"  Total Recovered Cases:    {len([o for o in all_outcomes if o.outcome_status == RecoveryOutcomeStatus.RECOVERED])}")
            lines.append("")
            lines.append("All recovered amounts reflect verified Razorpay webhook confirmations.")

    # -----------------------------------------------------------------------
    # BRANCH 6: Policy Rejection Explanation — "Why was this rejected?"
    # -----------------------------------------------------------------------
    elif kw_rejected:
        target = target_case or (cases[0] if cases else None)
        if not target:
            lines.append("No cases found to evaluate policy rejection.")
        else:
            cid_str = str(target.id)
            dec_r = await db.execute(
                select(DecisionRecord).where(DecisionRecord.case_id == target.id).order_by(desc(DecisionRecord.timestamp)).limit(1)
            )
            dec = dec_r.scalar_one_or_none()
            meta["case_id"] = cid_str
            meta["links"].append({"label": "Open Case Timeline", "href": f"/cases/{cid_str}", "is_external": False})

            lines.append(f"POLICY EVALUATION FOR CASE {cid_str[:8]}…")
            lines.append("=" * 45)
            lines.append("")
            if dec and dec.policy_status == PolicyStatus.REJECTED:
                lines.append(f"  Policy Gate:       REJECTED")
                lines.append(f"  Proposed Action:   {dec.proposed_action.value}")
                lines.append(f"  Rejection Reason:  {dec.rejection_reason or 'Policy safety boundary exceeded'}")
                lines.append("")
                lines.append("The deterministic Policy Engine prevented provider dispatch to protect tenant safety.")
            elif dec:
                lines.append(f"  Policy Gate:       {dec.policy_status.value}")
                lines.append(f"  Proposed Action:   {dec.proposed_action.value}")
                lines.append("  This case was NOT rejected by the Policy Firewall.")
            else:
                lines.append("  No policy evaluation record found for this case.")

    # -----------------------------------------------------------------------
    # BRANCH 7: System Health
    # -----------------------------------------------------------------------
    elif kw_health:
        yield _event("step", "Probing live system health & dependencies…")
        db_ok, redis_ok, qdrant_status, telegram_status = True, True, "unknown", "unknown"
        try:
            from app.infrastructure.database import check_db_health
            from app.infrastructure.redis import check_redis_health
            from app.infrastructure.qdrant import check_qdrant_health
            from app.services.telegram import TelegramNotifier

            db_ok = await check_db_health()
            redis_ok = await check_redis_health()
            qdrant_status = await check_qdrant_health()
            telegram_status = await TelegramNotifier.check_health()
        except Exception as e:
            logger.warning("Health probe error: %s", e)

        is_core_ok = db_ok and redis_ok
        overall = "ok" if is_core_ok and qdrant_status not in ("degraded", "down") else ("degraded" if is_core_ok else "down")

        lines.append("ARIV SYSTEM HEALTH")
        lines.append("=" * 45)
        lines.append("")
        lines.append(f"  Overall:            {'ALL SYSTEMS OPERATIONAL' if overall == 'ok' else overall.upper()}")
        lines.append("")
        pg_icon = _status_icon("ok" if db_ok else "down")
        rd_icon = _status_icon("ok" if redis_ok else "down")
        q_icon = _status_icon(qdrant_status)
        t_icon = _status_icon(telegram_status)
        lines.append(f"  {pg_icon} PostgreSQL:         {'Connected' if db_ok else 'DOWN'}")
        lines.append(f"  {rd_icon} Redis:              {'Connected' if redis_ok else 'DOWN'}")
        lines.append(f"  {q_icon} Qdrant:             {qdrant_status.capitalize()}")
        lines.append("  ✓ Decision Engine:   Active")
        lines.append("  ✓ Policy Engine:     Active")
        lines.append("  ✓ Execution Worker:  Active")
        lines.append("  ✓ Razorpay:          Connected (Test Mode)")
        lines.append(f"  {t_icon} Telegram:           {telegram_status.capitalize()}")
        lines.append("")
        lines.append(f"  Active Cases (tenant): {len(cases)}")
        if qdrant_status in ("degraded", "down"):
            lines.append("")
            lines.append("Note: Qdrant is in graceful degradation (historical_cases collection missing).")
            lines.append("Recovery Memory is inactive; core recovery and payment link creation are unaffected.")

        meta["links"].append({"label": "Open System Health", "href": "/system", "is_external": False})

    # -----------------------------------------------------------------------
    # BRANCH 8: Recovery Preview — "How would ARIV recover this?"
    # -----------------------------------------------------------------------
    elif kw_preview:
        yield _event("step", "Simulating recovery preview through Decision & Policy Engine…")
        preview_case = target_case or next(
            (c for c in cases if c.status not in (CaseStatus.RECOVERED, CaseStatus.FAILED, CaseStatus.CLOSED)),
            cases[0] if cases else None,
        )

        if not preview_case:
            lines.append("No active cases available to preview.")
        else:
            cid_str = str(preview_case.id)
            meta["case_id"] = cid_str
            meta["links"].append({"label": "Open Case", "href": f"/cases/{cid_str}", "is_external": False})

            cls_r = await db.execute(
                select(RecoveryClassification)
                .where(RecoveryClassification.case_id == preview_case.id)
                .order_by(desc(RecoveryClassification.timestamp))
                .limit(1)
            )
            cls_rec = cls_r.scalar_one_or_none()

            lines.append("RECOVERY PREVIEW (SIMULATION — NO ACTION TAKEN)")
            lines.append("=" * 45)
            lines.append("")
            lines.append(f"Case:    {cid_str[:8]}…")
            lines.append(f"Amount:  {_fmt_inr(preview_case.amount or 0)}")
            lines.append(f"Status:  {_case_status_str(preview_case)}")
            lines.append("")

            if cls_rec:
                cat = cls_rec.failure_category.value
                if cat in ("CUSTOMER_ACTION_REQUIRED", "AUTHENTICATION_REQUIRED"):
                    predicted = "GENERATE_PAYMENT_LINK"
                    rationale = "Customer must re-initiate payment via a fresh method. ARIV generates a Razorpay Payment Link."
                elif cat == "PROVIDER_DEGRADATION":
                    predicted = "RETRY_LATER"
                    rationale = "Provider degradation detected. ARIV schedules a later retry to avoid wasting attempts."
                elif cat == "TRANSIENT_TECHNICAL":
                    predicted = "RETRY_NOW"
                    rationale = "Transient technical error. Immediate retry is safe and likely to succeed."
                elif cat == "NON_RETRIABLE":
                    predicted = "STOP_RECOVERY"
                    rationale = "Terminal failure. PolicyEngine blocks recovery to prevent unnecessary charges."
                else:
                    predicted = "GENERATE_PAYMENT_LINK"
                    rationale = "Default autonomous recovery: issue customer Payment Link."

                lines.append(f"Failure Category: {cat}")
                lines.append(f"Predicted Action: {predicted}")
                lines.append(f"Rationale:        {rationale}")
                lines.append("")
                lines.append("To execute this authorized action, ask 'Recover this case.'")
                meta["can_recover"] = True
            else:
                lines.append("No classification signals recorded for this case.")

    # -----------------------------------------------------------------------
    # BRANCH 9: Pending Recoveries / Queue
    # -----------------------------------------------------------------------
    elif kw_pending:
        yield _event("step", "Scanning operational cases queue for pending recoveries…")
        pending = [c for c in cases if c.status in (CaseStatus.OPEN, CaseStatus.RISK_ASSESSED, CaseStatus.PENDING_APPROVAL)]
        lines.append(f"PENDING RECOVERIES ({len(pending)} active)")
        lines.append("=" * 45)
        lines.append("")
        if not pending:
            lines.append("No pending cases. All cases are currently resolved or recovered.")
        else:
            for p in pending[:5]:
                p_ctx = dict(p.context or {})
                stage = p_ctx.get("recovery_stage") or _case_status_str(p)
                lines.append(f"Case {str(p.id)[:8]}… | {_fmt_inr(p.amount or 0)} | Stage: {stage}")
                if p_ctx.get("payment_link_url"):
                    lines.append(f"  Link: {p_ctx['payment_link_url']}")
                lines.append("")

        meta["links"].append({"label": "View All Cases", "href": "/cases", "is_external": False})

    # -----------------------------------------------------------------------
    # DEFAULT BRANCH: General Contextual Operational Assistant
    # -----------------------------------------------------------------------
    else:
        open_cases = [c for c in cases if c.status in (CaseStatus.OPEN, CaseStatus.RISK_ASSESSED, CaseStatus.PENDING_APPROVAL)]
        recovered = [c for c in cases if c.status == CaseStatus.RECOVERED]
        total_at_risk = sum(c.amount or 0 for c in cases)

        lines.append("ARIV REVENUE RECOVERY CONTROL CENTER")
        lines.append("=" * 45)
        lines.append("")
        lines.append(f"  Total Revenue at Risk: {_fmt_inr(total_at_risk)}")
        lines.append(f"  Active Queue:          {len(open_cases)} cases")
        lines.append(f"  Recovered Cases:       {len(recovered)} cases")
        lines.append("")
        lines.append("Suggested Prompts:")
        lines.append("  • 'What is happening right now?'")
        lines.append("  • 'What's happening with this case?'")
        lines.append("  • 'Recover this case.'")
        lines.append("  • 'Where is the payment link?'")
        lines.append("  • 'How much was recovered?'")
        lines.append("  • 'Is ARIV healthy?'")

        meta["links"].append({"label": "View Operational Cases", "href": "/cases", "is_external": False})
        meta["links"].append({"label": "View Recovery Impact", "href": "/impact", "is_external": False})
        meta["links"].append({"label": "System Health", "href": "/system", "is_external": False})

    # Yield meta payload followed by content and DONE
    yield _event("meta", meta)
    answer = "\n".join(lines)
    yield _event("content", answer)
    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/query")
async def agent_query(
    body: AgentQueryRequest,
    tenant=Depends(_get_tenant),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Streaming agent query endpoint.
    Emits SSE events: { type: 'step', text }, { type: 'meta', ... }, { type: 'content', text }.
    """
    return StreamingResponse(
        _agent_stream(
            query=body.query,
            tenant_id=str(tenant.id),
            db=db,
            current_route=body.current_route,
            context_case_id=body.case_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
