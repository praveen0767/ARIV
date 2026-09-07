# ARIV Benchmark Summary — Judge-Grade Evidence (real Razorpay Test Mode)

Two REAL test-mode benchmark runs against the live ARIV stack, independently verified
against PostgreSQL. Full tables and SQL verification: see
[docs/benchmark-results.md](benchmark-results.md).

1. **Execution Scale (Benchmark A, 25 cases, ₹35,232.60):** the entire recovery
   pipeline — signed webhook → case → failure intelligence → decision engine →
   policy engine → real Razorpay Test-Mode execution — ran end-to-end on 25 real
   payments with 100% decision coverage and 24/25 provider actions succeeding. The
   single failure was a genuine provider `RATE_LIMIT_EXCEEDED`. This proves the
   execution path works and works safely — it is an execution benchmark, not a
   recovery benchmark.

2. **Scenario Diversity (Benchmark B, 18 cases, ₹145,400):** across transient
   technical, customer-action-required, non-retriable, and unknown/DO_NOT_HONOR
   scenarios, the system produced 4 RETRY_NOW, 5 GENERATE_PAYMENT_LINK, and 9
   STOP_RECOVERY decisions; 5/5 real payment links created; zero execution
   failures; two B2B cases (> ₹50,000 mandate) escalated for human review. It
   demonstrates governance-aware autonomy and "don't burn money chasing failure."

3. **Safety & Governance:** crossing the B2B mandate boundary or 2-minute route
   degradation flips the Economic Optimizer from auto-execute to human-deferral.
   2 of 18 cases ended in PENDING_APPROVAL with HUMAN_APPROVAL autonomy; the system
   stops and asks for a human exactly when uncertain of large amounts.

4. **Integrity & Independence:** every metric is recomputed here from raw SQL over
   persisted pipeline rows (`pay_bench_<id>%` scoping) and matches the report
   files field-for-field. Zero cross-benchmark collisions; no benchmark case sits in
   RECOVERED; reports are scan-verified to contain no credentials; zero-denominator
   rates render as NOT_APPLICABLE, never a misleading 0%.

5. **Recovery Rate — honest, not fabricated:** both cohorts are failure-only
   (payments permanently failed in Test Mode), so the only honest recovery reading is
   **0%**. These runs make **no recovery-revenue claim**. Separate real demonstrated
   recoveries (`ACTION_ATTRIBUTED`, real recovered amount) exist from prior runs and
   are intentionally kept out of these benchmark denominators.