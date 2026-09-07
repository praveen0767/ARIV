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

---

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

---

## 🏆 Executive Summary

Recovering failed payments is not about retrying everything.

Real recovery requires deciding **which failures are worth acting on**, doing so within strict safety and financial controls, and only crediting revenue after the payment provider confirms it.

ARIV implements that end-to-end loop for Razorpay and proves it with real Test-Mode execution evidence.

### Core capabilities

- **Decisioning**: failure classification + semantic memory + an agentic AI layer that *proposes* a typed recovery decision.
- **Ranking**: a deterministic economic optimizer ranks candidate actions by Expected Net Recovery (ENR).
- **Safety**: a deterministic PolicyEngine is the only authority that authorizes money-movement actions.
- **Execution**: durable transactional outbox → worker → Razorpay adapter.
- **Truth**: provider webhooks are verified and reconciled; revenue is attributed only after provider confirmation.
- **Control**: operator dashboard, Telegram alerts, and a conversational **ASK ARIV** layer grounded in live system state.

```text
AI proposes → Economic logic ranks → PolicyEngine authorizes
→ infrastructure executes → provider events establish truth