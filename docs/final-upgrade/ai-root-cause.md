# AI Negative Uplift — Root Cause Analysis

Status: **Phase 1 complete, evidence-backed.** Reproducible from the current source tree
(bit-for-bit, see `docs/final-upgrade/baseline.json`).

## 1. Observed failure mechanism

From the committed ablation (10 seeds × 10,000 cases = 100,000 cases per variant):

| Variant | Net (10 seeds) | Case rec. rate | vs previous | vs Economic |
|---|---|---|---|---|
| A0_BASELINE (rules) | ₹221,734,962.59 | 44.19% | — | −5.4% |
| A1_ECONOMIC | ₹234,413,917.40 | 46.69% | +5.7% | — |
| A2_AI_ECONOMIC | ₹230,486,294.80 | 45.91% | **−1.68% (0/10)** | −1.68% |
| A3_AI_ECONOMIC_MEMORY | ₹212,749,159.43 | 42.42% | **−7.70% (0/10)** | −9.24% |
| A4_FULL_ARIV | ₹230,694,194.23 | 45.94% | **+8.43% (10/10)** | −1.59% |

Full ARIV loses to plain Economic in every seed.

## 2. Evidence methodology

A replay harness (`scripts/diagnose_root_cause.py`) re-executed the **exact** ablation
decision functions per case and attributed every rupee of differential to
`(latent_incident, domain, is_systemic)` and to every action-switch from one variant to
the next. Decisions are bit-for-bit identical to the committed artifacts
(`root_cause_diagnostic.json` under `artifacts/benchmarks/final_upgrade/`).

## 3. Root causes (three distinct mechanisms)

### RC-1 — EMPLOYEE domain → unconditional ESCALATE_TO_HUMAN ("the ESCALATE trap")  [A2 vs A1]

`JudgeAIAdapter.generate_decision` (`scripts/run_judge_benchmark.py:112`) short-circuits on
`"EMPLOYEE" in prompt` and always returns `ESCALATE_TO_HUMAN`, ignoring `failure_category`.
`CandidateGenerator` (`app/services/candidate_generator.py`) then delegates the top-ranked slot
to the AI's recommendation. Because all candidates share the flat deterministic prior
(`ProbabilityProvider` returns 0.6 with no history), every ENR is identical and the **first**
listed candidate wins (`EconomicOptimizer.rank_candidates` stable-sort tie-break).

Consequence (data): for every non-retriable-non-engine case in the EMPLOYEE domain
(≈15,145 of 100k cases across seeds), A2 switches the recovering action to ESCALATE, whose
modeled conversion is **0.0** in the evaluator truth:

| bucket | A1 action (true conv) | A2 action (true conv) | A2 net |
|---|---|---|---|
| expired_card, EMPLOYEE (5,029) | SEND_REMINDER (0.50) | ESCALATE (0.0) | −₹75,435 (A1: +₹12.68M) |
| insufficient_funds, EMPLOYEE (5,106) | REQUEST (0.45) | ESCALATE (0.0) | −₹76,590 (A1: +₹11.57M) |
| transient_timeout, EMPLOYEE (5,010) | RETRY_LATER (0.85) | ESCALATE (0.0) | −₹75,150 (A1: +₹21.49M) |

Total ESCALATE-trap damage ≈ **−₹30.7M** over 100k cases.

Offsetting, genuinely correct AI behavior: switching GPL over REQUEST for insufficient funds
(+₹15.3M) and GPL over RETRY_LATER on systemic outages (+₹27.3M). Net A2 −₹3.93M (−1.68%).
The AI is not uniformly harmful; it has one classification defect that dominates its value.

### RC-2 — Memory precedents are corridor-blind and unsmoothed  [A3 vs A2]

The frozen public memory (`FROZEN_PUBLIC_MEMORY`) is keyed on `(domain, failure_category)`
only and injected as `historical_cases`. Two defects:

**(a) Corridor-blind probability boost.** For B2C+TRANSIENT_TECHNICAL the memory holds 5
RETRY_LATER precedents (4 recovered) ⇒ `ProbabilityProvider` returns the empirical 0.8. On the
10,173 systemic-outage B2C cases the corridor-aware pick is GENERATE_PAYMENT_LINK (true 0.70);
with memory, RETRY_LATER (0.8) out-ranks it and is chosen with true conversion **0.35**.
Result: A3 net drops ₹18.19M → ₹18.19M? No — A3 picks RETRY_LATER (0.35) ⇒ **−₹17.6M**
relative to A2 in that bucket alone.

**(b) STOP prior collapsed to 0 l by "failed" precedents.** For NON_RETRIABLE the memory holds
5 STOP precedents, all with outcome `FAILED`. `ProbabilityProvider` then returns empirical
p=0.0 for STOP, so STOP's ENR (−cost−risk) ranks below GENERATE_PAYMENT_LINK (prior 0.6) and
economic picks GPL. All 9,756 hard-fraud B2C cases flip to a futile (true conversion 0.0)
payment link: −₹97,560 and an unsafe intervention pattern. Survivorship error: STOP precedents
are *by construction* never "recovered" — a learner must never set p(STOP)=0 from them.

### RC-3 — A4's +8.43% is accidental tie-break rescue, not systemic value  [A4 vs A3]

`execute_ablation_variant_decision` records a signal for every case, and A4 uses the live
`SystemicIntelligenceService` buffer for `route_health`. Because systemic cases are ~20% of
the cohort, the buffer declares every corridor DEGRADED after warm-up. That forces the AI's
DEGRADED branch (GPL-first) onto B2B/EMPLOYEE corridors:

- EMPLOYEE: GPL is filtered (domain rule) ⇒ RETRY_LATER wins the ENR tie ⇒ **accidentally
  escapes RC-1** for 14,998 cases (+₹21.9M).
- B2B transient_timeout: AI-first tie-break picks GPL (true 0.45) over RETRY_LATER (true 0.85)
  ⇒ **−₹9.5M**.

The mechanism is ordering/luck, not route-aware economics.

### RC-4 — Ties collapse to candidate ordering ("informal AI authority")

All candidates share ENR `0.6·amount − 15` whenever there is no history, so ranking is purely
ordered by `CandidateGenerator` insertion order. AI recommendations are inserted first, which
hands the AI informal authority over the money decision — contradicting the "AI must not
directly determine economics" principle. Also on `NON_RETRIABLE` + memory (RC-2b) the ranking
falsely elevates GPL.

## 4. Causal hypotheses and severity

| # | Hypothesis | Evidence | Severity |
|---|---|---|---|
| RC-1 | EMPLOYEE→ESCALATE reflex ignores category; ESCALATE has 0 modeled payoff | 15,145 switched cases, duh −30.7M | High |
| RC-2a | Memory has no route/corridor context; boosts RETRY_LATER over route-aware GPL | 10,173 B2C systemic cases, −17.6M | High |
| RC-2b | Unsmoothed empirical probability collapses p(STOP)→0 | 9,756 fraud blocks flipped to GPL | High (safety) |
| RC-3 | Live-buffer DEGRADED corruption masks RC-1 via tie-break; hurts B2B | +21.9M/−9.5M net +8.43% | Medium |
| RC-4 | Uniform prior ⇒ ENR ties ⇒ candidate order decides | all buckets | High (structural) |

## 5. Proposed fixes (mapped to upgrade phases)

1. **(Phase 2)** Remove candidate-order authority: `EconomicOptimizer` must break ENR ties
   deterministically toward the *baseline/least-risk* action, never by AI insertion order.
   Keep the LLM strictly proposal-only; harden types so ENR/policy/authorization inputs are
   `ProbabilityProvider`- and `PolicyEngine`-owned.
2. **(Phase 3)** Replace the frozen-memory injection with a smoothing learner: probability =
   `(successes + α·prior) / (n + α)` (never 0); require minimum support before overriding the
   prior; keep STOP's probability floored by the prior; constrain updates to
   **provider-confirmed** outcomes only.
3. **(Phase 5)** Make route health an *input to the probability estimate* (degraded corridor
   discounts retry actions' ENR) instead of only a candidate filter and AI-prompt token.
4. **(Phase 4)** Give WAIT actions a real expected future value (transition matrix + costs +
   finite horizon) so RETRY_LATER / WAIT_UNTIL_WINDOW compete on economics, not ordering.

## 6. Expected invariant

After the fixes, on identical cohorts/seeds/truth with **unchanged ORIGINAL A1..A4 variants**:
- Original A1..A4 numbers must remain bit-for-bit unchanged (fixes are new variants/strategies).
- New variants (A5 = +learning, A6 = +wait, Phase 7 P4/P5) must **not** lose to Economic
  foreclosed by tie-order artifacts; economic authority must come from ENR with differentiated,
  route-aware, smoothed probabilities.
- No strategy may choose ESCALATE when a converting action is admissible, and no strategy may
  intervene on a terminal failure.

## 7. Test plan

- Phase 13 economic regression tests (10 scenarios) cover: high-cost/higher-p acting cautiously,
  ENR-ranking not tie-sorted, STOP when all ENR < 0, WAIT beating RETRY_NOW/STOP, degraded-route
  retry discounts, high-value strictness, irrelevant precedent cannot override deterministic
  evidence, AI cannot change final economics, policy rejection blocks execution, provider
  cancellation stops downstream attempts.
- Phase 2 adversarial tests prove manipulative LLM output cannot alter ENR, probability,
  authorization, or provider truth.
- Phase 8 matrix re-measures incremental value with fixed cohorts/seeds/truth and reports
  honestly (including possible "AI/economic still wins under X" outcomes in docs).