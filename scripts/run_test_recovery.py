#!/usr/bin/env python3
"""
scripts/run_test_recovery.py

ONE command for the complete ARIV local demo recovery scenario.

Creates a legitimate Razorpay payment.failed test event through the existing
signed webhook path and lets the existing pipeline run end to end:

    ProviderEvent -> Recovery Case -> Decision -> Economic Optimization (ENR)
    -> PolicyEngine -> Approved action -> Execution Worker -> real Razorpay
    Test-Mode payment link (when GENERATE_PAYMENT_LINK is selected).

No outcomes are fabricated and the case is never marked RECOVERED. Creating a
payment link is only a provider/execution result; ARIV still awaits a real
payment_link.paid webhook before counting recovery.

Usage:
    python scripts/run_test_recovery.py --amount 100
    python scripts/run_test_recovery.py --amount 250 --description "ARIV Test Recovery"

Exit code is 0 when a new Recovery Case is created, non-zero on failure.
"""

import argparse
import asyncio
import hmac
import hashlib
import sys
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_settings():
    from app.core.config import Settings

    env_file = PROJECT_ROOT / ".env"
    if env_file.is_file():
        return Settings(_env_file=str(env_file))
    return Settings()


def format_rupees(paise_or_major: float, paise: bool = True) -> str:
    amount = paise_or_major / 100.0 if paise else paise_or_major
    amount = Decimal(str(amount))
    if amount == amount.to_integral_value():
        return f"\u20b9{int(amount)}"
    return f"\u20b9{amount.quantize(Decimal('0.01'))}"


def parse_amount(value: str) -> int:
    try:
        rupees = Decimal(value)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"invalid amount: {value!r} (must be a positive number in rupees)")
    if not rupees.is_finite() or rupees <= 0:
        raise argparse.ArgumentTypeError(f"invalid amount: {value!r} (must be a positive number in rupees)")
    scaled = rupees * Decimal(100)
    if scaled != scaled.to_integral_value():
        raise argparse.ArgumentTypeError(f"invalid amount: {value!r} (must have at most two decimal places)")
    paise = int(scaled)
    if paise < 100:
        raise argparse.ArgumentTypeError("minimum amount is \u20b91 (100 paise)")
    return paise


def api_headers(settings, account_id: str) -> dict:
    signature = hmac.new(
        settings.INTERNAL_API_KEY.encode("utf-8"),
        account_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {"X-Account-ID": account_id, "X-Signature": signature}


async def run(amount_minor: int, description: str, api_base: str, timeout_seconds: int) -> int:
    import httpx

    settings = load_settings()
    account_id = (settings.DEMO_ACCOUNT_ID or "acc_demo_123").strip()

    webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
    if not webhook_secret:
        print("ERROR: RAZORPAY_WEBHOOK_SECRET is not configured in .env.", file=sys.stderr)
        return 1

    event_id = f"ev_ariv_demo_{uuid.uuid4().hex[:10]}"
    payment_id = f"pay_ariv_demo_{uuid.uuid4().hex[:10]}"

    payload = {
        "event": "payment.failed",
        "account_id": account_id,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "amount": amount_minor,
                    "currency": "INR",
                    "email": "customer@example.com",
                    "contact": "9876543210",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_reason": "Insufficient balance",
                    "notes": {"description": description},
                }
            }
        },
    }

    body = __import__("json").dumps(payload).encode("utf-8")
    signature = hmac.new(webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    webhook_url = f"{api_base}/webhooks/razorpay"
    headers = {
        "Content-Type": "application/json",
        "x-razorpay-signature": signature,
        "x-razorpay-event-id": event_id,
    }

    print("Creating ARIV local demo recovery scenario (test payment failure)...")
    print(f"  Event ID: {event_id}")
    print(f"  Payment ID: {payment_id}")
    print(f"  Account: {account_id}")
    print(f"  Amount: {format_rupees(amount_minor)}")
    print(f"  Description: {description}")
    print()

    snapshot_before: set = set()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            pre = await client.get(
                f"{api_base}/v1/recovery/cases?limit=50",
                headers=api_headers(settings, account_id),
            )
            if pre.status_code == 200:
                snapshot_before = {c.get("case_id") for c in pre.json() if isinstance(c, dict) and c.get("case_id")}
    except Exception as exc:
        print(f"WARNING: could not snapshot existing cases ({type(exc).__name__})", file=sys.stderr)

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.post(webhook_url, content=body, headers=headers)
    except Exception as exc:
        print(f"ERROR: could not reach webhook at {webhook_url}: {exc}", file=sys.stderr)
        return 1

    if resp.status_code != 200:
        print(f"ERROR: webhook rejected the test event (HTTP {resp.status_code}).", file=sys.stderr)
        print(f"       Response: {resp.text[:300]}", file=sys.stderr)
        return 1

    print(f"Webhook accepted (status={resp.json().get('message', 'ok')}).")
    print("Waiting for the existing pipeline to create the Recovery Case...")

    deadline = time.monotonic() + timeout_seconds
    case_id = None
    detail = None

    while time.monotonic() < deadline:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                r = await client.get(
                    f"{api_base}/v1/recovery/cases?limit=50",
                    headers=api_headers(settings, account_id),
                )
                if r.status_code == 200:
                    for c in r.json():
                        cid = (c or {}).get("case_id")
                        if cid and cid not in snapshot_before and str((c or {}).get("amount_minor")) == str(amount_minor):
                            case_id = cid
                            break
        except Exception:
            pass

        if case_id:
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                    d = await client.get(
                        f"{api_base}/v1/recovery/cases/{case_id}/full",
                        headers=api_headers(settings, account_id),
                    )
                    if d.status_code == 200:
                        detail = d.json()
                        case_payment_id = None
                        ctx = (detail.get("case") or {}).get("context") or {}
                        case_payment_id = ctx.get("payment_id")
                        if case_payment_id == payment_id:
                            break
                        if not case_payment_id and detail.get("decision"):
                            break
            except Exception:
                pass
        await asyncio.sleep(1.5)

    if not case_id or not detail:
        print(f"ERROR: no new Recovery Case appeared within {timeout_seconds}s for the test event.", file=sys.stderr)
        return 1

    await print_summary(detail, case_id, payment_id)
    return 0


async def print_summary(detail: dict, case_id: str, payment_id: str) -> None:
    case = detail.get("case", {})
    decision = detail.get("decision", {})
    economic = detail.get("economic") or {}
    execution = detail.get("execution") or {}
    recovery = detail.get("recovery") or {}

    print()
    print("Recovery Case:")
    print(f"  Case ID: {case.get('id')}")
    print(f"  Status: {case.get('status')}")
    print(f"  Amount at risk: {format_rupees(case.get('amount_minor', 0))}")
    print(f"  Frontend UI: http://localhost:3000/cases/{case.get('id')}")

    print()
    print("Decision:")
    print(f"  Proposed Action: {decision.get('proposed_action')}")
    print(f"  Baseline Action: {decision.get('baseline_action')}")
    print(f"  AI Confidence: {decision.get('ai_confidence')}")

    candidates = economic.get("ranked_candidates") or []
    print()
    print("Economic Optimization (ENR):")
    print(f"  Method: {economic.get('method', 'ENR')}")
    if economic.get("selected_enr") is not None:
        print(f"  Selected ENR: {format_rupees(float(economic['selected_enr']), paise=False)}")
    if economic.get("selected_probability") is not None:
        print(f"  Recovery Probability: {float(economic['selected_probability']) * 100:.0f}%")
    for cand in candidates[:3]:
        enr = float(cand.get("expected_net_recovery", 0) or 0)
        prob = float(cand.get("recovery_probability", 0) or 0)
        mark = "->" if cand.get("action") == decision.get("proposed_action") else "  "
        print(f"  {mark} {cand.get('action')}: ENR {format_rupees(enr, paise=False)} (p={prob:.2f})")

    print()
    print("PolicyEngine:")
    policy_final = None
    policy_evaluations = economic.get("policy_evaluations") or []
    for p in policy_evaluations:
        if p.get("action") == decision.get("proposed_action"):
            policy_final = p
            break
    status = decision.get("policy_status")
    autonomy = decision.get("autonomy_level")
    reason = decision.get("rejection_reason")
    if policy_final:
        status = policy_final.get("policy_status", status)
        autonomy = policy_final.get("autonomy_level", autonomy)
        reason = policy_final.get("rejection_reason", reason)
    print(f"  Status: {status}")
    print(f"  Autonomy: {autonomy}")
    if reason:
        print(f"  Rejection Reason: {reason}")

    print()
    print("Recovery Action & Execution:")
    if execution:
        print(f"  Action: {execution.get('action_type')}")
        print(f"  Execution Status: {execution.get('status')}")
        print(f"  Provider: {execution.get('provider')}")
        print(f"  Recovery Stage: {execution.get('recovery_stage')}")

    link = execution.get("payment_link_url") or (case.get("context") or {}).get("payment_link_url")
    plink_id = (
        execution.get("provider_resource_id")
        or execution.get("provider_reference")
        or (case.get("context") or {}).get("payment_link_id")
    )
    print()
    print("Payment Link (Razorpay Test Mode):")
    if link or plink_id:
        print(f"  ID: {plink_id or 'N/A'}")
        print(f"  URL: {link or 'N/A'}")
    else:
        print("  Not created — the selected action was not GENERATE_PAYMENT_LINK or no provider execution ran.")

    print()
    print(f"Outcome: {recovery.get('outcome_status')} — NOT RECOVERED. ARIV awaits a real "
          f"payment_link.paid webhook before confirming recovery for payment {payment_id}.")


def main() -> int:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    parser = argparse.ArgumentParser(
        prog="run_test_recovery",
        description="Run the complete ARIV local demo recovery scenario (test failure -> decision -> policy -> Razorpay Test-Mode payment link).",
    )
    parser.add_argument("--amount", type=parse_amount, required=True, help="Amount in rupees (e.g. 100 = \u20b9100).")
    parser.add_argument("--description", default="ARIV Test Recovery", help="Scenario label (default: 'ARIV Test Recovery').")
    parser.add_argument("--api-base", default=None, help="Backend base URL (default: ARIV_API_BASE env or http://localhost:8000).")
    parser.add_argument("--timeout", type=int, default=90, help="Seconds to wait for the pipeline (default: 90).")
    args = parser.parse_args()

    api_base = args.api_base or __import__("os").getenv("ARIV_API_BASE", "http://localhost:8000").rstrip("/")
    return asyncio.run(run(args.amount, args.description, api_base, args.timeout))


if __name__ == "__main__":
    sys.exit(main())