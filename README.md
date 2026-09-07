<div align="center">

<img src="./logo.png" alt="ARIV Logo" width="150"/>

# ARIV — Agentic Revenue Recovery for Razorpay

<img src="https://img.shields.io/badge/Razorpay-Test%20Mode-0f172a?style=for-the-badge" alt="Razorpay Test Mode"/>
<img src="https://img.shields.io/badge/FastAPI-Python-0f172a?style=for-the-badge&logo=fastapi" alt="FastAPI"/>
<img src="https://img.shields.io/badge/PostgreSQL-Database-0f172a?style=for-the-badge&logo=postgresql" alt="PostgreSQL"/>
<img src="https://img.shields.io/badge/Redis-Coordination-0f172a?style=for-the-badge&logo=redis" alt="Redis"/>
<img src="https://img.shields.io/badge/Qdrant-Semantic%20Memory-0f172a?style=for-the-badge" alt="Qdrant"/>
<img src="https://img.shields.io/badge/Docker-Compose-0f172a?style=for-the-badge&logo=docker" alt="Docker"/>
<img src="https://img.shields.io/badge/Next.js-React-0f172a?style=for-the-badge&logo=next.js" alt="Next.js"/>

</div>

**Agentic AI** reasons, retrieves context, diagnoses failures, and proposes recovery actions.
**Economic logic** ranks candidates.
**PolicyEngine** authorizes financial actions.
**Durable infrastructure** executes them.
**Razorpay provider events** establish truth.
**Attribution** determines recovered revenue.

*"Agentic" describes the reasoning/workflow layer — not unrestricted authority over money movement.*

**Detect a failed payment. Decide the best recovery. Authorize with deterministic policy. Execute safely. Verify provider truth. Attribute the revenue. Measure the outcome.**

ARIV is a recovery control plane for Razorpay that turns failed payments into governed, observable, measurable workflows.

## 💻 Technology at a Glance

| Technology | Role in ARIV |
|---|---|
| **FastAPI** | Async backend APIs and webhook endpoints |
| **PostgreSQL** | Authoritative transactional state |
| **Redis** | Coordination and deduplication |
| **Qdrant** | Semantic recovery memory |
| **LLM / OpenAI-compatible adapter** | Context-aware recovery reasoning |
| **PolicyEngine** | Deterministic financial authorization |
| **Transactional Outbox** | Durable side-effect boundary |
| **Execution Worker** | Idempotent background execution |
| **Razorpay Test APIs** | Provider-side Test Mode execution |
| **Razorpay Webhooks** | Provider-side event truth |
| **Next.js / React** | Operator control surface |
| **Docker Compose** | Reproducible local environment |

## Executive summary

Recovering failed payments is not about retrying everything. Real recovery requires deciding *which* failures are worth acting on, doing so within strict safety and financial controls, and only crediting revenue after the payment provider confirms it. ARIV implements that end-to-end loop for Razorpay and proves it with real Test-Mode execution evidence.

- **Decisioning**: failure classification + semantic memory + an agentic AI layer that *proposes* a typed recovery decision.
- **Ranking**: a deterministic economic optimizer ranks candidate actions by expected net recovery (ENR).
- **Safety**: a deterministic PolicyEngine is the only authority that authorizes money-movement actions.
- **Execution**: durable transactional outbox → worker → Razorpay adapter.
- **Truth**: provider webhooks are verified and reconciled; revenue is attributed only after provider confirmation.
- **Control**: operator dashboard, Telegram alerts, and a conversational "ASK ARIV" layer grounded in live system state.

```
AI proposes → Economic logic ranks → PolicyEngine authorizes → infrastructure executes → provider events establish truth
```

---

## ✅ Verified Test-Mode evidence

Two real test-mode benchmark runs exercised the **full execution pipeline** against Razorpay's real Test APIs: failure ingestion → decisioning → policy evaluation → provider execution. Everything below is recomputed from rows the pipeline persisted in PostgreSQL (see `docs/benchmark-results.md` for the independent SQL cross-check).

> **Reading this correctly:** these cohorts were *failure ingestion, decisioning, policy and execution* benchmarks. They did **not** include customers completing the generated recovery links, so verified-recovery and attributed-recovery are **zero**. This is honest — not a production performance claim.

### Benchmark A — Test-mode execution-scale pipeline benchmark
`benchmark_report_bench_20260907_041856_fa9508.json` · 25 cases · **₹35,232.60 at risk**

| Metric | Result |
|---|---|
| Cases decisioned | **25 / 25** (100%) |
| Policy evaluations / approvals | **25 / 25** |
| Execution attempts | **25** |
| Provider payment-link actions completed | **24 / 25** |
| Real Razorpay failures | **1** (`RATE_LIMIT_EXCEEDED`) |
| Verified recoveries | **0** |
| Attributed recoveries | **0** |
| Revenue recovered / recovery rate | **₹0 / 0%** |

### Benchmark B — Test-mode scenario-diversity / decision-policy benchmark
`benchmark_report_bench_20260907_045936_39bde5.json` · 18 cases · **₹145,400.00 at risk**

| Metric | Result |
|---|---|
| Cases decisioned | **18 / 18** (100%) |
| Decisions | RETRY_NOW **4** · GENERATE_PAYMENT_LINK **5** · STOP_RECOVERY **9** |
| Policy approved / needs review | **16 / 2** |
| Autonomy | FULL_AUTO **16** · HUMAN_APPROVAL **2** |
| Execution attempts / provider actions | **5 / 5** completed, **0** failures |
| Human escalations | **2** (B2B mandate + route-degradation cases) |
| Verified / attributed / revenue / recovery rate | **0 / 0 / ₹0 / 0%** |

### Real provider-confirmed recovery demonstration

Separately (not part of any benchmark denominator), ARIV demonstrated a real Razorpay Test-Mode, customer-completed recovery end-to-end:

```
payment failure → ARIV case → recovery decision → policy → recovery action
→ customer payment → Razorpay provider confirmation → RECOVERED
→ ACTION_ATTRIBUTED → measurement → Telegram
```

This is a single, real, provider-confirmed recovery demonstration — distinct from the failure-only benchmark cohorts above, which are intentionally kept out of recovery metrics.

---

## 🧮 What the ablation actually found

The repository's **offline, modeled ablation** (10 seeds × 10,000 synthetic cases, frozen Phase-1 baseline, common random numbers, held-out evaluator truth) measures each intelligence layer's incremental value.

> These are **modeled / offline ablation findings, not real-money causal measurements**. No layer is claimed to be empirically superior unless the reported ablation says so.

| Comparison | Result |
|---|---|
| Economic vs rules baseline | Economic strategy wins |
| AI + Economic vs Economic | AI layer did not improve modeled net recovery in the reported ablation |
| + Qdrant memory vs AI + Economic | Memory did not improve modeled net recovery in the reported ablation |
| + Systemic / route-aware layer | Improved the modeled result relative to the preceding variant |
| Full stack vs Economic | Full stack did not outperform Economic in the reported ablation |

Only the systemic / route-aware layer produced a modeled improvement over its immediate predecessor; the AI and memory layers did not. See `artifacts/benchmarks/phase2_ablation_report.md` for the full numbers.

---

## What problem ARIV solves

Payment failures are not a monolith:

- **Transient provider glitches** — a controlled retry may succeed.
- **Customer action required** — blocked card, missing OTP, needs a payment link.
- **Payment-method problems** — expired card, insufficient funds.
- **Non-retriable / risky** — fraud suspicion, degraded corridors.

Blindly retrying everything wastes attempts, hurts the customer, and increases risk. The business goal is **bounded, intelligently-selected, measurable recovery** — not maximum retries.

## 🔄 End-to-end recovery loop

```
Payment Failure
 → Detect (webhook → Recovery Case)
 → Diagnose (Failure Intelligence)
 → Retrieve context (tenant, history, Qdrant)
 → AI decision (typed proposal)
 → Economic ranking (ENR)
 → Policy check (deterministic approval)
 → Controlled execution (outbox → worker → Razorpay)
 → Provider confirmation (webhook reconciliation)
 → Attribution (action ↔ payment)
 → Measurement (recovered amount)
 → Operator visibility (dashboard + Telegram)
```

Each stage is observable and auditable. **Creating an action is not recovering revenue** — revenue is counted only after provider-confirmed, attributed payment.

## Architecture

```mermaid

flowchart TD
    RP[Razorpay Events] --> WH[Webhook Verification]
    WH --> PE[ProviderEvent Persistence]
    PE --> C[Recovery Case]

    C --> FI[Failure Intelligence]
    C --> SYS[Systemic Route Intelligence]

    SYS --> DC[Decision Context]
    FI --> DC

    DC --> Q[Qdrant Semantic Recovery Memory]
    Q --> DC

    DC --> AI[AI / Agentic Decision Engine]
    AI --> PROP[Typed Decision Proposal]
    PROP --> GEN[Candidate Generator]
    GEN --> ECON[Economic Optimizer]
    ECON --> POL[Deterministic PolicyEngine]

    POL -->|Approved| OUT[Transactional Outbox]
    POL -->|Rejected| STOP[STOP_RECOVERY]

    OUT --> WK[Execution Worker]
    WK --> AD[Razorpay Adapter]
    AD --> RPI[Razorpay API]

    RPI --> RECON[Provider Reconciliation]
    RECON --> OC[Recovery Outcome]

    OC --> ATTR[Recovery Attribution]
    OC --> MEAS[Recovery Measurement]

    MEAS --> TG[Telegram]
    MEAS --> UI[Operator Dashboard]
    UI --> ASK[ASK ARIV]
    ASK --> UI

    %% ========================================
    %% REDIS / QUEUE INFRASTRUCTURE
    %% ========================================

    REDIS[Redis + BullMQ] --> WK
    OUT --> REDIS

    %% ========================================
    %% DARK ARIV COLOR PALETTE
    %% ========================================

    %% Razorpay / External Provider
    classDef provider fill:#3B3518,stroke:#E0B93F,color:#FFF4C2,stroke-width:2px;

    %% Event Ingestion / Persistence
    classDef ingestion fill:#172B45,stroke:#5B9BFF,color:#DCEBFF,stroke-width:2px;

    %% Recovery Case
    classDef case fill:#162D49,stroke:#6FA8FF,color:#E4F0FF,stroke-width:2px;

    %% Intelligence Layer
    classDef intelligence fill:#292343,stroke:#9A87E8,color:#EEE9FF,stroke-width:2px;

    %% Qdrant Semantic Memory
    classDef memory fill:#452531,stroke:#E08AA5,color:#FFE8F0,stroke-width:2px;

    %% AI / Agentic Reasoning
    classDef agentic fill:#30244C,stroke:#A88BE8,color:#F1E9FF,stroke-width:2px;

    %% Decision / Economics
    classDef economics fill:#49371E,stroke:#D9A65A,color:#FFF0D2,stroke-width:2px;

    %% Deterministic Safety Boundary
    classDef policy fill:#193D2B,stroke:#68C28A,color:#DDF8E7,stroke-width:2.5px;

    %% Durable Execution
    classDef execution fill:#163D3A,stroke:#59BDB1,color:#D9F8F4,stroke-width:2px;

    %% External API
    classDef api fill:#1B3152,stroke:#6598E8,color:#DFEAFF,stroke-width:2px;

    %% Provider Reconciliation
    classDef reconciliation fill:#183D32,stroke:#65C69A,color:#DDF9EC,stroke-width:2px;

    %% Financial Outcome
    classDef outcome fill:#1B4228,stroke:#6BC982,color:#DDF9E2,stroke-width:2.5px;

    %% Attribution / Measurement
    classDef measurement fill:#2C2850,stroke:#9889DE,color:#EEE9FF,stroke-width:2px;

    %% Operator Visibility
    classDef operator fill:#303238,stroke:#9298A5,color:#F0F2F5,stroke-width:2px;

    %% RED #1 — Redis / BullMQ
    classDef redis fill:#4A2022,stroke:#E05A5A,color:#FFE3E3,stroke-width:2.5px;

    %% RED #2 — Recovery Safety Stop
    classDef stop fill:#4A2022,stroke:#E05A5A,color:#FFE3E3,stroke-width:2.5px;

    %% ========================================
    %% NODE COLOR ASSIGNMENTS
    %% ========================================

    class RP provider;

    class WH,PE ingestion;

    class C case;

    class FI,SYS,DC intelligence;

    class Q memory;

    class AI,PROP agentic;

    class GEN,ECON economics;

    class POL policy;

    class OUT,WK,AD execution;

    class RPI api;

    class RECON reconciliation;

    class OC outcome;

    class ATTR,MEAS measurement;

    class TG,UI,ASK operator;

    class REDIS redis;

    class STOP stop;
```

> The systems-integration box is a **typed capability / tool boundary**: a declared interface offering controlled, authorized actions to the decision and control layers — not a fully-fledged MCP server or an unrestricted agent-execution gateway.

## 🤖 Agentic AI Decision Layer

ARIV uses an **agentic reasoning layer** to:

- diagnose payment failures
- retrieve relevant recovery context
- evaluate candidate interventions
- produce structured recovery proposals
- explain decisions to operators

The agent does **not** authorize or directly execute financial actions.

```text
Agentic AI
    ↓
Proposal
    ↓
Economic Ranking
    ↓
PolicyEngine
    ↓
Execution
```

**AI is advisory:**

- AI **proposes structured decisions**; it does not author authoritative financial value.
- The model's payload is sanitized to advisory fields — financial, authorization, and provider-truth fields are stripped and never reach the economic/policy/execution layer.
- AI **cannot bypass PolicyEngine**.
- **Model confidence is not recovery probability** — probabilities and ENR come from the deterministic `ProbabilityProvider` and `EconomicOptimizer`.
- **Real LLM adapter** (OpenAI-compatible) with explicit timeouts; deterministic baseline fallback on failure — never bypassing policy.
- Produces a **structured, typed proposal**: diagnosis, recommended action, candidate actions, confidence (0.0–1.0), and an auditable reason.

## 🧠 Qdrant semantic memory

- **Contextual recovery memory**: tenant-scoped vector lookup of prior cases and their outcomes.
- **Context-dependent vectors** (no zero-vector), embedding abstraction (OpenAI semantic provider + deterministic hash fallback for offline/reproducible testing).
- Retrieved precedents are injected into the decision prompt; queries enforce tenant isolation.

## 🛡️ PolicyEngine / safety

The **PolicyEngine** is the deterministic financial firewall and the only authority that authorizes recovery actions:

- Validates safety, tenant limits, autonomy tier, retry budget, and systemic route health.
- **Order-neutral economic ranking**: ENR ties are resolved deterministically (baseline action first, then a fixed tier order) so the AI cannot steer a tie through candidate ordering.
- Iterates candidates in ENR order, rejecting risky ones, and executes `STOP_RECOVERY` when none pass.
- Cannot be bypassed by AI or route intelligence.
- Economic ranking uses **Expected Net Recovery** `ENR = P × amount − cost − risk`, with probability from empirical history when available (else a stated deterministic prior).

Approved actions are written to a **transactional outbox** before any side effect; the execution worker leases, idempotently executes, and guards state transitions.

## 🔒 Durable execution

Outbox + worker protects against model-driven arbitrary calls, policy bypass, duplicate side effects, and request-lifetime crashes. Optimistic locking and hardened ORM handling preserve concurrency correctness.

## Razorpay integration & provider truth

- HMAC-SHA256 webhook verification and deduplication; out-of-order and duplicate events handled.
- Razorpay **Test APIs** create payment links; execution waits for the async `payment_link.paid` event.
- **Provider reconciliation** correlates the success event to the originating action so attribution reflects provider truth.

## 📊 Attribution & measurement

Three distinct states:

1. **Action succeeded** — the link was created.
2. **Provider-confirmed payment** — Razorpay reports `PAID`.
3. **Attributed recovery** — the payment is linked to the recovery action (`ACTION_ATTRIBUTED`).

Only state 3 contributes to recovery revenue. Measurement values are estimates; causal lift is not claimed without controlled experiments.

## 💬 ASK ARIV

A conversational **operational control layer** grounded in actual ARIV state — it answers questions about live cases, decisions, policy outcomes, and next steps. It is a grounded routing/tool surface over real system data, **not** a general-purpose autonomous agent.

---

## 🛠️ Reliability & engineering invariants

Genuinely-solved engineering problems:

- **Expired webhook tunnel** — re-verifies the registered provider endpoint automatically.
- **Request-scoped async session in background processing** — fresh session per background task.
- **Provider success-event processing** — correlates success to the original action before attribution.
- **Concurrency / stale ORM state** — optimistic locking + hardened ORM handling.
- **Tenant isolation hardening** — fail-closed tenant resolution.
- **Provider reconciliation correctness** — verified, deduplicated, out-of-order-safe.
- **Outbox / execution reliability** — idempotency, leases, state-machine guards.
- **Case-detail endpoint & Qdrant consistency.**

## 🏗️ Technical decision — why this architecture is trustworthy

ARIV deliberately separates *judgment* from *authority*:

| Layer | Role | Trust property |
|---|---|---|
| Agentic AI layer | Reason, retrieve, propose | Cannot trigger money movement alone |
| PolicyEngine | Authorize | Deterministic, auditable, non-bypassable |
| Outbox + worker | Execute durably | Idempotent, crash-safe |
| Provider reconciliation | Confirm truth | Only provider confirmation counts |
| Attribution + measurement | Count revenue | Prevents false recovery claims |

**No single component can both decide on money and move it.** That separation is the core safety property.

---

## 🚀 Local reproduction

You can fork ARIV, clone your fork, configure Razorpay Test Mode, and run the complete local stack with Docker Compose.

### 1. Fork

Open:

**https://github.com/praveen0767/ARIV**

Click **Fork** and create your own copy.

### 2. Clone

```bash
git clone https://github.com/<your-username>/ARIV.git
cd ARIV
```

### 3. Configure environment

```bash
cp .env.example .env
```

Fill in the required local environment values. For the complete Razorpay Test Mode flow you need:

- **Razorpay Test Mode credentials**
- **webhook secret**
- **`TEST_MODE`**

Telegram configuration is optional and only needed for Telegram notifications.

> **Never commit `.env`, API keys, webhook secrets, Telegram tokens, or other credentials.**

### 4. Start ARIV

```bash
docker compose up -d --build
```

Then:

```bash
docker compose ps
```

- Frontend: [http://localhost:3000](http://localhost:3000)
- Backend API: [http://localhost:8000](http://localhost:8000)

### 5. Verify installation

```bash
docker compose exec web pytest -q
```

**Current verified result: 258 passed · 1 skipped · 0 failed · 2 warnings.** (The 2 warnings are known pre-existing runtime warnings in a tenant-bootstrap test, not failures.)

### 6. Run ARIV

The lifecycle is:

```
Payment Failure
 → Webhook Ingestion
 → Recovery Case
 → Failure Intelligence
 → AI Proposal
 → Economic Ranking
 → PolicyEngine
 → Durable Execution
 → Razorpay Test Action
 → Provider Confirmation
 → Recovery Attribution
 → Measurement
```

### 7. Reproduce the Test Mode benchmarks

Run the verified test-mode pipeline benchmarks:

```bash
# Execution-scale (25 cases) — run from the repo root
python scripts/run_benchmark.py --cases 25 --min 5000 --max 250000 \
  --webhook-url http://localhost:8000/webhooks/razorpay \
  --account-id acc_benchmark --output-dir . --poll-interval 3 --max-wait 300

# Scenario-diversity (18-case cohort defined in JSON, order preserved)
python scripts/run_benchmark.py --scenario-file scripts/scenarios_mixed_18.json \
  --webhook-url http://localhost:8000/webhooks/razorpay \
  --account-id acc_benchmark --output-dir . --poll-interval 3 --max-wait 300
```

The synthetic economic/judge harnesses remain available for offline strategy comparison:

```bash
python scripts/run_economic_benchmark.py --cases 5 --seed 42
python scripts/run_judge_benchmark.py
```

Full metric definitions, formulas, zero-denominator handling, and independent SQL verification: [docs/benchmark-results.md](docs/benchmark-results.md). Judge-facing summary: [docs/benchmark-summary.md](docs/benchmark-summary.md).

### 8. Stop the environment

```bash
docker compose down
```

To also remove volumes (fresh database):

```bash
docker compose down -v
```

---

## 🧪 Tests

```bash
docker compose exec web pytest -q
```

**Current verified result: 258 passed · 1 skipped · 0 failed · 2 warnings.** (Run on 2026-09-07.) The 2 warnings are known pre-existing runtime warnings in a tenant-bootstrap test, not failures.

---

## 📸 Screenshots

| | |
|---|---|
| Command center | ![](docs/screenshots/01-command-center.png) |
| Failed-payment case | ![](docs/screenshots/02-failed-payment-case.png) |
| AI decision + policy | ![](docs/screenshots/03-ai-decision-policy.png) |
| Recovery action | ![](docs/screenshots/04-recovery-action.png) |
| Razorpay test payment | ![](docs/screenshots/05-razorpay-test-payment.png) |
| Recovered attribution | ![](docs/screenshots/06-recovered-attribution.png) |
| Telegram recovery | ![](docs/screenshots/07-telegram-recovery.png) |
| ASK ARIV | ![](docs/screenshots/08-ask-ariv.png) |
| Qdrant memory | ![](docs/screenshots/09-qdrant-memory.png) |
| System health | ![](docs/screenshots/10-system-health.png) |
| Measurement | ![](docs/screenshots/11-measurement.png) |

---

## 🎥 Product Walkthrough

A concise walkthrough of the ARIV recovery workflow: decisioning, policy enforcement, Razorpay integration, execution, provider confirmation, attribution, measurement, and operator experience.

**▶ Watching the full product walkthrough is recommended:** [ARIV on YouTube](https://www.youtube.com/watch?v=vkv6G-Nq67s)

---


## ✅ Final takeaway

ARIV is a **recovery control plane**. Agentic AI proposes, PolicyEngine authorizes, durable infrastructure executes, Razorpay establishes provider truth, and attribution determines recovered revenue. Its evidence is bounded and honest: execution-scale and scenario-diversity benchmarks prove the pipeline works, the offline ablation shows which layers add value and which do not, the zero-recovery reading on failure-only cohorts makes no false claim, and the separately demonstrated provider-confirmed recovery shows what is proven and what is claimed.

**Detect · Diagnose · Retrieve · Propose · Rank · Authorize · Execute · Verify · Attribute · Measure**
