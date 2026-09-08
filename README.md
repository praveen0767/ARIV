<div align="center">

<img src="./logo.png" alt="ARIV Logo" width="140"/>

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

ARIV is built to recover failed payments intelligently instead of blindly retrying them.

### Key Claims

- ✅ **Real Razorpay Test API integration** — provider execution is not mocked.
- ✅ **Deterministic financial safety** — AI proposes; `PolicyEngine` authorizes.
- ✅ **No single AI layer can independently move money.**
- ✅ **258 tests passing** across the implemented stack.
- ✅ **100% decision coverage** in both reported Test-Mode benchmark cohorts.
- ✅ **Honest recovery measurement** — benchmark cohorts report **0 verified recoveries** because no customer completed those generated recovery actions.
- ✅ **Economic optimization** through ENR ranking and systemic route intelligence.
- ✅ **Real provider-confirmed recovery** demonstrated separately in Razorpay Test Mode.

> **AI reasons. Economic logic ranks. PolicyEngine authorizes. Infrastructure executes. Razorpay confirms. Attribution measures.**

---

## 💡 What ARIV Does

A failed payment is not automatically a retry candidate.

ARIV asks:

```text
Why did the payment fail?
        ↓
Is recovery appropriate?
        ↓
Which action has the best expected value?
        ↓
Is that action allowed by policy?
        ↓
Can it execute safely?
        ↓
Did Razorpay confirm payment?
        ↓
Can the result be attributed to the recovery action?

Core pipeline:

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
Attribution + Measurement

Action execution is not treated as revenue recovery. Recovery revenue requires provider confirmation and attribution.


---

🏗️ Architecture

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

> Architectural boundary: judgment ≠ authority ≠ execution ≠ provider truth.



The integration layer is a typed capability boundary for controlled actions, not an unrestricted autonomous money-movement gateway.


---

🤖 Decisioning

ARIV separates reasoning from financial authorization and execution.

Layer	Responsibility

AI / Agentic	Diagnose, retrieve context, propose
Economic Optimizer	Rank candidate actions
PolicyEngine	Deterministic financial authorization
Outbox + Worker	Durable execution
Razorpay	Provider execution + confirmation
Attribution	Recovery linkage + measurement


ENR = P(recovery) × amount − cost − risk

AI confidence is not treated as recovery probability, and AI cannot bypass PolicyEngine.


---

🧪 Verified Test-Mode Evidence

Two benchmark cohorts exercised the real Razorpay Test APIs through ARIV's normal pipeline.

Benchmark A — Execution Scale

25 cases · ₹35,232.60 at risk

Metric	Result

Cases decisioned	25 / 25 (100%)
Policy evaluations / approvals	25 / 25
Execution attempts	25
Provider payment-link actions	24 / 25
Real Razorpay failures	1 (RATE_LIMIT_EXCEEDED)
Verified recoveries	0
Attributed recoveries	0
Revenue recovered	₹0
Recovery rate	0%


Benchmark B — Scenario Diversity

18 cases · ₹145,400 at risk

Metric	Result

Cases decisioned	18 / 18 (100%)
RETRY_NOW	4
GENERATE_PAYMENT_LINK	5
STOP_RECOVERY	9
Policy approved / review	16 / 2
FULL_AUTO / HUMAN_APPROVAL	16 / 2
Execution attempts	5
Provider actions completed	5 / 5
Execution failures	0
Human escalations	2
Verified recoveries	0
Attributed recoveries	0
Revenue recovered	₹0
Recovery rate	0%


Why 0% recovery?

These cohorts primarily exercised:

Failure
  ↓
Decision
  ↓
Policy
  ↓
Execution

They did not include customers completing the generated recovery links.

Therefore:

Action created ≠ Revenue recovered

ARIV reports 0 verified recoveries rather than converting executed actions into revenue claims.


---

✅ Real Provider-Confirmed Recovery

Separate from the benchmark denominators, ARIV demonstrated a customer-completed Razorpay Test-Mode recovery:

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

This is a separate provider-confirmed demonstration, not added to benchmark recovery totals.


---

🧮 Offline Ablation

An offline modeled ablation used 10 seeds × 10,000 synthetic cases.

Comparison	Result

Economic vs Rules	Economic strategy wins
AI + Economic vs Economic	AI did not improve modeled net recovery
+ Qdrant vs AI + Economic	Qdrant did not improve modeled net recovery
+ Systemic / Route Intelligence	Improved modeled result
Full Stack vs Economic	Full stack did not outperform Economic


> These are offline modeled findings, not real-money causal measurements.




---

📊 Attribution & Measurement

ARIV separates action execution, payment confirmation, and attributable recovery.

Action succeeded
      ↓
Provider confirms payment
      ↓
Recovery attributed

Only the final state contributes to recovery revenue.

Action Success
     ≠
Payment Success
     ≠
Attributed Recovery


---

📸 Product Proof

Stage	Screenshot	Proof

01		🖥️ Live command center + system state
02		💳 Failed payment → recovery case
03		🤖 AI proposal + policy boundary
04		⚙️ Governed recovery action
05		💳 Real Razorpay Test-Mode payment
06		✅ Provider-confirmed recovery + attribution
07		📲 Recovery notification
08		💬 Conversational operator control
09		🧠 Semantic recovery memory
10		❤️ Infrastructure health
11		📊 Recovery measurement



---

🔒 Reliability & Safety

Implemented safeguards include:

HMAC-SHA256 webhook verification

Duplicate and out-of-order provider-event handling

Durable ProviderEvent persistence

Tenant-isolated semantic retrieval

Deterministic PolicyEngine

Transactional Outbox

Worker leases + idempotent execution

Optimistic locking

Recovery state-machine guards

Provider reconciliation before attribution

Request-safe background database sessions

Deterministic fallback when the LLM is unavailable


Core invariant

AI proposes
    ↓
PolicyEngine authorizes
    ↓
Infrastructure executes
    ↓
Razorpay confirms
    ↓
Attribution measures

No single AI component can decide and independently move money.


---

💻 Technology Stack

Technology	Role

FastAPI	Backend APIs + webhook ingestion
PostgreSQL	Authoritative state
Redis / BullMQ	Coordination + background processing
Qdrant	Semantic recovery memory
LLM adapter	Context-aware reasoning
PolicyEngine	Deterministic financial authorization
Transactional Outbox	Durable side-effect boundary
Execution Worker	Background execution
Razorpay Test APIs	Provider Test-Mode execution
Razorpay Webhooks	Provider truth
Next.js / React	Operator interface
Docker Compose	Reproducible environment



---

🚀 Run Locally

Requirements

Docker + Docker Compose

Razorpay Test Mode credentials

Webhook secret

Optional Telegram credentials


Clone

git clone https://github.com/praveen0767/ARIV.git
cd ARIV

Configure

cp .env.example .env

Configure the Razorpay Test Mode credentials, webhook secret, and required local settings.

> Never commit .env, API keys, webhook secrets, or Telegram tokens.



Start

docker compose up -d --build
docker compose ps

Open:

Frontend → http://localhost:3000
Backend  → http://localhost:8000

Tests

docker compose exec web pytest -q

Verified:

258 passed
1 skipped
0 failed

Stop

docker compose down

Fresh database:

docker compose down -v


---

🧪 Benchmark Reproduction

The benchmark runner sends payment-failure webhook events through the application pipeline, varies amounts, waits for persisted processing, and computes metrics from the database.

python scripts/run_benchmark.py

Reports are written as:

benchmark_report_<benchmark_id>.json

The benchmark runner does not directly fabricate recovery outcomes, bypass policy, mutate historical records, or write benchmark results into the application UI.


---

📁 Repository Structure

ARIV/
├── app/
│   ├── api/
│   ├── agents/
│   ├── models/
│   ├── services/
│   ├── policies/
│   ├── workers/
│   └── integrations/
├── frontend/
├── scripts/
├── tests/
├── docs/
│   └── screenshots/
├── docker-compose.yml
├── Dockerfile
├── .env.example
└── README.md


---

🎥 Product Walkthrough

ARIV Product Demo

https://www.youtube.com/watch?v=vkv6G-Nq67s

Failure
  ↓
Diagnosis
  ↓
AI Decision
  ↓
Policy
  ↓
Recovery Action
  ↓
Razorpay
  ↓
Provider Confirmation
  ↓
Attribution
  ↓
Measurement


---

🏁 Engineering Takeaway

ARIV is built as a closed-loop recovery control plane, not an LLM wrapper around a retry API.

AI              → Reasons
Economic Layer  → Ranks
PolicyEngine    → Authorizes
Outbox + Worker → Executes
Razorpay        → Confirms
Attribution     → Measures

The evaluation deliberately distinguishes between action execution, provider-confirmed recovery, and offline modeled results. The system does not assume that adding more AI automatically produces more recovered revenue.

> AI can recommend. Policy decides. Infrastructure executes. Razorpay confirms. Attribution proves.



Detect · Diagnose · Retrieve · Propose · Rank · Authorize · Execute · Verify · Attribute · Measure