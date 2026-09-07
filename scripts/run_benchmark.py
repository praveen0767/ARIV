#!/usr/bin/env python3
"""
scripts/run_benchmark.py

ARIV REAL TEST-MODE Webhook Benchmark (one-off evaluation harness).

Exercises the EXISTING ARIV pipeline end to end:
    TEST INPUT -> POST /webhooks/razorpay -> signature verify -> ProviderEvent
    -> RecoveryCase -> Failure Intelligence -> Decision Context -> Qdrant (where available)
    -> AI / decision layer -> PolicyEngine -> Execution Outbox / worker -> provider path
    -> RecoveryOutcome -> attribution -> measurement.

It NEVER:
  - directly inserts RecoveryCase/RecoveryOutcome/Execution rows
  - forces cases into RECOVERED
  - alters PolicyEngine / attribution / execution semantics
  - touches historical cases

Every metric in the JSON report is computed from rows the ARIV pipeline itself
persisted. Unsupported metrics are reported as "NOT_MEASURED".
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# Ensure the project root is importable when running from any CWD so that
# `from scripts.benchmark_utils import ...` resolves consistently.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmark_utils import (
    ScenarioSpec,
    build_failure_payload,
    compute_report,
    generate_amounts,
    generate_benchmark_id,
    make_event_id,
    make_payment_id,
    observe_cases,
    resolve_benchmark_account_id,
    resolve_webhook_secret,
    send_events,
    should_keep_polling,
    write_report,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ariv.benchmark")

DEFAULT_WEBHOOK_URL = "http://localhost:8000/webhooks/razorpay"
MINOR_MIN_DEFAULT = 5000          # 50.00 INR
MINOR_MAX_DEFAULT = 250000        # 2500.00 INR


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _poll_until_processed(
    benchmark_id: str,
    expected_count: int,
    poll_interval: float,
    max_wait: float,
) -> bool:
    waited = 0.0
    while waited < max_wait:
        still_waiting = await should_keep_polling(benchmark_id, expected_count)
        if not still_waiting:
            return True
        await asyncio.sleep(poll_interval)
        waited += poll_interval
    return False


async def run_benchmark(
    *,
    cases: int,
    minimum: int,
    maximum: int,
    webhook_url: str,
    account_id: str,
    output_dir: Path,
    poll_interval: float,
    max_wait: float,
    seed: int,
) -> dict:
    benchmark_id = generate_benchmark_id()
    start_time = utc_now()
    logger.info("Benchmark %s starting (TEST MODE, %d cases)", benchmark_id, cases)

    amounts = generate_amounts(cases, minimum, maximum, seed=seed)

    # Discover a mapped account_id when tenants already exist so that every
    # benchmark event resolves to a real tenant (resolve_tenant fails closed).
    resolved_account = await resolve_benchmark_account_id(account_id)
    logger.info("Using account_id=%s for tenant resolution", resolved_account)

    webhook_secret = resolve_webhook_secret()

    event_ids: List[str] = []
    payment_ids: List[str] = []
    payloads = []
    for i, amount in enumerate(amounts):
        eid = make_event_id(benchmark_id, i)
        pid = make_payment_id(benchmark_id, i)
        event_ids.append(eid)
        payment_ids.append(pid)
        payloads.append(
            build_failure_payload(
                benchmark_id=benchmark_id,
                index=i,
                amount_minor=amount,
                account_id=resolved_account,
                event_id=eid,
                payment_id=pid,
            )
        )

    report = await _deliver_observe_report(
        benchmark_id=benchmark_id,
        start_time=start_time,
        cases=cases,
        payloads=payloads,
        event_ids=event_ids,
        payment_ids=payment_ids,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        expected_count=cases,
        poll_interval=poll_interval,
        max_wait=max_wait,
        output_dir=output_dir,
    )
    return report


async def run_scenario_benchmark(
    *,
    scenarios: List[ScenarioSpec],
    webhook_url: str,
    account_id: str,
    output_dir: Path,
    poll_interval: float,
    max_wait: float,
    settle_delay: float = 1.0,
) -> dict:
    """
    Runs a scenario-cohort benchmark.

    Delivery order === list order. Each case's webhook inputs (error_code /
    error_reason / amount_minor) come from the ScenarioSpec; the input metadata
    is attached verbatim to the report only as descriptive context, never as a
    persisted pipeline result.
    """
    cases = len(scenarios)
    benchmark_id = generate_benchmark_id()
    start_time = utc_now()
    logger.info("Scenario benchmark %s starting (TEST MODE, %d cases)", benchmark_id, cases)

    resolved_account = await resolve_benchmark_account_id(account_id)
    logger.info("Using account_id=%s for tenant resolution", resolved_account)
    webhook_secret = resolve_webhook_secret()

    event_ids: List[str] = []
    payment_ids: List[str] = []
    payloads = []
    scenario_by_payment: dict = {}
    for i, spec in enumerate(scenarios):
        eid = make_event_id(benchmark_id, i)
        pid = make_payment_id(benchmark_id, i)
        event_ids.append(eid)
        payment_ids.append(pid)
        payloads.append(
            build_failure_payload(
                benchmark_id=benchmark_id,
                index=i,
                amount_minor=spec.amount_minor,
                account_id=resolved_account,
                event_id=eid,
                payment_id=pid,
                error_code=spec.error_code,
                error_reason=spec.error_reason,
            )
        )
        scenario_by_payment[pid] = {
            "scenario": spec.label,
            "error_code": spec.error_code,
            "error_reason": spec.error_reason,
        }

    report = await _deliver_observe_report(
        benchmark_id=benchmark_id,
        start_time=start_time,
        cases=cases,
        payloads=payloads,
        event_ids=event_ids,
        payment_ids=payment_ids,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        expected_count=cases,
        poll_interval=poll_interval,
        max_wait=max_wait,
        output_dir=output_dir,
        scenario_by_payment=scenario_by_payment,
        settle_delay=settle_delay,
    )
    return report


async def _deliver_observe_report(
    *,
    benchmark_id: str,
    start_time: str,
    cases: int,
    payloads,
    event_ids,
    payment_ids,
    webhook_url: str,
    webhook_secret: str,
    expected_count: int,
    poll_interval: float,
    max_wait: float,
    output_dir: Path,
    scenario_by_payment: Optional[dict] = None,
    settle_delay: float = 0.0,
) -> dict:
    logger.info("Sending %d webhook events to %s", len(payloads), webhook_url)
    delivery = await send_events(
        events=payloads,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        event_ids=event_ids,
        settle_delay=settle_delay,
    )
    accepted = sum(1 for d in delivery if d.accepted)
    logger.info("Accepted by webhook endpoint: %d/%d", accepted, len(delivery))

    end_time = utc_now()
    if accepted > 0 and cases > 0:
        observed_all = await _poll_until_processed(
            benchmark_id,
            expected_count=cases,
            poll_interval=poll_interval,
            max_wait=max_wait,
        )
        logger.info("Polling complete. observed_all=%s", observed_all)

    observations = await observe_cases(benchmark_id, payment_ids, scenario_by_payment)
    end_time = utc_now()

    report = compute_report(
        benchmark_id=benchmark_id,
        start_time=start_time,
        end_time=end_time,
        cases_requested=cases,
        observations=observations,
        sent_delivery=delivery,
    )

    # Honest unsupported-metric labels (no fabricated values).
    report["supported_metrics_note"] = (
        "human_escalations reflects persisted HUMAN_APPROVAL/NEEDS_REVIEW decision records; "
        "all other required metrics are computed from actual persisted rows."
    )

    report_path = write_report(report, output_dir)
    logger.info("Report written to %s", report_path)

    return report


def load_scenario_file(path: Path) -> List[ScenarioSpec]:
    """Reads a scenario-cohort JSON file into ordered ScenarioSpec objects."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit(f"{path} must contain a JSON array of scenario objects")
    scenarios: List[ScenarioSpec] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise SystemExit(f"{path}[{i}] must be an object")
        label = str(item.get("label", f"scenario_{i}"))
        amount_minor = int(item.get("amount_minor", 0))
        error_code = str(item.get("error_code", "UNKNOWN"))
        error_reason = str(item.get("error_reason", "UNKNOWN"))
        if amount_minor <= 0:
            raise SystemExit(f"{path}[{i}] amount_minor must be > 0")
        scenarios.append(
            ScenarioSpec(
                label=label,
                amount_minor=amount_minor,
                error_code=error_code,
                error_reason=error_reason,
            )
        )
    return scenarios


def parse_args():
    parser = argparse.ArgumentParser(description="ARIV REAL TEST-MODE webhook benchmark")
    parser.add_argument(
        "--scenario-file", type=str, default=None,
        help="JSON array of {label, amount_minor, error_code, error_reason} "
             "scenarios to deliver in list order instead of randomized amounts",
    )
    parser.add_argument("--cases", type=int, default=25, help="number of failure cases (default 25)")
    parser.add_argument(
        "--min", type=int, default=MINOR_MIN_DEFAULT,
        help="minimum amount in minor units (paise); default 5000 = 50.00 INR",
    )
    parser.add_argument(
        "--max", type=int, default=MINOR_MAX_DEFAULT,
        help="maximum amount in minor units (paise); default 250000 = 2500.00 INR",
    )
    parser.add_argument("--webhook-url", type=str, default=DEFAULT_WEBHOOK_URL)
    parser.add_argument(
        "--account-id", type=str, default="acc_benchmark",
        help="fallback account_id used only when no tenant is mapped yet",
    )
    parser.add_argument(
        "--output-dir", type=str, default=".",
        help="directory for benchmark_report_<id>.json",
    )
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--max-wait", type=float, default=180.0, help="seconds to wait for processing")
    parser.add_argument("--seed", type=int, default=None, help="deterministic amount seed")
    return parser.parse_args()


async def amain():
    args = parse_args()

    if args.scenario_file:
        scenarios = load_scenario_file(Path(args.scenario_file))
        if not scenarios:
            raise SystemExit("scenario file contains no scenarios")
        report = await run_scenario_benchmark(
            scenarios=scenarios,
            webhook_url=args.webhook_url,
            account_id=args.account_id,
            output_dir=Path(args.output_dir),
            poll_interval=args.poll_interval,
            max_wait=args.max_wait,
        )
    else:
        if args.cases <= 0:
            raise SystemExit("--cases must be > 0")
        report = await run_benchmark(
            cases=args.cases,
            minimum=args.min,
            maximum=args.max,
            webhook_url=args.webhook_url,
            account_id=args.account_id,
            output_dir=Path(args.output_dir),
            poll_interval=args.poll_interval,
            max_wait=args.max_wait,
            seed=args.seed,
        )

    print("\n===== ARIV TEST-MODE BENCHMARK SUMMARY =====")
    print(f"benchmark_id:            {report['benchmark_id']}")
    print(f"mode:                    {report['mode']}")
    print(f"cases_requested:         {report['cases_requested']}")
    print(f"cases_observed:          {report['cases_observed']}")
    print(f"total_amount_at_risk:    INR {report['total_amount_at_risk_inr']:.2f}")
    print(f"decision_engine_cases:   {report['decision_engine_cases']}")
    print(f"policy_approved:         {report['policy_approved']}")
    print(f"policy_blocked:          {report['policy_blocked']}")
    print(f"execution_attempts:      {report['execution_attempts']}")
    print(f"execution_failures:      {report['execution_failures']}")
    print(f"verified_recoveries:     {report['verified_recoveries']}")
    print(f"attributed_recoveries:   {report['attributed_recoveries']}")
    print(f"revenue_recovered:       INR {report['revenue_recovered_inr']:.2f}")
    print(f"recovery_rate:           {report['recovery_rate']}")
    print(f"human_escalations:       {report['human_escalations']}")
    print(f"report:                  benchmark_report_{report['benchmark_id']}.json")
    print("===========================================")


if __name__ == "__main__":
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        raise SystemExit("Interrupted.")