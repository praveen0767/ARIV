"""
tests/test_benchmark_metrics.py

Focused unit tests for the REAL TEST-MODE benchmark metric layer (Phase 4).

Covers:
  1. Metric formula definitions (decision coverage, policy approval, human
     review, execution attempt, provider action success, execution failure,
     recovery, attribution).
  2. Zero-denominator handling: rates must be the literal string
     'NOT_APPLICABLE' -- never NaN, Infinity, or a misleading 0%.
  3. Aggregation correctness of summarize_metrics() including decisions_by_action,
     needs_review vs policy_blocked vs human_approval, provider_actions_succeeded
     from SUCCEEDED attempts, and recovery/attribution counts.
  4. compute_report() serialization shape and per-case scenario labeling.
  5. Benchmark cohort isolation invariant (payment_id prefix scoping) and the
     documented invariant that metrics only reflect pipeline-persisted rows.

These tests are fully offline: no webhook delivery and no database access.
"""

import json

from scripts.benchmark_utils import (
    CaseObservation,
    SentEvent,
    compute_report,
    derive_metrics,
    summarize_metrics,
    _case_payment_id_like,
)


def _obs(
    amount_minor: int,
    case_status: str = "RISK_ASSESSED",
    decision_actions=None,
    decision_policy_statuses=None,
    decision_autonomy_levels=None,
    attempt_statuses=None,
    execution_failures: int = 0,
    outcome_status=None,
    recovered_amount_minor: int = 0,
    recovery_source=None,
    human_escalation: bool = False,
    scenario="UNKNOWN_ERR",
    payment_id="pay_bench_x_1",
) -> CaseObservation:
    return CaseObservation(
        case_id=f"case_{payment_id}",
        payment_id=payment_id,
        amount_minor=amount_minor,
        case_status=case_status,
        scenario=scenario,
        error_code="DO_NOT_HONOR",
        error_reason="do not honor",
        route_status="CRITICAL",
        decision_actions=decision_actions or [],
        decision_policy_statuses=decision_policy_statuses or [],
        decision_autonomy_levels=decision_autonomy_levels or [],
        attempt_statuses=attempt_statuses or [],
        execution_failures=execution_failures,
        outcome_status=outcome_status,
        recovered_amount_minor=recovered_amount_minor,
        recovery_source=recovery_source,
        human_escalation=human_escalation,
    )


def test_zero_denominator_metrics_report_not_applicable():
    """Empty cohort: every rate surfaces as NOT_APPLICABLE, never NaN/Inf/0%."""
    derived = derive_metrics(summarize_metrics([]))
    for key in (
        "decision_coverage",
        "policy_approval_rate",
        "human_review_rate",
        "execution_attempt_rate",
        "provider_action_success_rate",
        "execution_failure_rate",
        "recovery_rate",
        "attribution_rate",
    ):
        assert derived[key] == "NOT_APPLICABLE", key
        assert isinstance(derived[key], str)


def test_zero_attribution_with_no_recoveries_is_not_applicable():
    """No verified recoveries -> attribution_rate is NOT_APPLICABLE (0% would be misleading)."""
    obs = [
        _obs(10000, decision_actions=["STOP_RECOVERY"], decision_policy_statuses=["APPROVED"])
    ]
    raw = summarize_metrics(obs)
    assert raw["verified_recoveries"] == 0
    derived = derive_metrics(raw)
    assert derived["attribution_rate"] == "NOT_APPLICABLE"
    assert derived["recovery_rate"] == 0.0


def test_zero_attempts_expose_failure_rate_as_not_applicable():
    """No execution dispatch -> success/failure rates must not read as 0%."""
    obs = [
        _obs(10000, decision_actions=["STOP_RECOVERY"], decision_policy_statuses=["APPROVED"])
    ]
    derived = derive_metrics(summarize_metrics(obs))
    assert derived["execution_attempt_rate"] == 0.0
    assert derived["provider_action_success_rate"] == "NOT_APPLICABLE"
    assert derived["execution_failure_rate"] == "NOT_APPLICABLE"


def test_default_recovery_rate_is_zero_percent_when_no_recoveries():
    """recovery_rate uses cases_observed (never zero for a delivered cohort) and is a
    real measured 0% -- distinct from the misleading-zero case above."""
    obs = [_obs(10000, decision_actions=["STOP_RECOVERY"])]
    derived = derive_metrics(summarize_metrics(obs))
    assert derived["recovery_rate"] == 0.0


def test_metric_formulas_known_values():
    """Known-cohort sanity: hand-computed expected rates."""
    obs = [
        _obs(
            5000,
            case_status="RECOVERED",
            decision_actions=["GENERATE_PAYMENT_LINK"],
            decision_policy_statuses=["APPROVED"],
            decision_autonomy_levels=["FULL_AUTO"],
            attempt_statuses=["SUCCEEDED", "SUCCEEDED"],
            outcome_status="RECOVERED",
            recovered_amount_minor=5000,
            recovery_source="ACTION_ATTRIBUTED",
            scenario="CUSTOMER_ACTION_REQUIRED",
        ),
        _obs(
            7000,
            case_status="RECOVERED",
            decision_actions=["GENERATE_PAYMENT_LINK"],
            decision_policy_statuses=["APPROVED"],
            decision_autonomy_levels=["FULL_AUTO"],
            attempt_statuses=["SUCCEEDED"],
            outcome_status="RECOVERED",
            recovered_amount_minor=7000,
            recovery_source="ACTION_ATTRIBUTED",
            scenario="CUSTOMER_ACTION_REQUIRED",
        ),
        _obs(
            12000,
            decision_actions=["RETRY_NOW"],
            decision_policy_statuses=["NEEDS_REVIEW"],
            decision_autonomy_levels=["HUMAN_APPROVAL"],
            attempt_statuses=["FAILED"],
            execution_failures=1,
            human_escalation=True,
            scenario="TRANSIENT_TECHNICAL",
        ),
        _obs(
            20000,
            decision_actions=["STOP_RECOVERY"],
            decision_policy_statuses=["REJECTED"],
            decision_autonomy_levels=["FULL_AUTO"],
            scenario="NON_RETRIABLE",
        ),
    ]

    raw = summarize_metrics(obs)
    assert raw["cases_observed"] == 4
    assert raw["total_amount_at_risk_minor"] == 44000
    assert raw["total_amount_at_risk_inr"] == 440.0
    assert raw["decision_engine_cases"] == 4
    assert raw["policy_evaluated"] == 4
    assert raw["policy_approved"] == 2
    assert raw["needs_review"] == 1
    assert raw["policy_blocked"] == 1
    assert raw["human_approval"] == 1
    assert raw["execution_attempts"] == 4
    assert raw["provider_actions_succeeded"] == 3
    assert raw["execution_failures"] == 1
    assert raw["verified_recoveries"] == 2
    assert raw["attributed_recoveries"] == 2
    assert raw["revenue_recovered_minor"] == 12000
    assert raw["revenue_recovered_inr"] == 120.0
    assert raw["decisions_by_action"] == {
        "GENERATE_PAYMENT_LINK": 2,
        "RETRY_NOW": 1,
        "STOP_RECOVERY": 1,
    }

    derived = derive_metrics(raw)
    assert derived["decision_coverage"] == 100.0
    assert derived["policy_approval_rate"] == 50.0
    assert derived["human_review_rate"] == 25.0
    assert derived["execution_attempt_rate"] == 100.0
    assert derived["provider_action_success_rate"] == 75.0
    assert derived["execution_failure_rate"] == 25.0
    assert derived["recovery_rate"] == 50.0
    assert derived["attribution_rate"] == 100.0


def test_compute_report_shape_and_scenario_labels():
    """compute_report serializes scenario metadata per case and derived metrics."""
    obs = [
        _obs(
            5000,
            case_status="RECOVERED",
            decision_actions=["GENERATE_PAYMENT_LINK"],
            decision_policy_statuses=["APPROVED"],
            decision_autonomy_levels=["FULL_AUTO"],
            attempt_statuses=["SUCCEEDED"],
            outcome_status="RECOVERED",
            recovered_amount_minor=5000,
            recovery_source="ACTION_ATTRIBUTED",
            scenario="CUSTOMER_ACTION_REQUIRED",
            payment_id="pay_bench_b1_0",
        ),
        _obs(
            12000,
            decision_actions=["STOP_RECOVERY"],
            decision_policy_statuses=["NEEDS_REVIEW"],
            decision_autonomy_levels=["HUMAN_APPROVAL"],
            human_escalation=True,
            scenario="UNKNOWN_ERR",
            payment_id="pay_bench_b1_1",
        ),
    ]
    sent = [
        SentEvent(index=0, event_id="evt_x_0", payment_id="pay_bench_b1_0", amount_minor=5000, http_status=200, accepted=True)
    ]

    report = compute_report(
        benchmark_id="bench_unit_b1",
        start_time="2026-09-07T00:00:00Z",
        end_time="2026-09-07T00:00:01Z",
        cases_requested=2,
        observations=obs,
        sent_delivery=sent,
    )

    assert report["total_cases"] == 2
    assert {"RETRY_NOW", "GENERATE_PAYMENT_LINK", "STOP_RECOVERY"} >= set(report["decisions_by_action"])
    assert report["derived_metrics"]["decision_coverage"] == 100.0
    assert report["delivery"][0]["accepted"] is True

    cases = {c["payment_id"]: c for c in report["cases"]}
    assert cases["pay_bench_b1_0"]["scenario"] == "CUSTOMER_ACTION_REQUIRED"
    assert cases["pay_bench_b1_1"]["scenario"] == "UNKNOWN_ERR"
    assert cases["pay_bench_b1_1"]["human_escalation"] is True

    # Entire report must be JSON-serializable (phase-4 evidence artifact).
    json.dumps(report, default=str)


def test_not_observed_cases_excluded_from_metrics_but_listed():
    """NOT_OBSERVED cases appear in cases[] but never inflate observed metrics."""
    obs = [
        _obs(
            5000,
            case_status="NOT_OBSERVED",
            scenario="CUSTOMER_ACTION_REQUIRED",
            payment_id="pay_bench_b1_0",
        ),
        _obs(
            10000,
            case_status="RISK_ASSESSED",
            decision_actions=["STOP_RECOVERY"],
            decision_policy_statuses=["APPROVED"],
            payment_id="pay_bench_b1_1",
        ),
    ]
    report = compute_report(
        benchmark_id="bench_unit_b2",
        start_time="2026-09-07T00:00:00Z",
        end_time="2026-09-07T00:00:01Z",
        cases_requested=2,
        observations=obs,
        sent_delivery=[],
    )
    assert report["total_cases"] == 1
    assert report["total_amount_at_risk_minor"] == 10000
    assert len(report["cases"]) == 2


def test_benchmark_cohort_isolation_prefix():
    """Benchmark correlation scope is the embedded benchmark_id prefix: a case
    whose payment_id belongs to another benchmark can never be counted by this
    run's observability query."""
    from sqlalchemy.dialects import postgresql

    compiled = _case_payment_id_like("bench_a").compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    sql = str(compiled)
    assert "payment_id" in sql
    assert "bench_a" in sql
    # Payment ids are pay_<benchmarked>_<index>; the prefix match is exact-scoped.
    assert sql.count("bench_a") == 1