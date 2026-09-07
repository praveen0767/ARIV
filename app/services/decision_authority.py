"""
app/services/decision_authority.py

Strict AI-authority boundary for ARIV.

The LLM is strictly advisory. This module defines the ONLY code path that
translates raw LLM output into a `DecisionProposal`, and it enforces that:

- The LLM may supply only advisory fields: ``diagnosis``, ``recommended_action``,
  ``candidate_actions``, ``reason``, ``confidence``, ``knowledge_refs``.
- Any financial, economic, authorization, or truth-bearing field present in a
  (possibly malformed or adversarial) LLM payload is dropped and audited, and is
  NEVER forwarded to the deterministic services.

Probabilities, expected net recovery, intervention cost, risk penalty, policy
eligibility/authorization, credentials, provider truth, and recovery attribution
are computed exclusively by the deterministic services:

- ``ProbabilityProvider`` - calibrated recovery probability
- ``EconomicOptimizer`` - ENR / expected recovery / cost / risk penalty
- ``PolicyEngine`` - policy eligibility and authorization
- ``OutboxService`` / ``ExecutionWorker`` - execution authorization and dispatch
- webhook reconciliation / payment provider events - provider truth + attribution
"""

from typing import Any, Dict, List, Tuple

# The ONLY keys the LLM is allowed to populate.
ADVISORY_FIELDS: frozenset = frozenset({
    "diagnosis",
    "recommended_action",
    "candidate_actions",
    "reason",
    "confidence",
    "knowledge_refs",
})

# Keys that an adversarial/malformed/failed LLM payload might carry. Even if
# present they are STRIPPED and never influence financial execution.
FINANCIAL_AUTHORITY_FIELDS: frozenset = frozenset({
    # money / economic score
    "expected_irv", "expected_net_recovery", "expected_recovery",
    "expected_recovery_amount", "expected_value", "enr", "ev",
    "recovery_probability", "probability", "prob", "amount", "expected_amount",
    "recoverable_amount", "operational_cost", "cost", "risk_penalty", "risk",
    "final_score", "economic_score", "score", "net_value",
    # authorization / truth
    "approved", "authorized", "policy_decision", "policy", "autonomy",
    "provider_truth", "attribution", "recovered", "success", "paid",
    "credentials", "api_key", "secret", "token",
})


def sanitize_llm_payload(raw: Any) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """Extract the strictly advisory subset of a raw LLM payload.

    Returns ``(advisory, stripped_all, stripped_financial)`` where:
    - ``advisory`` contains only allowed advisory keys (unknown keys are never
      forwarded, even benign-looking ones),
    - ``stripped_all`` is every key removed from the raw payload,
    - ``stripped_financial`` is the subset of removed keys that carry financial,
      authorization, provider-truth, or credential authority.

    If ``raw`` is not a dict, returns ``({}, [], [])`` so callers fall back.
    """
    if not isinstance(raw, dict):
        return {}, [], []

    advisory = {key: raw[key] for key in ADVISORY_FIELDS if key in raw}
    stripped_all = [key for key in raw if key not in ADVISORY_FIELDS]
    stripped_financial = [
        key for key in stripped_all if key.lower().strip("_ *") in FINANCIAL_AUTHORITY_FIELDS
    ]
    return advisory, stripped_all, stripped_financial