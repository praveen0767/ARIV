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

**Detect → Diagnose → Propose → Rank → Authorize → Execute → Verify → Attribute → Measure**

**ARIV is an agentic revenue-recovery control plane for Razorpay.**

</div>

---

## 🏆 Buildathon Submission Summary

**Problem:** Recover failed payments intelligently instead of blindly retrying everything.

### Key Claims

- ✅ **Real Razorpay Test API integration** — provider execution is not mocked.
- ✅ **Deterministic safety boundary** — AI proposes; `PolicyEngine` authorizes.
- ✅ **258/258 tests passing** — full stack reproducible with Docker Compose.
- ✅ **100% decision coverage** in both reported Test-Mode benchmark cohorts.
- ✅ **Honest recovery measurement** — failure-only cohorts correctly report **0 verified recoveries**.
- ✅ **Economic optimization** — ENR ranking + systemic route intelligence.
- ✅ **Real provider-confirmed recovery** — demonstrated separately in Razorpay Test Mode.

> **AI reasons. Economic logic ranks. PolicyEngine authorizes. Infrastructure executes. Razorpay confirms. Attribution measures.**

---

## 💡 Core Flow

```text
Razorpay Failure
      ↓
Webhook Verification
      ↓
ProviderEvent Persistence
      ↓
Recovery Case
      ↓
Failure + Systemic Route Intelligence
      ↓
Decision Context + Qdrant Memory
      ↓
AI / Agentic Proposal
      ↓
Candidate Generation
      ↓
Economic Optimization (ENR)
      ↓
Deterministic PolicyEngine
      ↓
Transactional Outbox
      ↓
Execution Worker
      ↓
Razorpay
      ↓
Provider Reconciliation
      ↓
Recovery Outcome
      ↓
Attribution
      ↓
Measurement
```

**Action success is not recovery.**  
Recovery revenue is counted only after provider-confirmed payment and attribution.

---

## 🏗️ Architecture

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

    REDIS[Redis + BullMQ] --> WK
    OUT --> REDIS

    classDef provider fill:#3B3518,stroke:#E0B93F,color:#FFF4C2,stroke-width:2px;
    classDef ingestion fill:#172B45,stroke:#5B9BFF,color:#DCEBFF,stroke-width:2px;
    classDef case fill:#162D49,stroke:#6FA8FF,color:#E4F0FF,stroke-width:2px;
    classDef intelligence fill:#292343,stroke:#9A87E8,color:#EEE9FF,stroke-width:2px;
    classDef memory fill:#452531,stroke:#E08AA5,color:#FFE8F0,stroke-width:2px;
    classDef agentic fill:#30244C,stroke:#A88BE8,color:#F1E9FF,stroke-width:2px;
    classDef economics fill:#49371E,stroke:#D9A65A,color:#FFF0D2,stroke-width:2px;
    classDef policy fill:#193D2B,stroke:#68C28A,color:#DDF8E7,stroke-width:2.5px;
    classDef execution fill:#163D3A,stroke:#59BDB1,color:#D9F8F4,stroke-width:2px;
    classDef api fill:#1B3152,stroke:#6598E8,color:#DFEAFF,stroke-width:2px;
    classDef reconciliation fill:#183D32,stroke:#65C69A,color:#DDF9EC,stroke-width:2px;
    classDef outcome fill:#1B4228,stroke:#6BC982,color:#DDF9E2,stroke-width:2.5px;
    classDef measurement fill:#2C2850,stroke:#9889DE,color:#EEE9FF,stroke-width:2px;
    classDef operator fill:#303238,stroke:#9298A5,color:#F0F2F5,stroke-width:2px;
    classDef redis fill:#4A2022,stroke:#E05A5A,color:#FFE3E3,stroke-width:2.5px;
    classDef stop fill:#4A2022,stroke:#E05A5A,color:#FFE3E3,stroke-width:2.5px;

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

> The key architectural boundary is **judgment ≠ authority ≠ execution ≠ provider truth**.

---

## 🤖 Decisioning

ARIV separates the responsibilities deliberately:

| Layer | Responsibility |
|---|---|
| **AI / Agentic layer** | Diagnose, retrieve context, propose |
| **Economic Optimizer** | Rank candidates using ENR |
| **PolicyEngine** | Deterministic authorization |
| **Outbox + Worker** | Durable execution |
| **Razorpay** | Provider-side execution + truth |
| **Attribution** | Establish recovery linkage |

```text
ENR = P(recovery) × amount − cost − risk
```

AI confidence is **not** treated as recovery probability, and AI cannot bypass `PolicyEngine`.

---

## 🧪 Verified Test-Mode Benchmarks

Two real Test-Mode benchmark runs exercised the pipeline against Razorpay Test APIs.

### Benchmark A

**25 cases · ₹35,232.60 at risk**

| Metric | Result |
|---|---:|
| Decisioned | **25 / 25 (100%)** |
| Policy evaluations / approvals | **25 / 25** |
| Execution attempts | **25** |
| Provider payment-link actions | **24 / 25** |
| Real Razorpay failures | **1** (`RATE_LIMIT_EXCEEDED`) |
| Verified recoveries | **0** |
| Attributed recoveries | **0** |
| Revenue recovered | **₹0** |
| Recovery rate | **0%** |

### Benchmark B

**18 cases · ₹145,400 at risk**

| Metric | Result |
|---|---:|
| Decisioned | **18 / 18 (100%)** |
| `RETRY_NOW` | **4** |
| `GENERATE_PAYMENT_LINK` | **5** |
| `STOP_RECOVERY` | **9** |
| Policy approved / review | **16 / 2** |
| `FULL_AUTO` / `HUMAN_APPROVAL` | **16 / 2** |
| Execution attempts | **5** |
| Provider actions completed | **5 / 5** |
| Execution failures | **0** |
| Human escalations | **2** |
| Verified recoveries | **0** |
| Attributed recoveries | **0** |
| Revenue recovered | **₹0** |
| Recovery rate | **0%** |

### Why 0% recovery?

These cohorts tested:

```text
Failure → Decision → Policy → Execution
```

They did **not** contain customers completing the generated recovery links.

Therefore:

```text
Action created ≠ Revenue recovered
```

ARIV intentionally reports **0** rather than inventing a recovery rate.

---

## ✅ Separate Real Provider-Confirmed Recovery

Outside the benchmark denominators, ARIV demonstrated a real Razorpay Test-Mode customer-completed recovery:

```text
Payment Failure
      ↓
Recovery Case
      ↓
Recovery Decision
      ↓
Policy Approval
      ↓
Recovery Action
      ↓
Customer Payment
      ↓
Razorpay Confirmation
      ↓
RECOVERED
      ↓
ACTION_ATTRIBUTED
      ↓
Measurement
      ↓
Telegram
```

This is a **separate provider-confirmed demonstration**, not added to the benchmark recovery totals.

---

## 🧮 Offline Ablation

The reported offline modeled ablation uses **10 seeds × 10,000 synthetic cases**.

| Comparison | Result |
|---|---|
| Economic vs Rules | **Economic strategy wins** |
| AI + Economic vs Economic | AI did **not** improve modeled net recovery |
| + Qdrant vs AI + Economic | Qdrant did **not** improve modeled net recovery |
| + Systemic / Route Intelligence | **Improved modeled result** |
| Full Stack vs Economic | Full stack did **not** outperform Economic |

> These are **offline modeled findings**, not real-money causal measurements.

The result is intentionally disclosed: deterministic economic optimization and systemic route intelligence produced the reported modeled gains, while AI and Qdrant did not show incremental modeled recovery improvement in this ablation.

---

## 📊 Attribution & Measurement

ARIV keeps these states separate:

```text
Action succeeded
      ↓
Provider confirmed payment
      ↓
Attributed recovery
```

Only the final state contributes to recovery revenue.

```text
Action Success
      ≠
Payment Success
      ≠
Attributed Recovery
```

No causal lift is claimed without controlled experiments.

---

## 📸 Product Proof

The screenshots are arranged around the actual product story:

| Stage | Screenshot | Proof |
|---|---|---|
| 01 | ![Command Center](docs/screenshots/01-command-center.png) | 🖥️ Command center + live system state |
| 02 | ![Failed Payment](docs/screenshots/02-failed-payment-case.png) | 💳 Failed payment → recovery case |
| 03 | ![AI Decision + Policy](docs/screenshots/03-ai-decision-policy.png) | 🤖 AI proposal + PolicyEngine boundary |
| 04 | ![Recovery Action](docs/screenshots/04-recovery-action.png) | ⚙️ Governed recovery action |
| 05 | ![Razorpay Test Payment](docs/screenshots/05-razorpay-test-payment.png) | 💳 Real Razorpay Test-Mode payment |
| 06 | ![Recovered Attribution](docs/screenshots/06-recovered-attribution.png) | ✅ Provider-confirmed recovery + attribution |
| 07 | ![Telegram Recovery](docs/screenshots/07-telegram-recovery.png) | 📲 Recovery notification |
| 08 | ![ASK ARIV](docs/screenshots/08-ask-ariv.png) | 💬 Conversational operator control |
| 09 | ![Qdrant Memory](docs/screenshots/09-qdrant-memory.png) | 🧠 Semantic recovery memory |
| 10 | ![System Health](docs/screenshots/10-system-health.png) | ❤️ Infrastructure health |
| 11 | ![Measurement](docs/screenshots/11-measurement.png) | 📊 Recovery measurement |

### Screenshot Story

```text
01 Command Center
      ↓
02 Failed Payment
      ↓
03 AI Decision + Policy
      ↓
04 Recovery Action
      ↓
05 Razorpay Test Payment
      ↓
06 Recovered + Attributed
      ↓
07 Telegram Confirmation
      ↓
08 ASK ARIV
      ↓
09 Qdrant Memory
      ↓
10 System Health
      ↓
11 Measurement
```

---

## 🛡️ Safety & Reliability

Key engineering safeguards:

- HMAC-SHA256 webhook verification.
- Duplicate and out-of-order event handling.
- Durable `ProviderEvent` persistence.
- Tenant-isolated Qdrant retrieval.
- Deterministic `PolicyEngine`.
- Transactional Outbox.
- Worker leases and idempotent execution.
- Optimistic locking.
- State-machine guards.
- Provider reconciliation before attribution.
- Request-safe background database sessions.
- Deterministic fallback when the LLM is unavailable.

### Core invariant

```text
AI proposes
    ↓
PolicyEngine authorizes
    ↓
Infrastructure executes
    ↓
Razorpay confirms
    ↓
Attribution measures
```

**No single AI component can decide and independently move money.**

---

## 🚀 Run Locally

### Requirements

- Docker + Docker Compose
- Razorpay Test Mode credentials
- Webhook secret
- Optional Telegram credentials

### Clone

```bash
git clone https://github.com/praveen0767/ARIV.git
cd ARIV
```

### Configure

```bash
cp .env.example .env
```

Configure Razorpay Test Mode credentials, webhook secret and required local variables.

> Never commit `.env`, API keys, webhook secrets or Telegram tokens.

### Start

```bash
docker compose up -d --build
```

Check:

```bash
docker compose ps
```

Open:

```text
Frontend → http://localhost:3000
Backend  → http://localhost:8000
```

### Test

```bash
docker compose exec web pytest -q
```

Current verified result:

```text
258 passed
1 skipped
0 failed
2 warnings
```

### Stop

```bash
docker compose down
```

Fresh database:

```bash
docker compose down -v
```

---

## 🧪 Reproduce the Benchmarks

### 25-case execution benchmark

```bash
python scripts/run_benchmark.py \
  --cases 25 \
  --min 5000 \
  --max 250000 \
  --webhook-url http://localhost:8000/webhooks/razorpay \
  --account-id acc_benchmark \
  --output-dir . \
  --poll-interval 3 \
  --max-wait 300
```

### 18-case scenario benchmark

```bash
python scripts/run_benchmark.py \
  --scenario-file scripts/scenarios_mixed_18.json \
  --webhook-url http://localhost:8000/webhooks/razorpay \
  --account-id acc_benchmark \
  --output-dir . \
  --poll-interval 3 \
  --max-wait 300
```

### Offline benchmarks

```bash
python scripts/run_economic_benchmark.py --cases 5 --seed 42
python scripts/run_judge_benchmark.py
```

Detailed benchmark documentation:

```text
docs/benchmark-results.md
docs/benchmark-summary.md
artifacts/benchmarks/phase2_ablation_report.md
```

---

## 🎥 Product Walkthrough

**ARIV Product Demo**

https://www.youtube.com/watch?v=vkv6G-Nq67s

The walkthrough follows:

```text
Failure
→ Diagnosis
→ AI Decision
→ Policy
→ Recovery Action
→ Razorpay
→ Confirmation
→ Attribution
→ Measurement
```

---

## 🏁 Final Takeaway

ARIV is **not simply an AI retry tool**.

It is a governed recovery control plane:

```text
                    AI
                 PROPOSES
                    ↓
              ECONOMIC LOGIC
                  RANKS
                    ↓
             POLICYENGINE
                AUTHORIZES
                    ↓
          OUTBOX + WORKER
                EXECUTES
                    ↓
               RAZORPAY
                 CONFIRMS
                    ↓
             ATTRIBUTION
                 PROVES
                    ↓
              MEASUREMENT
                  COUNTS
```

The evidence is deliberately bounded:

- ✅ **258/258 tests pass**
- ✅ **Real Razorpay Test APIs**
- ✅ **25/25 and 18/18 decision coverage**
- ✅ **Real provider execution**
- ✅ **Separate provider-confirmed recovery**
- ✅ **Honest 0% recovery for failure-only cohorts**
- ✅ **Offline ablation with transparent results**
- ✅ **Systemic / route intelligence showed modeled improvement**
- ✅ **No unsupported causal-lift claim**

> **AI can recommend. Policy decides. Infrastructure executes. Razorpay confirms. Attribution proves.**

**Detect · Diagnose · Retrieve · Propose · Rank · Authorize · Execute · Verify · Attribute · Measure**