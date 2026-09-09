# ARIV — Render Deployment

This doc describes how to run ARIV on [Render](https://render.com) while leaving
the local `docker compose` workflow (README §Quickstart) **unchanged**. Render
deployment is additive: a Blueprint (`render.yaml`), a background worker
(`python -m app.worker`), and configuration. No local-only code path is removed.

---

## 1. Architecture

```
Browser ──▶ ariv-frontend (Next.js web service, :3000)
                │  /api/proxy/v1/...  (same-origin, HMAC added server-side)
                ▼
            ariv-backend (FastAPI web service, $PORT → health: /health/ready)
                │
                ├── PostgreSQL (Render managed)   — DATABASE_URL
                ├── Redis (Render Key Value)      — REDIS_URL
                ├── Qdrant (external managed/Cloud)— QDRANT_URL [+ QDRANT_API_KEY]
                └── Razorpay (Test Mode, outbound)
                
ariv-worker (background worker service)
                ├── KnowledgeOutbox → Qdrant drainer   (always)
                └── ExecutionOutbox → provider poller  (when Razorpay keys set)
```

**Why a separate worker:** the web service runs HTTP + the durable *lifespan*
drainer. If you ever scale the web service horizontally you would get N
competing drainer loops. Both consumers are claim-based (`FOR UPDATE SKIP
LOCKED` + leases), so it is *safe* either way — but the recommended topology is
one dedicated worker that owns the drainer and the ExecutionOutbox backstop, and
`KNOWLEDGE_DRAIN_ENABLED=false` on the web service to avoid redundant sweepers.

The ExecutionOutbox poller is a **backstop only**. Authorized actions are still
executed synchronously in the request path (decision engine / agent). The poller
guarantees that items left `PENDING` (e.g. a deploy interrupted the request, or
a provider returned `UNKNOWN`) are claimed, reconciled, and dead-lettered by a
durable consumer.

---

## 2. Provision managed infrastructure

| Dependency      | Where                                   | Supplies                              |
|-----------------|-----------------------------------------|---------------------------------------|
| PostgreSQL 15+  | Render → Databases (PostgreSQL)          | `DATABASE_URL` (`postgres://…`)       |
| Redis           | Render → Key Value                      | `REDIS_URL` (`rediss://…` or plain)   |
| Vector DB       | Qdrant Cloud (or self-hosted)           | `QDRANT_URL` (REST HTTPS) + `QDRANT_API_KEY` |

Notes:

- Render Postgres exposes `postgres://…`. ARIV normalizes it to
  `postgresql+asyncpg://…` automatically (`settings.async_database_url`, used by
  both the app engine and `alembic`). You can paste the URL verbatim.
- Qdrant must be seeded once with the required collection:

  ```
  collection:  historical_cases
  vectors:     size = 768, distance = Cosine
  ```

  The app auto-creates it at startup if absent (`ensure_collections`), and the
  /health/ready + /health/dependencies endpoints report `degraded` (not `down`)
  while the collection is missing.
- Razorpay webhook and Test-Mode keys come from the Razorpay dashboard.

---

## 3. Services (render.yaml)

| Service        | Type    | Build context / Dockerfile   | Start command                |
|----------------|---------|------------------------------|------------------------------|
| `ariv-backend` | web     | `./` + `./Dockerfile`        | `uvicorn … --port $PORT`     |
| `ariv-worker`  | worker  | `./` + `./Dockerfile`        | `python -m app.worker`       |
| `ariv-frontend`| web     | `./frontend` + `Dockerfile`  | `npm run start` (proxies)    |

### Migrations

`alembic upgrade head` is set as the backend service's `preDeployCommand`, so
migrations run before the new version starts. Manual equivalent:

```bash
docker build -t ariv-migrate .   # or reuse the deployed image
docker run --rm -e DATABASE_URL="$DATABASE_URL" ariv-migrate python -m alembic upgrade head
```

The migration runs with the `python:3.11-slim` image and normalizes the Render
Postgres URL driver automatically (`alembic/env.py` → `settings.async_database_url`).

> `render.yaml` uses the Docker-runtime Blueprint keys: `dockerContext` and
> `dockerfilePath` for both builds, and `dockerCommand: python -m app.worker`
> to override the backend Dockerfile `CMD` for the worker service. The backend
> itself binds `uvicorn` to `$PORT` (Render) with a local fallback of 8000.

### Health checks

- `/health` — liveness (static `ok`). Used by local `docker compose` healthcheck.
- `/health/ready` — **readiness** (new). Probes Postgres + Redis; returns
  `200 {"status":"ready"}` only when both are reachable, otherwise `503`. This is
  the backend `healthCheckPath` so Render keeps the instance out of rotation
  until core dependencies are live.
- `/health/dependencies` — full breakdown (postgres, redis, qdrant, telegram).

### Razorpay webhook

Configure in the Razorpay dashboard with:

```
URL:        https://ariv-backend.onrender.com/webhooks/razorpay
Event:      payment.failed, payment_link.paid, payment.captured
```

The webhook verifies HMAC-SHA256 over the raw body using `RAZORPAY_WEBHOOK_SECRET`,
deduplicates via Redis + a Postgres unique constraint, and persists events in the
web request path (session-safe shim).

**Durability note:** the webhook acknowledges events over HTTP **only after the
`ProviderEvent` row is committed to Postgres**, so a SIGTERM/deploy crash never
loses the row. If the process dies mid-background-processing, the row remains
durable with `processed_at = NULL` and no automatic replay currently exists.
Inspect after an incident with:

```sql
SELECT id, provider, external_id, created_at
FROM provider_events
WHERE processed_at IS NULL ORDER BY created_at;
```

A safe replay must guard against duplicate `RecoveryCase` creation — run the
replay via the persistent ingestion path only after verifying that event.
(This is the documented follow-up for full at-least-once processing.)

---

## 4. Environment variables

Set secret/shared values in Render dashboard (or via `sync: false` + dashboard
overrides) and the infra URLs from linked resources. `INTERNAL_API_KEY` is a
shared secret between the backend and the frontend proxy (HMAC signing key) —
not a browser-exposed value.

| Variable                     | LOCAL default                                | RENDER                                     |
|------------------------------|----------------------------------------------|--------------------------------------------|
| `DATABASE_URL`               | `postgresql+asyncpg://ariv_user:…@localhost:5432/ariv_db` | Render PostgreSQL (auto-normalized) |
| `REDIS_URL`                  | `redis://localhost:6379/0`                   | Render Key Value                            |
| `QDRANT_URL`                 | `http://localhost:6333`                      | Qdrant Cloud HTTPS endpoint                |
| `QDRANT_API_KEY`             | *(unset)*                                    | Qdrant Cloud key (if cluster requires)     |
| `QDRANT_COLLECTION_NAME`     | `historical_cases`                           | `historical_cases` (must match)            |
| `KNOWLEDGE_DRAIN_ENABLED`    | `true`                                       | web: `false` · worker: `true`              |
| `KNOWLEDGE_DRAIN_INTERVAL_SECONDS` | `30.0`                                  | `30.0`                                      |
| `INTERNAL_API_KEY`           | `test_internal_key`                          | strong random secret (backend ↔ frontend)  |
| `ACCOUNT_ID` (frontend)      | `acc_demo_123`                               | tenant account id the frontend impersonates|
| `API_BASE` (frontend)        | `http://web:8000`                            | `https://ariv-backend.onrender.com`        |
| `DEMO_MODE`                  | `true`                                       | `true` (demo tenant map only)               |
| `RAZORPAY_KEY_ID`            | *(unset)*                                    | Test-Mode key id                            |
| `RAZORPAY_KEY_SECRET`        | *(unset)*                                    | Test-Mode key secret                        |
| `RAZORPAY_WEBHOOK_SECRET`    | `test_secret`                                | Test-Mode webhook secret                    |
| `RAZORPAY_ENVIRONMENT`       | `SANDBOX`                                    | `SANDBOX` (see §6)                          |
| `RAZORPAY_BASE_URL`          | `https://api.razorpay.com/v1`                | *(leave default)*                           |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | *(unset)*                    | optional ops alerts (non-blocking)         |
| `LLM_*`                      | *(unset)*                                    | optional (explainability only)              |
| `EMBEDDING_DIMENSION`        | `768`                                        | `768` (matches collection contract)         |

> The frontend proxy falls back to `http://web:8000` — a **Docker-only** hostname.
> On Render you MUST set `API_BASE` to the backend URL, otherwise the dashboard
> and Ask ARIV return 502.

---

## 5. Deploy

```bash
# render.yaml is a Render Blueprint (Infrastructure-as-Code).
# Option A — dashboard:  New → Blueprint → point at this repo (branch: main)
# Option B — API:        create a Blueprint from the render.yaml in this repo
```

After first deploy:

1. Set `API_BASE` on the frontend to the backend's URL.
2. Set shared secrets: `INTERNAL_API_KEY`, `RAZORPAY_WEBHOOK_SECRET`.
3. Verify:
   - `https://<backend>/health/ready` → `200 {"status":"ready"}`
   - `https://<backend>/health/dependencies` → postgres/redis `ok`
   - `https://<frontend>/` loads, Ask ARIV streams, demo recovery works.

### Sizing (starter plan)

- **backend**: `starter` (0.1 CPU / 512 MB). FastAPI + asyncpg is light; pool_size
  10 is well within 512 MB. Move to `standard` (0.25 CPU / 512 MB) if concurrency
  grows. Do **not** scale beyond one web instance while the drainer is tied to
  the lifespan (the dedicated worker owns draining when you do).
- **worker**: `starter` (0.1 CPU / 512 MB). Poller + drainer are small, I/O-bound
  loops; the memory footprint is the SQLAlchemy session + Qdrant client only.
- **frontend**: `starter` (0.1 CPU / 512 MB). Next.js production server fits;
  `standard` if you add many dynamic routes.

---

## 6. Go-live checklist

- [ ] Swap `RAZORPAY_ENVIRONMENT` `SANDBOX` → live **and** keys + webhook secret
      to live credentials; the adapter factory remains sandbox-locked, so the
      switch is a one-line env change.
- [ ] Move `INTERNAL_API_KEY` and webhook secret into Render encrypted secrets.
- [ ] Point the Razorpay webhook at the production backend URL and re-verify the
      signature is accepted (check `ProviderEvent` rows are inserted).
- [ ] Confirm Qdrant is versioned/backed up and reachable over HTTPS at startup
      (non-fatal if down — financial flows never depend on vector memory).
- [ ] Confirm `KNOWLEDGE_DRAIN_ENABLED=false` on the backend and `true` on worker
      before enabling horizontal scaling of the web service.

---

## 7. Local workflow is unchanged

```bash
docker compose up --build          # db, redis, qdrant, web, frontend
python scripts/run_test_recovery.py --amount 100   # local E2E demo
pytest                             # full suite (281 passed, 1 skipped)
```

The only behavioral change when running locally via plain `uvicorn` (not docker)
is that the DB URL is normalized to the asyncpg driver — a no-op for the docker
default which already uses it. `/health` behaves exactly as before; the new
`/health/ready` endpoint is additive. `KNOWLEDGE_DRAIN_ENABLED` defaults to
`true`, so the lifespan drainer still runs locally exactly as it does today.