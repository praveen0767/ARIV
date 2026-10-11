# MatchLens — Evidence-Grounded Cricket Catch-Up

> Dream11 FDE internship assignment artifact: help a returning fan understand what changed during a missed interval of a cricket match.

## Product thesis

**The fan's job:** "I missed part of the match. Show me what changed, why it matters, and let me understand it in my preferred language."

MatchLens reconstructs a selected interval from a real historical ball-by-ball dataset, calculates match-state differences deterministically, prioritizes consequential events, and uses bounded AI to communicate the evidence. It must not describe a historical replay as live.

This is a proposed standalone project in the ARIV repository. It is not integrated into Dream11 and does not assume access to Dream11 internal APIs or systems.

## Core workflow

1. Choose a supported match and innings.
2. Choose start and end boundaries (over-end boundaries for the first slice).
3. Choose an overall/team/player lens and a supported language.
4. Reconstruct both states from the source deliveries.
5. Build a fact packet with source delivery IDs.
6. Generate a concise explanation from that packet (optional model provider).
7. Validate structured assertions and evidence references.
8. Return the explanation or a deterministic fallback, always with replay/data provenance.

## Architecture invariants

- **Source authority:** data, not the LLM, determines score and event facts.
- **Deterministic replay:** a fixed dataset revision and interval must reproduce the same computed state.
- **Idempotence:** duplicate input events do not double-count runs or wickets.
- **Evidence traceability:** surfaced facts retain source delivery identifiers.
- **Bounded AI:** one model call plus at most one retry; timeouts and output limits; no model call needed to get a usable fallback.
- **Clear status:** historical replay is unmistakably labelled; unsupported live synchronization is never implied.
- **Graceful degradation:** missing API keys, model timeout, or invalid output must not break deterministic catch-up.
- **Honest measurement:** test results and demo limitations are recorded; no unsupported capacity or product-gap claims.

## First milestone: a working five-day artifact

Must ship:
- one verified, appropriately licensed historical match;
- deterministic interval state reconstruction and state diff;
- a mobile-first interface;
- evidence-linked important events;
- AI explanation if available, with deterministic fallback;
- tests reconciling the selected interval to a trusted scorecard;
- public deployment and a <=200-word assignment note.

Not in the critical path:
- licensed real-time data feeds;
- exact OTT/broadcast synchronization;
- 50M-concurrent-user deployment;
- social graph, prediction markets or monetary gamification;
- Kafka, Kubernetes, Qdrant or multi-agent orchestration without measured need.

## Architecture path

`frontend` → `FastAPI request contract` → `match-data adapter` → `deterministic match engine` → `evidence/context planner` → `bounded explanation provider` → `claim/evidence gate` → `verified response or deterministic fallback`.

The initial implementation can stay as a modular monolith. PostgreSQL can persist match metadata, dataset revisions and request telemetry if needed; a cache is an optimization, not an authority. A future authorized live-feed adapter must implement the same canonical event contract and add source freshness, reconnect, ordering and duplicate handling.

## Dataset and attribution

Use only an appropriately licensed dataset. Cricsheet's license and format must be reviewed before including or redistributing data:
- https://cricsheet.org/licensing/
- https://cricsheet.org/format/json/
- https://cricsheet.org/downloads/

Store the source URL, license/attribution text, dataset revision, match identifier and retrieval date beside the fixture. Do not fabricate a scorecard or imply that sample data came from a live feed.

## Acceptance criteria

1. Same match revision + same boundaries produce same calculated states.
2. Invalid or inverted intervals are rejected before any model call.
3. Calculated score/wickets reconcile with the selected scorecard.
4. Every displayed event points to known source delivery IDs.
5. An invalid model response cannot replace calculated facts.
6. With the model disabled, catch-up still returns a useful recap.
7. UI and response label the dataset as historical replay.
8. README documents run, test, environment and deployment instructions.
