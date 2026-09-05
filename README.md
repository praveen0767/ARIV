# ARIV — Agentic Revenue Recovery for Razorpay

<p align="center">
  <img src="logo.png" alt="ARIV" width="180"/>
</p>

<p align="center">
  <strong>Detect revenue risk. Decide the recovery. Enforce policy. Execute safely. Verify the outcome. Attribute the revenue.</strong>
</p>

<p align="center">
  <a href="#architecture">Architecture</a> •
  <a href="#real-end-to-end-recovery">Live Recovery</a> •
  <a href="#ai-agentic-layer">AI / Agentic Layer</a> •
  <a href="#recovery-attribution--measurement">Measurement</a> •
  <a href="#ask-ariv">ASK ARIV</a> •
  <a href="#engineering-reliability">Reliability</a> •
  <a href="#local-development">Run Locally</a>
</p>

---

## Executive Overview

**ARIV (Autonomous Revenue Intelligence & Recovery)** is an agentic revenue-recovery control plane built around Razorpay.

When a payment enters a risky state, ARIV does more than recommend a retry.

It:

**detects → diagnoses → retrieves context → reasons → proposes an intervention → enforces deterministic policy → executes through a durable workflow → waits for provider truth → verifies recovery → attributes recovered revenue → measures impact → notifies operators**

The central design principle is:

> **AI proposes. Policy authorizes. Infrastructure executes. Provider events establish truth.**

ARIV is therefore designed as a **financial workflow system with an AI decision layer**, rather than an LLM wrapped around a payment API.

![ARIV Command Center](docs/screenshots/01-command-center.png)

---

# Why ARIV?

Payment failure is not a single problem.

A transient provider failure may justify a controlled retry.

A customer-action failure may require a new payment method or recovery payment link.

A non-retriable condition may require stopping recovery.

An uncertain failure may need human escalation.

ARIV converts those different failure states into **bounded recovery strategies** instead of blindly retrying everything.

### ARIV closes the loop

```text
Payment Failure
      ↓
Revenue Risk Detection
      ↓
Failure Intelligence
      ↓
Context + Memory
      ↓
AI Decision
      ↓
Policy Firewall
      ↓
Authorized Action
      ↓
Transactional Outbox
      ↓
Execution Worker
      ↓
Razorpay
      ↓
Provider Confirmation
      ↓
Recovery Attribution
      ↓
Measurement
      ↓
Operational Notification
