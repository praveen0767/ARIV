<div align="center">

<img src="./logo.png" alt="ARIV Logo" width="150"/>

# ARIV

### AI-Assisted Revenue Recovery Control Plane for Razorpay

**Detect failed payments → Diagnose → Rank recovery actions economically → Enforce policy → Execute safely → Verify provider truth → Attribute revenue → Measure outcomes**

<br/>

<img src="https://img.shields.io/badge/Razorpay-Test%20Mode-0f172a?style=for-the-badge" alt="Razorpay Test Mode"/>
<img src="https://img.shields.io/badge/FastAPI-Python-0f172a?style=for-the-badge&logo=fastapi" alt="FastAPI"/>
<img src="https://img.shields.io/badge/PostgreSQL-Database-0f172a?style=for-the-badge&logo=postgresql" alt="PostgreSQL"/>
<img src="https://img.shields.io/badge/Redis-Coordination-0f172a?style=for-the-badge&logo=redis" alt="Redis"/>
<img src="https://img.shields.io/badge/Qdrant-Semantic%20Memory-0f172a?style=for-the-badge" alt="Qdrant"/>
<img src="https://img.shields.io/badge/Docker-Compose-0f172a?style=for-the-badge&logo=docker" alt="Docker"/>

<br/><br/>

**AI reasons and proposes.**  
**Economic logic ranks.**  
**PolicyEngine authorizes.**  
**Infrastructure executes.**  
**Provider events establish truth.**

</div>

---

# 🎥 Product Walkthrough

### Live ARIV product explanation

This walkthrough demonstrates the ARIV product, recovery workflow, decisioning, policy enforcement, Razorpay integration, execution flow, recovery attribution, measurement, and operator experience.

[![ARIV Product Walkthrough](https://img.youtube.com/vi/vkv6G-Nq67s/maxresdefault.jpg)](https://www.youtube.com/watch?v=vkv6G-Nq67s)

**▶ Watch the full product walkthrough:**  
https://www.youtube.com/watch?v=vkv6G-Nq67s

---

# ⚡ What is ARIV?

ARIV is a **recovery control plane for Razorpay** that turns failed payments into governed, observable, and measurable workflows.

It is built around a simple principle:

> **Recover revenue intelligently without turning financial execution into an unrestricted AI problem.**

ARIV combines:

- Failure intelligence
- Contextual recovery memory
- AI-assisted decision proposals
- Economic action ranking
- Deterministic policy enforcement
- Durable execution
- Razorpay Test API integration
- Webhook verification
- Provider reconciliation
- Recovery attribution
- Outcome measurement
- Operator visibility

The core loop is:

```text
Payment Failure
      ↓
Detect
      ↓
Diagnose
      ↓
Retrieve Context
      ↓
AI Proposal
      ↓
Economic Ranking
      ↓
Policy Authorization
      ↓
Durable Execution
      ↓
Provider Confirmation
      ↓
Recovery Attribution
      ↓
Measurement
🧠 Why ARIV?

Payment failures are not one homogeneous problem.

A failure can represent:

Situation	Appropriate response
Temporary provider issue	Controlled retry
Customer action required	Payment link / reminder
Payment-method problem	Payment-method recovery
Insufficient funds	Wait / retry later
Route degradation	Suppress retry / escalate
Fraud or risk signal	Stop
Non-retriable decline	Stop
Unknown condition	Conservative handling

The objective is therefore not maximum retries.

The objective is:

Maximum admissible expected net recovery under financial and operational constraints.

🎯 Core Design

ARIV deliberately separates judgment from authority.

Layer	Responsibility	Trust boundary
AI / decision layer	Diagnose, reason, propose	Cannot move money by itself
Qdrant memory	Retrieve prior recovery context	Tenant-scoped
Economic optimizer	Rank candidates	Deterministic financial calculation
PolicyEngine	Authorize / reject	Deterministic and non-bypassable
Transactional Outbox	Persist authorized side effects	Durable handoff
Execution Worker	Execute provider action	Idempotent + lease controlled
Razorpay Adapter	Provider interaction	Test-mode provider boundary
Reconciliation	Establish provider truth	Provider event is authoritative
Attribution	Link action to payment	Prevents false recovery
Measurement	Record economic outcome	No fabricated causal lift
Fundamental rule
Recommendation ≠ Execution
Execution ≠ Payment Success
Payment Success ≠ Attributed Recovery

Only a provider-confirmed and correctly attributed payment contributes to recovery revenue.

🚀 End-to-End Recovery Loop
💻 Technology Stack
Technology	Role
FastAPI	Async backend APIs and webhook endpoints
PostgreSQL	Authoritative transactional state
Redis	Coordination and deduplication
Qdrant	Semantic recovery memory
LLM / OpenAI-compatible adapter	Context-aware recovery reasoning
PolicyEngine	Deterministic financial authorization
Transactional Outbox	Durable side-effect boundary
Execution Worker	Idempotent background execution
Razorpay Test APIs	Provider action execution
Razorpay Webhooks	Provider-side event truth
Telegram	Recovery notifications
Next.js / React	Operator control surface
Docker Compose	Reproducible local environment
🤖 AI Decision Layer

The AI layer is intentionally not the financial authority.

It can:

diagnose payment failure context
propose candidate recovery actions
explain reasoning
retrieve contextual knowledge
return structured decision output

It cannot directly determine:

authoritative rupee value
final economic score
policy approval
execution authorization
provider truth
recovery attribution

A proposal can look like:

{
  "diagnosis": "...",
  "recommended_action": "...",
  "candidate_actions": [],
  "confidence": 0.0,
  "reason": "...",
  "knowledge_refs": []
}

The downstream deterministic layers establish:

Probability
    ↓
Expected Recovery
    ↓
Intervention Cost
    ↓
Risk Penalty
    ↓
Expected Net Recovery
    ↓
Policy Eligibility
    ↓
Authorization
💰 Economic Decisioning

ARIV compares admissible recovery interventions using Expected Net Recovery (ENR).

Conceptually:

ENR =
    P(recovery) × amount
    − intervention cost
    − risk penalty

This means the system does not simply choose:

"the action with the highest probability."

It asks:

Which admissible action has the highest expected net economic value?

Candidate actions include:

RETRY_NOW
RETRY_LATER
GENERATE_PAYMENT_LINK
REQUEST_PAYMENT_METHOD_UPDATE
SEND_REMINDER
ESCALATE_TO_HUMAN
WAIT
STOP_RECOVERY

The PolicyEngine then evaluates these candidates against the financial and operational constraints.

🛡️ Deterministic PolicyEngine

The PolicyEngine is the financial firewall.

It evaluates:

action eligibility
retry limits
tenant constraints
autonomy level
systemic route health
safety requirements
high-value transaction restrictions
candidate ordering
stop conditions

The key invariant is:

AI cannot bypass PolicyEngine.

If no candidate is admissible:

→ STOP_RECOVERY

Approved provider actions are written to a transactional outbox before external side effects occur.

🧠 Qdrant Semantic Recovery Memory

ARIV uses Qdrant for contextual recovery memory.

The memory layer provides:

tenant-scoped vector retrieval
historical recovery context
prior case outcomes
contextual precedent retrieval
reusable recovery knowledge

Embedding support includes:

OpenAI semantic embeddings
deterministic hash fallback for offline and reproducible testing

Tenant isolation is enforced during retrieval.

🧱 Durable Execution

Approved actions cross a transactional outbox boundary:

Policy Approval
      ↓
Transactional Outbox
      ↓
Worker Lease
      ↓
Idempotent Execution
      ↓
Razorpay Adapter

This protects against:

request-lifetime crashes
duplicate financial side effects
worker races
stale execution
policy bypass
repeated provider mutations

State-machine protections, optimistic locking, worker leases, and idempotency are used around recovery execution.

🔐 Razorpay Integration & Provider Truth

ARIV integrates with Razorpay Test APIs and webhooks.

Implemented controls include:

HMAC-SHA256 webhook verification
Webhook deduplication
ProviderEvent persistence
Duplicate-event handling
Out-of-order event handling
Razorpay Test API payment-link creation
Provider reconciliation
Action/payment correlation

The system does not treat a successful API call as a successful recovery.

The provider must confirm the payment.

Razorpay Action
      ↓
payment_link.paid
      ↓
Provider Confirmation
      ↓
Reconciliation
      ↓
Attribution
      ↓
RECOVERED
✅ Recovery Attribution

ARIV explicitly distinguishes:

1. Action succeeded
Payment link created successfully.
2. Provider-confirmed payment
Razorpay reports PAID.
3. Attributed recovery
The provider-confirmed payment is correctly linked
to the recovery action.

Only the third state contributes to recovery revenue.

API Success ≠ Revenue Recovered
📊 Verified Test-Mode Evidence

ARIV includes two real Razorpay Test-Mode benchmark cohorts.

Important: these are execution and decision-policy benchmarks, not customer-conversion benchmarks.

The cohorts did not include customer completion of generated recovery links, so verified recovery and attributed recovery are legitimately zero.

Benchmark A — Execution Scale
25 cases
₹35,232.60 at risk
Metric	Result
Cases decisioned	25 / 25
Policy evaluations	25 / 25
Execution attempts	25
Provider payment-link actions	24 / 25
Real downstream failure	1 × RATE_LIMIT_EXCEEDED
Verified recoveries	0
Attributed recoveries	0
Revenue recovered	₹0
Recovery rate	0%

The benchmark is derived from persisted PostgreSQL state and independently cross-checked with SQL.

Benchmark B — Scenario Diversity
18 cases
₹145,400.00 at risk
Metric	Result
Cases decisioned	18 / 18
RETRY_NOW	4
GENERATE_PAYMENT_LINK	5
STOP_RECOVERY	9
Policy approved	16
Human approval	2
Provider actions	5 / 5
Provider action failures	0
Verified recoveries	0
Attributed recoveries	0
Revenue recovered	₹0
Recovery rate	0%
💳 Real Provider-Confirmed Recovery Demonstration

Separately from the failure-only cohorts, ARIV completed a real Razorpay Test-Mode customer payment recovery flow.

Payment Failure
      ↓
ARIV Recovery Case
      ↓
Recovery Decision
      ↓
Policy Authorization
      ↓
Recovery Action
      ↓
Customer Payment
      ↓
Razorpay Provider Confirmation
      ↓
Reconciliation
      ↓
RECOVERED
      ↓
ACTION_ATTRIBUTED
      ↓
Measurement
      ↓
Telegram Notification

This demonstration is intentionally excluded from the benchmark denominators.

It demonstrates that the provider-side recovery and attribution path works end-to-end without pretending that one successful Test-Mode payment is a statistically meaningful recovery-rate experiment.

🔬 Evidence & Scientific Posture

ARIV explicitly separates provider-backed evidence from synthetic/offline evidence.

Provider-backed
Razorpay Test APIs
Razorpay Test webhooks
HMAC verification
PostgreSQL persistence
Provider reconciliation
Provider-confirmed recovery
Recovery attribution
Telegram notification
Operator dashboard
Synthetic / offline
Economic policy simulations
Strategy comparison
Ablation experiments
Stress evaluation
Reproducibility tests

The system therefore does not treat:

Execution Benchmark

as:

Customer Recovery-Rate Benchmark

and does not treat:

One Successful Test-Mode Payment

as:

Production Recovery Performance
🧬 Strategy Evaluation & Ablation

ARIV contains offline evaluation infrastructure for comparing decision layers.

The conceptual hierarchy is:

Rules
   ↓
Economic Policy
   ↓
AI + Economic
   ↓
AI + Economic + Memory
   ↓
Systemic Intelligence
   ↓
Full ARIV

The purpose is not to assume that more AI means better outcomes.

The purpose is to ask:

Does each additional layer actually create measurable incremental value?

Results should therefore be interpreted empirically.

🚨 Reliability & Engineering Invariants
Failure mode	Protection
Duplicate webhook	Verification + deduplication
Duplicate execution	Idempotency
Out-of-order provider events	Reconciliation
Worker race	Leasing + concurrency controls
Stale state	Optimistic locking
Background async-session failure	Fresh session per background task
Tenant ambiguity	Fail-closed tenant resolution
Provider action failure	Persistent execution outcome
Policy rejection	No unauthorized execution
Already-recovered payment	Stop downstream recovery
Invalid AI proposal	Typed validation + deterministic fallback
Qdrant unavailable	Graceful degradation
Redis unavailable	Health detection / safe degradation
High-risk transaction	Stricter policy controls
🧭 ASK ARIV

ASK ARIV is the conversational operational control layer.

It answers questions grounded in actual ARIV state:

current cases
failure diagnosis
decisions
policy outcomes
provider actions
recovery state
attribution
latest activity
next steps

ASK ARIV is intentionally presented as a grounded operational control surface, not a general-purpose autonomous financial agent.

🖥️ Operator Dashboard

ARIV provides an operator control surface for:

Recovery cases
Failure intelligence
Decision reasoning
Policy outcomes
Execution state
Provider reconciliation
Recovery attribution
Measurement
System health
ASK ARIV
📸 Product Screenshots
Command Center

Failed Payment Case

AI Decision + Policy

Recovery Action

Razorpay Test Payment

Recovered Attribution

Telegram Recovery

ASK ARIV

Qdrant Memory

System Health

Measurement

🏗️ Architecture Overview
🧩 Capability Boundary

ARIV includes a typed systems-integration boundary for controlled capabilities.

It is intentionally not presented as a fully-fledged MCP server or unrestricted agent execution gateway.

The intended pattern is:

Declared Capability
      ↓
Controlled Authorization
      ↓
Deterministic Policy
      ↓
Durable Execution
🧪 Local Reproduction
1. Start the stack
docker compose up -d --build

Backend:

http://localhost:8000

Frontend:

http://localhost:3000
2. Configure Razorpay Test Mode

Provide Razorpay Test credentials and webhook configuration through .env.

The repository contains:

.env.example

Do not commit .env.

3. Run the execution benchmark

From the repository root:

python scripts/run_benchmark.py \
  --cases 25 \
  --min 5000 \
  --max 250000 \
  --webhook-url http://localhost:8000/webhooks/razorpay \
  --account-id acc_benchmark \
  --output-dir . \
  --poll-interval 3 \
  --max-wait 300
4. Run the scenario benchmark
python scripts/run_benchmark.py \
  --scenario-file scripts/scenarios_mixed_18.json \
  --webhook-url http://localhost:8000/webhooks/razorpay \
  --account-id acc_benchmark \
  --output-dir . \
  --poll-interval 3 \
  --max-wait 300
5. Run offline economic evaluation
python scripts/run_economic_benchmark.py --cases 5 --seed 42
6. Run judge benchmark
python scripts/run_judge_benchmark.py
🧪 Tests

Run the full test suite:

docker compose exec web pytest -q

Current verified result:

222 passed
1 skipped
0 failed
2 warnings

The known warnings are pre-existing runtime/deprecation warnings and are not test failures.

📚 Evidence Documentation

Detailed metric definitions and SQL verification:

docs/benchmark-results.md

Judge-facing benchmark summary:

docs/benchmark-summary.md
🔒 Security & Trust Model

ARIV is designed around conservative financial automation.

LLM Output
    ↓
Untrusted / Typed Proposal
    ↓
Deterministic Economic Calculation
    ↓
Deterministic Policy Authorization
    ↓
Durable Side-Effect Boundary
    ↓
Provider Confirmation
    ↓
Recovery Attribution

No single component should both:

Determine financial authority
+
Execute financial side effects
🧠 Important Engineering Decisions

ARIV addressed several difficult payment-workflow problems during development:

webhook endpoint reliability
fresh async database sessions for background processing
provider success-event correlation
optimistic concurrency handling
stale ORM state
fail-closed tenant resolution
webhook deduplication
provider reconciliation
durable outbox execution
worker leases
state-machine protections
Qdrant degradation handling
deterministic benchmark metrics
zero-denominator metric handling
separation of provider success from attributed recovery
📦 Repository Structure
ARIV/
│
├── app/
│   ├── api/
│   ├── core/
│   ├── interfaces/
│   ├── models/
│   ├── services/
│   └── ...
│
├── frontend/
│
├── scripts/
│   ├── run_benchmark.py
│   ├── run_economic_benchmark.py
│   ├── run_judge_benchmark.py
│   ├── benchmark_utils.py
│   └── scenarios_mixed_18.json
│
├── tests/
│
├── docs/
│   ├── screenshots/
│   ├── benchmark-results.md
│   └── benchmark-summary.md
│
├── artifacts/
│   └── benchmarks/
│
├── alembic/
├── Dockerfile
├── docker-compose.yml
├── alembic.ini
├── .env.example
├── .gitignore
├── logo.png
└── README.md
🌐 Evidence Boundary
What is real
Razorpay Test APIs
Razorpay Test webhooks
HMAC verification
PostgreSQL persistence
Redis coordination
Qdrant retrieval
Durable execution
Provider reconciliation
Provider-confirmed recovery demonstration
Recovery attribution
Telegram notification
Operator dashboard
What is synthetic / offline
Economic simulations
Policy comparisons
Strategy ablations
Stress evaluation
Reproducibility experiments

These evidence types remain explicitly separated.

🏁 Final Takeaway

ARIV is not built around:

“Retry every failed payment.”

It is built around:

“Determine whether recovery is worthwhile, select the best admissible intervention, authorize it deterministically, execute it durably, verify provider truth, attribute the outcome, and measure the result.”

The recovery control loop is:

Detect
  ↓
Diagnose
  ↓
Retrieve
  ↓
Propose
  ↓
Rank
  ↓
Authorize
  ↓
Execute
  ↓
Verify
  ↓
Attribute
  ↓
Measure

And the core boundary remains:

AI proposes. Economic logic ranks. Policy authorizes. Infrastructure executes. Provider events establish truth.

<div align="center">
ARIV
Revenue recovery with economic reasoning, deterministic governance, durable execution, and provider-grounded measurement.

▶ Watch the Product Walkthrough

</div> ```

One important point: I kept the README's current honest benchmark posture intact rather than turning the new visual structure into marketing copy. Your existing document explicitly says the cohorts are execution/decision benchmarks, with ₹0 recovered / 0%, while the separate provider-confirmed recovery is excluded from those denominators.
