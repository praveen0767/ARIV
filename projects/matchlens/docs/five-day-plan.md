# Five-Day Delivery Plan

## Day 1 — Dataset and domain correctness
- Interview 3–5 cricket fans or run short usability conversations; record direct quotes only with consent.
- Select one real, appropriately licensed historical match fixture.
- Record source/attribution, dataset revision and trusted scorecard.
- Implement canonical boundary mapping and deterministic state snapshots.
- Gate: boundary totals reconcile to scorecard; unknown extras fail closed.

## Day 2 — Evidence/context engine
- Implement state diff and interval selection.
- Create stable fact IDs linked to source delivery IDs.
- Add team/player relevance heuristic and invalid interval tests.
- Gate: same fixture revision + request is deterministic.

## Day 3 — AI plus fallback
- Implement a provider interface and typed response schema.
- Add evidence-restricted generation, timeouts, output-size limit and at most one retry.
- Implement deterministic fallback before tuning prompts.
- Test no API key, timeout, malformed response, invented number, unknown player and missing fact ID.
- Gate: AI can fail without making the core workflow fail.

## Day 4 — User experience and deployment
- Build mobile-first selection and result view.
- Display before/after state, selected interval, important events, provenance and replay badge.
- Deploy frontend/backend; secure secrets on server.
- Test the public link in a private/fresh browser session on mobile and desktop.
- Gate: no login required; a user reaches a result unaided.

## Day 5 — Evidence, usability and submission
- Run golden fixtures and scorecard reconciliation.
- Have at least 2 fluent speakers review localized sample outputs if language is shipped.
- Collect small, honest usability feedback.
- Record measured latency and failure behavior; report test counts without inflating them.
- Confirm 200-word note exactly matches deployed features and names only tools actually used.
- Rehearse 2-minute demo: fan problem → chosen interval → state diff → evidence → explanation → fallback.

## Priority order
P0: correct state reconstruction, working link, replay disclosure, deterministic fallback.
P1: evidence IDs, bounded AI, one reviewed regional language.
P2: persistence/telemetry, extra lenses, optional delay simulation.
Out of scope for the deadline: production live-feed integration, exact broadcast synchronization, 50M concurrent connections, social/prediction systems, multi-agent orchestration.
