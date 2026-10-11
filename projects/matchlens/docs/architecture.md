# MatchLens Architecture Decision Record

## 1. Business boundary

The assignment is to build one AI-powered fan artifact, not to reproduce Dream11's private architecture. The product hypothesis is that a fan returning after an interruption needs the story behind a changed score, not another scoreboard.

Primary user outcome: complete a catch-up request and understand the interval using a concise explanation and inspectable evidence.

## 2. Logical services (initially one deployable backend)

### A. Request API
Validates match/innings, boundaries, lens and language. Invalid requests are rejected before any AI invocation. Requests are stateless unless persistence is needed for telemetry or shareable result IDs.

### B. Match-data adapter
Loads a versioned historical fixture. It is the only component allowed to interpret provider-specific JSON. It emits a canonical sequence with stable event IDs, source references and explicit innings / over / ball identity.

### C. Deterministic state engine
Replays the canonical event sequence and calculates state before and after the requested interval. Handles cricket extras, legal-ball semantics, dismissals and innings transitions supported by the dataset. Unknown or unsupported event shapes fail closed rather than being guessed by an LLM.

### D. Context/evidence planner
Computes score deltas and selects key events using transparent heuristics: wickets/milestones first, then lens-relevant events, then quantifiable state changes and supporting deliveries. This is a ranking heuristic, not a proven fan-preference model.

### E. Explanation provider
Takes a bounded evidence packet and explicit style/language instructions. It returns a typed result whose claims refer to fact IDs. It does not get authority to modify match state. Model provider is optional behind an interface.

### F. Verification/fallback gate
Checks referenced fact IDs, allowed event types, numerical assertions that can be deterministically checked, supported-player identities, and output shape. Retry at most once. If it still fails—or the provider is unavailable—return a deterministic template. A valid fact ID alone does not prove a sentence is semantically true, so the golden set also needs human review.

### G. Response/provenance layer
Returns calculated states, deltas, event evidence, explanation source (AI/fallback), replay label, fixture revision and timing metadata. No false claim of live synchronization.

## 3. Sequence

```text
Fan request
  -> validate request & supported range
  -> load fixture revision
  -> normalize source events
  -> deterministically replay interval
  -> compare state at both boundaries
  -> select evidence with stable fact IDs
  -> [optional] request AI explanation
  -> validate shape, citations and checkable assertions
       -> pass: return checked explanation
       -> fail: retry once
       -> fail/unavailable: deterministic recap
  -> record operational metrics
  -> return provenance-labelled response
```

## 4. Invariants

- AI never computes or mutates authoritative score state.
- An event is counted at most once.
- Dataset revision and boundary convention are explicit.
- Every fact can be traced to one or more source events.
- A model outage does not prevent core catch-up.
- Historical replay is not styled as live.
- Never put provider secrets in the client bundle or repository.
- Don't log unnecessary fan-identifying information.
- No real-time provider call unless licensed/authorized and configured.

## 5. Data contract

A canonical event should capture only fields supported by the source, for example:
- source event ID and dataset revision;
- match ID and innings;
- source over/ball identifiers and normalized sequence index;
- batter/bowler where available;
- bat runs, extras broken down by type, total runs;
- wicket type and dismissed player where supported;
- source delivery payload reference.

A state snapshot includes runs, wickets, legal balls faced, innings and boundary identifier. Do not infer exact broadcast frame timing from event ingestion time.

## 6. Persistence and reliability

Initial mode: deterministic fixture load in-process, plus structured logs. If persistence is included, use PostgreSQL for authoritative metadata and request/evaluation records. Cache immutable computed state by (match ID, dataset revision, innings, boundary). Cache invalidation is then a revision change, not a guess.

Do not add Redis, Qdrant, a worker queue, or distributed locks until a real asynchronous path or workload requires them. If later added:
- queue messages are idempotent and versioned;
- retries are bounded;
- no exactly-once claim without stating the underlying delivery semantics;
- workers use leases/visibility timeouts and record terminal outcomes;
- cached/semantic retrieval results never override canonical match data.

## 7. Future live path

A licensed live-feed adapter must add:
- source event and ingestion timestamps separately;
- sequence/correction/revision handling;
- freshness monitoring and stale-data behaviour;
- reconnect/replay and deduplication;
- feed-vs-broadcast timing distinction;
- configurable delay buffer with honest guarantee wording.

WebSockets/SSE are delivery choices, not a solution to broadcast synchronization. Exact spoiler control requires a trusted player/broadcast clock or user calibration.

## 8. Observability and metrics

Collect:
- request duration and failures;
- match calculation failures/reconciliation status;
- AI latency and provider errors;
- validation failure/retry/fallback rates;
- cache hits if caching exists;
- catch-up completion feedback if user explicitly provides it.

Do not present operational metrics as business impact. Report actual values from the deployed build, and distinguish test fixture results from real fan testing.

## 9. Capacity evolution

The prototype makes no 50M-concurrency claim. For later scale: calculate canonical match events once, cache reusable context, shard fan-out by match, separate connection handling from model inference, impose inference budgets/backpressure, and validate each layer with representative load tests and explicit SLOs.

## 10. Decisions

- Build a modular monolith first.
- One historical match and one complete workflow outrank many unverified features.
- English plus one language with real review is better than unsupported multilingual claims.
- Keep optional AI, deterministic fallback always on.
