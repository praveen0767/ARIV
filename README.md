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

**Detect failed payments → Diagnose → Reason → Rank → Authorize → Execute → Verify → Attribute → Measure**

**ARIV is an agentic revenue-recovery control plane for Razorpay.**

</div>

---

## 🏆 Buildathon Submission Summary

**Problem Solved:** Recover failed payments intelligently — not by blindly retrying everything.

### Key Claims

- ✅ **Real Razorpay Test API integration** — not mocked provider execution.
- ✅ **Deterministic financial safety** — AI proposes; `PolicyEngine` authorizes.
- ✅ **258/258 tests passing** — full stack reproducible locally.
- ✅ **Honest benchmarking** — 100% decision coverage, with **0% recovery explicitly reported for failure-only cohorts**.
- ✅ **Economic optimization** — systemic/route awareness + ENR ranking produced modeled improvement in the reported ablation.
- ✅ **Provider-confirmed recovery proof** — one separate end-to-end Test-Mode recovery was completed and attributed.

### Why ARIV is different

1. **Architecture trust:** Judgment and financial authority are separated.
2. **Honest metrics:** Recovery is counted only after provider confirmation and attribution.
3. **Production-oriented engineering:** PostgreSQL state, transactional outbox, worker leasing, idempotency, reconciliation, policy enforcement and comprehensive tests.

> **Agentic does not mean unrestricted authority over money.**  
> AI reasons and proposes. Deterministic systems authorize and execute.

---

## 💡 Executive Summary

Failed payments have different causes and therefore should not receive the same recovery action.

ARIV combines:

- **Failure Intelligence** for diagnosis.
- **Qdrant semantic memory** for contextual precedents.
- **Agentic AI** for structured recovery proposals.
- **Economic Optimizer** for Expected Net Recovery (`ENR`) ranking.
- **PolicyEngine** as the deterministic financial authorization boundary.
- **Transactional Outbox + Worker** for durable execution.
- **Razorpay Test APIs + Webhooks** for provider execution and truth.
- **Attribution + Measurement** to ensure recovered revenue is counted correctly.
- **Dashboard + Telegram + ASK ARIV** for operator visibility.

```text
AI proposes
    ↓
Economic logic ranks
    ↓
PolicyEngine authorizes
    ↓
Outbox + Worker executes
    ↓
Razorpay confirms
    ↓
Attribution verifies
    ↓
Revenue is measured


---

🧱 Technology Stack

Technology	Role

FastAPI	Backend APIs + webhook ingestion
PostgreSQL	Authoritative transactional state
Redis / BullMQ	Coordination + background processing
Qdrant	Semantic recovery memory
OpenAI-compatible LLM adapter	Context-aware reasoning
PolicyEngine	Deterministic financial authorization
Transactional Outbox	Durable side-effect boundary
Execution Worker	Idempotent background execution
Razorpay Test APIs	Real Test-Mode provider actions
Razorpay Webhooks	Provider event truth
Next.js / React	Operator dashboard
Docker Compose	Reproducible local environment



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

    classDef provider fill:#302A12,stroke:#E0B93F,color:#FFF4C2,stroke-width:2px;
    classDef ingestion fill:#14243B,stroke:#5B9BFF,color:#DCEBFF,stroke-width:2px;
    classDef case fill:#152B46,stroke:#6FA8FF,color:#E4F0FF,stroke-width:2px;
    classDef intelligence fill:#25203C,stroke:#9A87E8,color:#EEE9FF,stroke-width:2px;
    classDef memory fill:#3A2029,stroke:#E08AA5,color:#FFE8F0,stroke-width:2px;
    classDef agentic fill:#2B2142,stroke:#A88BE8,color:#F1E9FF,stroke-width:2px;
    classDef economics fill:#3D2E18,stroke:#D9A65A,color:#FFF0D2,stroke-width:2px;
    classDef policy fill:#163424,stroke:#68C28A,color:#DDF8E7,stroke-width:2.5px;
    classDef execution fill:#143532,stroke:#59BDB1,color:#D9F8F4,stroke-width:2px;
    classDef api fill:#182C49,stroke:#6598E8,color:#DFEAFF,stroke-width:2px;
    classDef reconciliation fill:#16382E,stroke:#65C69A,color:#DDF9EC,stroke-width:2px;
    classDef outcome fill:#183A23,stroke:#6BC982,color:#DDF9E2,stroke-width:2.5px;
    classDef measurement fill:#272344,stroke:#9889DE,color:#EEE9FF,stroke-width:2px;
    classDef operator fill:#292B30,stroke:#9298A5,color:#F0F2F5,stroke-width:2px;
    classDef redis fill:#431C1F,stroke:#E05A5A,color:#FFE3E3,stroke-width:2.5px;
    classDef stop fill:#431C1F,stroke:#E05A5A,color:#FFE3E3,stroke-width:2.5px;

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

> The architecture deliberately separates judgment, authorization, execution and provider truth. This is the core financial-safety property of ARIV.




---

🤖 Agentic AI

ARIV's AI layer:

Diagnoses failure context.

Retrieves relevant recovery precedents.

Evaluates candidate interventions.

Produces typed recovery proposals.

Explains decisions to operators.


The AI does not directly move money.

Failure
  ↓
Context + Memory
  ↓
Agentic AI
  ↓
Typed Proposal
  ↓
Economic Ranking
  ↓
PolicyEngine
  ↓
Execution

The model output is restricted to advisory fields. Authoritative financial, authorization and provider-truth fields cannot be supplied by the model.

Model confidence is not recovery probability.

Recovery probability and ENR are supplied by deterministic system components.


---

🧠 Qdrant Semantic Memory

ARIV uses Qdrant for tenant-scoped semantic recovery memory.

Prior cases and outcomes become contextual recovery knowledge.

Queries enforce tenant isolation.

Context-dependent vectors are used instead of meaningless zero vectors.

OpenAI semantic embeddings and deterministic hash fallback support reproducible operation.

Retrieved precedents are supplied to the decision context.



---

🛡️ Deterministic PolicyEngine

PolicyEngine is the financial safety boundary.

It validates:

Tenant limits.

Retry budgets.

Autonomy tier.

Action safety.

Systemic route health.

Candidate eligibility.


The economic optimizer ranks candidate actions using:

ENR = P × Amount − Cost − Risk

The AI cannot bypass the policy boundary.

If no candidate passes policy, ARIV executes:

STOP_RECOVERY

This prevents an AI-generated recommendation from becoming an unrestricted financial action.


---

🔒 Durable Execution

Approved actions enter a transactional outbox before side effects occur.

The worker provides:

Idempotent execution.

Worker leasing.

State-machine guards.

Optimistic locking.

Crash-safe processing.

Duplicate-event protection.


This protects the system against request crashes, duplicate webhooks and repeated execution attempts.


---

💳 Razorpay Integration

ARIV integrates with Razorpay Test Mode through the real provider flow.

Razorpay failure event
        ↓
Webhook verification
        ↓
Recovery Case
        ↓
ARIV decision
        ↓
Policy authorization
        ↓
Razorpay Test API
        ↓
Customer payment
        ↓
Razorpay confirmation
        ↓
Recovery Outcome

Webhook handling includes:

HMAC-SHA256 verification.

Deduplication.

Out-of-order event handling.

Provider reconciliation.

Correlation of successful payments with originating recovery actions.



---

📊 Verified Test-Mode Evidence

ARIV was exercised through real Razorpay Test-Mode execution.

Benchmark A — Execution-scale pipeline

25 cases · ₹35,232.60 at risk

Metric	Result

Cases decisioned	25 / 25 — 100%
Policy evaluations / approvals	25 / 25
Execution attempts	25
Provider payment-link actions completed	24 / 25
Real Razorpay failures	1
Verified recoveries	0
Attributed recoveries	0
Revenue recovered	₹0
Recovery rate	0%


Benchmark B — Scenario diversity

18 cases · ₹145,400.00 at risk

Metric	Result

Cases decisioned	18 / 18 — 100%
RETRY_NOW	4
GENERATE_PAYMENT_LINK	5
STOP_RECOVERY	9
Policy approved / needs review	16 / 2
FULL_AUTO / HUMAN_APPROVAL	16 / 2
Execution attempts	5
Provider actions completed	5 / 5
Execution failures	0
Human escalations	2
Verified recoveries	0
Attributed recoveries	0
Revenue recovered	₹0


⚠️ Why the benchmark recovery rate is 0%

These cohorts primarily exercised failure ingestion → decisioning → policy → execution.

They did not contain customers completing the generated recovery links.

Therefore:

Recovery link created ≠ Revenue recovered

ARIV deliberately reports 0 verified recoveries rather than treating an executed recovery action as revenue.

That distinction is intentional and is part of the measurement design.


---

✅ Real Provider-Confirmed Recovery

Separately from the failure-only benchmark cohorts, ARIV demonstrated a real Razorpay Test-Mode customer-completed recovery:

Payment failure
      ↓
ARIV Recovery Case
      ↓
Recovery decision
      ↓
Policy authorization
      ↓
Recovery action
      ↓
Customer payment
      ↓
Razorpay provider confirmation
      ↓
RECOVERED
      ↓
ACTION_ATTRIBUTED
      ↓
Measurement
      ↓
Telegram

This is presented as a single verified end-to-end demonstration, not inflated into a benchmark recovery rate.


---

🧮 Offline Ablation

The repository also contains an offline modeled ablation using:

10 seeds × 10,000 synthetic cases

The evaluation measures incremental strategy performance under a controlled synthetic environment.

Comparison	Finding

Economic vs Rules	Economic strategy wins
AI + Economic vs Economic	AI did not improve modeled net recovery
+ Qdrant Memory	Memory did not improve modeled net recovery
+ Systemic / Route Intelligence	Improved modeled result
Full Stack vs Economic	Full stack did not outperform Economic


These are modeled offline findings, not real-money causal claims.

The honest interpretation is that the deterministic economic layer currently carries the strongest measured financial optimization signal, while AI and memory provide contextual reasoning and operational capabilities whose modeled incremental recovery lift was not demonstrated in this ablation.

See:

artifacts/benchmarks/phase2_ablation_report.md


---

📈 Attribution & Measurement

ARIV keeps three concepts separate:

State	Meaning

Action succeeded	Recovery action was successfully created/executed
Provider confirmed	Razorpay reports the payment as successful
Attributed recovery	Successful payment is causally linked to the recovery action


Only the final state contributes to recovery revenue.

Action Success
      ≠
Payment Success
      ≠
Attributed Recovery

This prevents inflated recovery claims.


---

💬 ASK ARIV

ASK ARIV is an operator-facing conversational control layer.

It can provide grounded answers about:

Current recovery cases.

Decisions.

Policy outcomes.

Execution status.

Recovery outcomes.

Next actions.


It is a controlled operational interface over ARIV state, not an unrestricted autonomous financial agent.


---

🧪 Reliability & Engineering

ARIV explicitly addresses production-style failure modes:

Webhook verification and deduplication.

Out-of-order provider events.

Async background-session correctness.

Provider success-event reconciliation.

Tenant isolation.

Optimistic locking.

Durable outbox execution.

Worker leasing.

Idempotency.

State-machine transition guards.

Qdrant consistency.

Case-detail consistency.


The central invariant is:

AI cannot directly authorize money movement.


---

📸 Product Proof

The following screenshots document the actual product flow and operator experience.

Product Proof	Screenshot

🖥️ Command Center	docs/screenshots/01-command-center.png
❌ Failed Payment Case	docs/screenshots/02-failed-payment-case.png
🤖 AI Decision + Policy	docs/screenshots/03-ai-decision-policy.png
⚡ Recovery Action	docs/screenshots/04-recovery-action.png
💳 Razorpay Test Payment	docs/screenshots/05-razorpay-test-payment.png
✅ Recovered Attribution	docs/screenshots/06-recovered-attribution.png
📲 Telegram Recovery	docs/screenshots/07-telegram-recovery.png
💬 ASK ARIV	docs/screenshots/08-ask-ariv.png
🧠 Qdrant Memory	docs/screenshots/09-qdrant-memory.png
❤️ System Health	docs/screenshots/10-system-health.png
📊 Measurement	docs/screenshots/11-measurement.png



---

🎥 Product Walkthrough

ARIV product walkthrough:

https://www.youtube.com/watch?v=vkv6G-Nq67s

The walkthrough demonstrates the product flow from failed payment through decisioning, policy, execution, Razorpay integration, provider confirmation, attribution and measurement.


---

🚀 Run ARIV Locally

ARIV is designed to be reproducible locally with Docker Compose.

1. Fork

https://github.com/praveen0767/ARIV

Fork the repository to your GitHub account.

2. Clone

git clone https://github.com/<your-username>/ARIV.git
cd ARIV

3. Configure environment

cp .env.example .env

Configure your local values, including Razorpay Test Mode credentials and webhook configuration.

Required for the Razorpay Test-Mode flow:

Razorpay Test Key ID
Razorpay Test Key Secret
Webhook Secret
TEST_MODE

Telegram configuration is optional.

> Never commit .env, API keys, webhook secrets or Telegram tokens.



4. Start the stack

docker compose up -d --build

Check:

docker compose ps

Typical local endpoints:

Frontend → http://localhost:3000
Backend  → http://localhost:8000

5. Run tests

docker compose exec web pytest -q

Verified repository result:

258 passed
1 skipped
0 failed

6. Stop

docker compose down

For a fresh database:

docker compose down -v


---

🧪 Test-Mode Benchmark

The benchmark scripts exercise the existing ARIV ingestion and recovery pipeline using Razorpay Test Mode.

Execution-scale benchmark

python scripts/run_benchmark.py \
  --cases 25 \
  --min 5000 \
  --max 250000 \
  --webhook-url http://localhost:8000/webhooks/razorpay \
  --account-id acc_benchmark \
  --output-dir . \
  --poll-interval 3 \
  --max-wait 300

Scenario benchmark

python scripts/run_benchmark.py \
  --scenario-file scripts/scenarios_mixed_18.json \
  --webhook-url http://localhost:8000/webhooks/razorpay \
  --account-id acc_benchmark \
  --output-dir . \
  --poll-interval 3 \
  --max-wait 300

Reports are written as:

benchmark_report_<benchmark_id>.json

Offline strategy benchmarks:

python scripts/run_economic_benchmark.py --cases 5 --seed 42
python scripts/run_judge_benchmark.py

Detailed metric definitions and independent SQL verification:

docs/benchmark-results.md

Judge-facing summary:

docs/benchmark-summary.md


---

🧭 Recovery Philosophy

ARIV does not optimize for:

maximum retries

It optimizes for:

safe expected net recovery

A recovery action should happen only when:

The failure is actionable.

The candidate is economically justified.

Policy permits it.

The system can execute it safely.

Provider truth can later confirm the outcome.

Attribution can establish whether revenue was actually recovered.



---

🏆 Final Takeaway

ARIV is a revenue-recovery control plane, not simply an AI wrapper around Razorpay.

Its core design is:

JUDGMENT
              Agentic AI + Memory
                     ↓
              Economic Ranking
                     ↓
                 AUTHORITY
              PolicyEngine
                     ↓
                 EXECUTION
          Outbox + Worker + Adapter
                     ↓
                  TRUTH
           Razorpay Reconciliation
                     ↓
                MEASUREMENT
          Attribution + Revenue

The evidence is intentionally bounded:

258/258 tests pass.

Real Razorpay Test APIs are integrated.

25/25 and 18/18 benchmark cases reached decisioning.

Real provider execution was demonstrated.

One separate provider-confirmed recovery was demonstrated.

Failure-only cohorts correctly report 0% recovery rather than inventing revenue.

Offline ablation results are clearly labeled as modeled rather than causal.

AI and Qdrant are not falsely claimed to increase modeled recovery when the reported ablation did not show it.

Systemic/route intelligence did show modeled improvement.


The core engineering principle

> AI can recommend. Policy decides. Infrastructure executes. Razorpay confirms. Attribution proves.



Detect · Diagnose · Retrieve · Propose · Rank · Authorize · Execute · Verify · Attribute · Measure