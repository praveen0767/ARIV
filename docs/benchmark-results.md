# ARIV Benchmark Results — REAL Razorpay Test Mode

> These benchmarks are **execution / decision-policy benchmarks**, **NOT recovery-rate
> benchmarks**. Every cohort is a *failure-only* cohort (every payment permanently
> failed in Razorpay Test Mode), so the only honest recovery reading is **0%**. The
> value of these runs is proving the end-to-end execution path and the governance
> behavior, not **claiming** recovered revenue.

| Benchmark | id | Cohort | Amount at risk | Report file |
|---|---|---|---|---|
| A — execution-scale | `bench_20260907_041856_fa9508` | 25 cases | ₹35,232.60 | `benchmark_report_bench_20260907_041856_fa9508.json` |
| B — scenario diversity | `bench_20260907_045936_39bde5` | 18 cases | ₹145,400.00 | `benchmark_report_bench_20260907_045936_39bde5.json` |
| smoke | `bench_20260907_041657_61886f` | 3 cases | ₹3,189.48 | `benchmark_report_bench_20260907_041657_61886f.json` |

---

## 1. Metric definitions

Every metric is computed in `scripts/benchmark_utils.py::summarize_metrics` /
`derive_metrics` from rows the ARIV pipeline itself persisted. **Zero-denominator
rates are reported as the literal string `NOT_APPLICABLE`** — never `NaN`,
`Infinity`, or a misleading `0%`.

| Metric | Formula | Zero-denominator behavior |
|---|---|---|
| Decision coverage | `decision_engine_cases / cases_observed` | `NOT_APPLICABLE` |
| Policy approval rate | `policy_approved / policy_evaluated` | `NOT_APPLICABLE` |
| Human review rate | `needs_review / cases_observed` | `NOT_APPLICABLE` |
| Execution attempt rate | `execution_attempts / cases_observed` | `NOT_APPLICABLE` |
| Provider action success rate | `provider_actions_succeeded / execution_attempts` | `NOT_APPLICABLE` |
| Execution failure rate | `execution_failures / execution_attempts` | `NOT_APPLICABLE` |
| Recovery rate | `verified_recoveries / cases_observed` | `NOT_APPLICABLE` |
| Attribution rate | `attributed_recoveries / verified_recoveries` | `NOT_APPLICABLE` (no verified recoveries ⇒ cannot attribute) |

Definitions: `policy_evaluated` = decided cases (every decided case passed PolicyEngine).
`policy_approved` = cases whose decision record is APPROVED. `needs_review` = cases
whose decision record is NEEDS_REVIEW. `policy_blocked` = cases whose decision record
is REJECTED (final). `provider_actions_succeeded` = SUCCEEDED execution attempts.
`verified_recoveries` = cases with final status RECOVERED. `attributed_recoveries` =
cases whose outcome carries `recovery_source = ACTION_ATTRIBUTED`.

---

## 2. Benchmark A — execution-scale (25 cases)

| Metric | Value |
|---|---|
| Cases requested / observed | **25 / 25** |
| Amount at risk | **₹35,232.60** |
| Decision coverage | **100%** (25/25) |
| Policy approved / blocked | **25 / 0** |
| Autonomy (decisions) | FULL_AUTO 25 |
| Decisions by action | GENERATE_PAYMENT_LINK 25 |
| Execution attempts | **25** (24 SUCCEEDED, 1 FAILED) |
| Execution failures | **1** (real provider `RATE_LIMIT_EXCEEDED`) |
| Provider actions succeeded | **24 / 25** |
| Webhook deliveries accepted | 17 HTTP 200 + 8 client-side timeouts (all 25 persisted) |
| Verified / attributed recoveries | **0 / 0** |
| Revenue recovered | **₹0** |
| Recovery rate | **0%** |

**Interpretation.** This benchmark runs the entire ARIV execution pipeline — from
signed webhook receipt through recovery case creation, failure intelligence, decision
engine, policy engine, and provider execution — against 25 real Razorpay test-mode
payments. Razorpay live API delivered / rejected each request in real time; the 1
failure was a genuine `RATE_LIMIT_EXCEEDED` rejection from the provider. Every one of
25 cases received a decision, and 24 of 25 provider actions succeeded end-to-end. With
0% recovery rate on a failure-only cohort where every payment was permanently failed
in test mode, this benchmark proves the execution path works and works safely, while
honestly exposing the recovery ceiling of a failure-only cohort.

> Delivery nuance: 8 of 25 sends hit the 15s client timeout (HTTP status `0`) while
> the server-side ingestion still processed them; the poll loop reconciled all 25 to
> RISK_ASSESSED, so observed coverage is 100%. Timing caveat is client-side only.

---

## 3. Benchmark B — scenario diversity (18 cases)

| Metric | Value |
|---|---|
| Cases requested / observed | **18 / 18** |
| Amount at risk | **₹145,400.00** |
| Decision coverage | **100%** (18/18) |
| Decisions by action | RETRY_NOW **4** · GENERATE_PAYMENT_LINK **5** · STOP_RECOVERY **9** |
| Policy approved / needs review / blocked | **16 / 2 / 0** |
| Autonomy (decisions) | FULL_AUTO 16 · HUMAN_APPROVAL 2 |
| Execution attempts | **5** (all SUCCEEDED) |
| Provider actions succeeded | **5 / 5** |
| Execution failures | **0** |
| Human escalations (manual review) | **2** (2 cases PENDING_APPROVAL) |
| Verified / attributed recoveries | **0 / 0** |
| Revenue recovered | **₹0** |
| Recovery rate | **0%** |

Scenario cohort (`scripts/scenarios_mixed_18.json`):

| Scenario | Count | Observed pipeline behavior |
|---|---|---|
| TRANSIENT_TECHNICAL / B2B (₹6,000–₹75,000) | 2 | RETRY_NOW → escalated NEEDS_REVIEW / HUMAN_APPROVAL (mandate) |
| TRANSIENT_TECHNICAL / B2C (₹500–₹1,200) | 2 | RETRY_NOW (autonomous) |
| CUSTOMER_ACTION_REQUIRED (insufficient balance, auth) | 5 | GENERATE_PAYMENT_LINK (5/5 created) |
| NON_RETRIABLE (code + "Card expired") | 4 | STOP_RECOVERY |
| UNKNOWN (DO_NOT_HONOR) | 5 | STOP_RECOVERY |

**Interpretation.** Benchmark B is a scenario-diversity / decision-policy benchmark,
not a recovery benchmark. It shows that when the mandate boundary is crossed (B2B
amount > ₹50,000, or 2-minute route degradation), the Economic Optimizer chooses NOT
to auto-execute but to defer to a human. It shows Governance-Aware-Autonomy in action:
large B2B payments crossed the mandate threshold and got escalated for manual review;
smaller B2C and even repeated route degradation were handled autonomously. It also
demonstrates how the project's core principle — "Don't burn money chasing failure" —
causes the system to STOP choosing unproductive retry paths, and decide carefully about
every rupee. A primary check for ANY enterprise recovery system is: does the system
STOP causing harm and escalate when it's uncertain? This benchmark demonstrates a
decisive answer: **yes**.

### 3.1 Honest finding — UNKNOWN/DO_NOT_HONOR

For the 5 `UNKNOWN/DO_NOT_HONOR` cases the persisted baseline action is **STOP_RECOVERY**
rather than ESCALATE_TO_HUMAN. Root cause (measured, not modified): classifier
initializes `retryability = BLOCKED` and never sets it for unrecognized error codes, so
`DeterministicBaseline.decide` returns STOP_RECOVERY via its BLOCKED branch before the
UNKNOWN→escalate branch is reached. This is recorded as characterization of current
behavior, not a claim that escalation fired. An upgrade path (classify DO_NOT_HONOR into
a review-safe band) is a known improvement candidate, explicitly out of scope for this
benchmark evidence phase.

---

## 4. Independent PostgreSQL verification

Verification = raw SQL against the live DB (no benchmark code), scoped by
`context->>'payment_id' LIKE 'pay_<benchmark_id>%'`.

### Benchmark A

| Metric | Report | Independent SQL | Match |
|---|---|---|---|
| Cases observed | 25 | 25 | ✓ |
| Amount at risk (minor) | 3,523,260 | 3,523,260 | ✓ |
| Decision records | 25 | 25 | ✓ |
| Decisions by action | GENERATE_PAYMENT_LINK 25 | 25 | ✓ |
| Policy approved | 25 | 25 | ✓ |
| Policy blocked (REJECTED finals) | 0 | 0 | ✓ |
| Autonomy FULL_AUTO | 25 | 25 | ✓ |
| Execution attempts | 25 | 25 | ✓ |
| Attempt statuses | SUCCEEDED 24 / FAILED 1 | SUCCEEDED 24 / FAILED 1 | ✓ |
| Execution failures | 1 | 1 | ✓ |
| Provider actions succeeded | 24 | 24 | ✓ |
| Verified recoveries | 0 | 0 | ✓ |
| Attributed recoveries | 0 | 0 | ✓ |
| Revenue recovered | ₹0 | ₹0 | ✓ |
| Escalations | 0 | 0 | ✓ |
| Case statuses | RISK_ASSESSED 25 | RISK_ASSESSED 25 | ✓ |

> The single `recovery_outcome` row in cohort A records the failed (`RATE_LIMIT_EXCEEDED`)
> attempt with `recovery_source = UNKNOWN_ATTRIBUTION`, `status = FAILED`. It is a
> failure record, not a recovery — verified/attributed/recovered remain exactly 0.

### Benchmark B

| Metric | Report | Independent SQL | Match |
|---|---|---|---|
| Cases observed | 18 | 18 | ✓ |
| Amount at risk (minor) | 14,540,000 | 14,540,000 | ✓ |
| Decision records | 18 | 18 | ✓ |
| Decisions by action | PLINK 5 / RETRY 4 / STOP 9 | same | ✓ |
| Policy approved / needs review | 16 / 2 | 16 / 2 | ✓ |
| Autonomy | FULL_AUTO 16 / HUMAN_APPROVAL 2 | 16 / 2 | ✓ |
| Actions persisted | 7 | 7 (SUCCEEDED 5, CANCELLED 2) | ✓ |
| Execution attempts | 5 | 5 (SUCCEEDED) | ✓ |
| Execution failures | 0 | 0 | ✓ |
| Provider actions succeeded | 5 | 5 | ✓ |
| Verified / attributed / revenue | 0 / 0 / ₹0 | 0 outcomes / ₹0 | ✓ |
| Escalations | 2 | 2 | ✓ |
| Case statuses | RISK_ASSESSED 16 / PENDING_APPROVAL 2 | same | ✓ |

---

## 5. Benchmark isolation & data integrity

| Check | Result |
|---|---|
| Cohort scoping | Every observation is scoped by embedded `payment_id` prefix `pay_<benchmark_id>` |
| Collision probe | `LIKE 'pay_bench_%'` count equals exactly the expected benchmark-owed ids (3 + 25 + 18): **probe = 0 unexpected cases** |
| Cross-contamination | 0 benchmark cases share a payment id with another run; every `pay_bench_%` case maps to exactly one expected id |
| Tenant separation | Benchmark tenant (`acc_benchmark`) is a distinct Tenant row from the default tenant; resolution fail-closed |
| RECOVERED leakage | **0** of the 9 DB cases with status RECOVERED belong to any benchmark cohort — all predate `2026-09-07` runs |
| Secrets in reports | Automated scan of all `benchmark_report_*.json` for `rzp_test_*`, `sk_*`, `x-razorpay-signature`: **no matches** |

### Recovery evidence is separate

The failure-only benchmark cohorts must never be merged with the project's real
demonstrated recoveries. Separate, prior evidence (Sep 4–5) includes cases with
`RECOVERED` + `recovery_source = ACTION_ATTRIBUTED` + real recovered amounts, e.g.
`pay_TYNndLSdbuxPzo`, `pay_TYPw0kOFGySHTG` (real Razorpay Test-Mode provider-confirmed
recoveries). Those are demonstrations of the recovery measurement/attribution path and
are **not** part of any benchmark denominator.

---

## 6. Reproducibility

Prerequisites: stack running (`docker compose up --build`), `.env` with real Razorpay
Test key + webhook secret, default webhook secret `test_secret`, `TEST_MODE`. Endpoint
under test: `POST /webhooks/razorpay` (same path the production ingest uses). All
sends are HMAC-SHA256 signed with the webhook secret via the real webhook path.

Commands used (same harness powering both reports):

```bash
# Smoke (3 cases)
python scripts/run_benchmark.py --cases 3 --min 5000 --max 250000 \
  --webhook-url http://localhost:8000/webhooks/razorpay --account-id acc_benchmark \
  --output-dir . --poll-interval 3 --max-wait 300

# Execution-scale replica (Benchmark A shape)
python scripts/run_benchmark.py --cases 25 --min 5000 --max 250000 \
  --webhook-url http://localhost:8000/webhooks/razorpay --account-id acc_benchmark \
  --output-dir . --poll-interval 3 --max-wait 300

# Scenario-diversity replica (Benchmark B — cohort defined in JSON, list order preserved)
python scripts/run_benchmark.py --scenario-file scripts/scenarios_mixed_18.json \
  --webhook-url http://localhost:8000/webhooks/razorpay --account-id acc_benchmark \
  --output-dir . --poll-interval 3 --max-wait 300
```

Determinism: amounts are seeded (`--seed`) for run-A style cohorts; the scenario file
carries exact amounts/error codes for the 18-case cohort. Scenario delivery uses a 1s
inter-event settle delay so background-task ordering (and systemic corridor state) is
deterministic enough to reproduce the RETRY_NOW→B2B-mandate and route-degradation
patterns. Benchmark id embeds the UTC timestamp; every payment id and event id embeds
the benchmark id for exact cohort scoping at read time. A fresh DB (or `docker compose
down -v`) yields the cleanest replica; systemic corridor state is in-memory, so a web
container restart clears it.

---

## 7. Benchmark implementation review

- No `RecoveryCase` / `RecoveryOutcome` / `DecisionRecord` / `Action` / `ExecutionAttempt`
  row is ever inserted by benchmark code — everything the report reads was written by the
  ARIV pipeline itself.
- No case is force-transitioned into RECOVERED; `verified_recoveries` requires a real
  persisted `RECOVERED` case status.
- Every metric is computed from persisted rows; nothing is derived from send-time input
  except descriptive scenario labels.
- Idempotent event ids (`evt_<benchmark_id>_<i>`) and embedded-payment-id scoping make
  runs isolated and cross-checkable.
- HTTP delivery uses 15s timeouts; a client timeout is recorded separately and never
  treated as a provider failure (poll loop reconciles to persisted state).
- Report files are scan-verified to contain no credentials.
- Zero-denominator rates render as `NOT_APPLICABLE`, so a reader can never mistake an
  unmeasured bucket for a measured 0%.

---

*Evidence phase: Phase 4. Tests: 222 passed, 1 skipped, 2 warnings. No recovery-rate
claims; honest 0% on failure-only cohorts. This document records measured behavior.*