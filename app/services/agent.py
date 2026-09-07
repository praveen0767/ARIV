import logging
from typing import Optional, List, Any
from app.domain.schemas import DecisionContext, DecisionProposal
from app.domain.decision import RecoveryAction
from app.infrastructure.adapters.llm_adapter import LLMAdapter
from app.services.decision_authority import sanitize_llm_payload

logger = logging.getLogger("ariv.services.agent")


class AgentRuntime:
    """
    LLM Agent Runtime.
    Accepts a rich DecisionContext (including Qdrant retrieval evidence) and
    outputs a strictly validated DecisionProposal via LLM invocation.
    Never computes or dictates authoritative economic metrics (ENR).
    """

    @classmethod
    def _parse_action(cls, val: Any) -> Optional[RecoveryAction]:
        if isinstance(val, RecoveryAction):
            return val
        if not val or not isinstance(val, str):
            return None
        clean_val = val.strip().upper()
        # Try direct enum name
        if clean_val in RecoveryAction.__members__:
            return RecoveryAction[clean_val]
        # Try by value
        for member in RecoveryAction:
            if member.value == clean_val:
                return member
        return None

    @classmethod
    async def propose_decision(
        cls,
        context: DecisionContext,
        adapter: Any = None,
    ) -> DecisionProposal:
        proposal, _ = await cls._propose_decision_with_audit(context, adapter)
        return proposal

    @classmethod
    async def _propose_decision_with_audit(
        cls,
        context: DecisionContext,
        adapter: Any = None,
    ) -> tuple[DecisionProposal, dict]:
        """As ``propose_decision`` but also returns the advisory-boundary audit.

        Returns ``(DecisionProposal, {"all": [...], "financial": [...]})`` where the
        second element lists every non-advisory (and financial-authority) key that was
        stripped from the raw LLM payload. Returns ``({...}, {"all": [], "financial": []})``
        on failure with the deterministic fallback proposal.
        """
        logger.info(f"Agent reasoning over context for Case {context.case_id}")
        llm_client = adapter or LLMAdapter

        # Build rich prompt including Qdrant memory evidence
        history_evidence = []
        for idx, item in enumerate((context.historical_cases or [])[:5]):
            if isinstance(item, dict):
                act = item.get("action_type") or item.get("action") or "UNKNOWN"
                out = item.get("outcome_status") or item.get("outcome") or "UNKNOWN"
                cat = item.get("failure_category") or "UNKNOWN"
                history_evidence.append(f"  {idx+1}. Action: {act} -> Outcome: {out} (Category: {cat})")

        history_str = "\n".join(history_evidence) if history_evidence else "  (No prior matching cases found)"

        baseline_name = (
            context.baseline_action.value
            if hasattr(context.baseline_action, "value")
            else str(context.baseline_action or "STOP_RECOVERY")
        )

        route_info = ""
        if context.route_health:
            route_info = f"Systemic Route Health: {context.route_health.get('summary', 'Normal')}\n"

        prompt = (
            f"Case ID: {context.case_id}\n"
            f"Tenant ID: {context.tenant_id}\n"
            f"Domain: {context.domain}\n"
            f"Amount: {context.amount} {context.currency}\n"
            f"Failure Category: {context.failure_category}\n"
            f"Retryability: {context.retryability}\n"
            f"Recoverability: {context.recoverability}\n"
            f"Intervention Count: {context.intervention_count}\n"
            f"Deterministic Baseline Action: {baseline_name}\n"
            f"{route_info}"
            f"Retrieved Historical Recovery Cases:\n{history_str}\n\n"
            "Evaluate this context and recommend the optimal recovery action and ranked candidate actions.\n"
            "Return JSON matching:\n"
            "{\n"
            '  "diagnosis": "<concise diagnosis of root failure cause>",\n'
            '  "recommended_action": "<RecoveryAction>",\n'
            '  "candidate_actions": ["<RecoveryAction>", ...],\n'
            '  "reason": "<concise rationale>",\n'
            '  "confidence": <float between 0.0 and 1.0>,\n'
            '  "knowledge_refs": ["<ref1>", ...]\n'
            "}"
        )

        try:
            llm_response = await llm_client.generate_decision(prompt=prompt)

            # Enforce the strict AI-authority boundary: only advisory fields are
            # forwarded. Any financial/economic/authorization/provider-truth field
            # the LLM may have produced is dropped and never reaches the
            # deterministic economic/policy/execution layer.
            advisory, stripped_all, stripped_financial = sanitize_llm_payload(llm_response)

            # Parse diagnosis
            diagnosis = str(advisory.get("diagnosis") or f"Payment failure ({context.failure_category}) analyzed.")

            # Parse recommended action
            raw_rec = advisory.get("recommended_action")
            rec_action = cls._parse_action(raw_rec)
            if rec_action is None:
                raise ValueError(f"Invalid recommended_action returned by LLM: {raw_rec}")

            # Parse candidate actions
            raw_candidates = advisory.get("candidate_actions") or []
            candidate_actions: List[RecoveryAction] = []
            if isinstance(raw_candidates, list):
                for cand in raw_candidates:
                    parsed = cls._parse_action(cand)
                    if parsed and parsed not in candidate_actions:
                        candidate_actions.append(parsed)

            # Ensure recommended action is in candidate list
            if rec_action not in candidate_actions:
                candidate_actions.insert(0, rec_action)

            # Parse confidence
            raw_conf = advisory.get("confidence")
            try:
                conf = float(raw_conf)
                conf = max(0.0, min(1.0, conf))
            except (TypeError, ValueError):
                conf = 0.5

            reason = str(advisory.get("reason") or "AI decision proposal generated.")
            raw_refs = advisory.get("knowledge_refs")
            knowledge_refs = [str(r) for r in raw_refs] if isinstance(raw_refs, list) else []

            stripped = {"all": stripped_all, "financial": stripped_financial}

            return DecisionProposal(
                diagnosis=diagnosis,
                recommended_action=rec_action,
                candidate_actions=candidate_actions,
                reason=reason,
                confidence=conf,
                expected_irv=0.0,  # Never use LLM as economic authority
                knowledge_refs=knowledge_refs,
            ), stripped

        except Exception as e:
            logger.error(f"LLM decision generation failed: {e}")
            fallback_action = context.baseline_action or RecoveryAction.STOP_RECOVERY
            return DecisionProposal(
                diagnosis=f"Deterministic fallback diagnosis for {context.failure_category}.",
                recommended_action=fallback_action,
                candidate_actions=[fallback_action],
                reason=f"LLM unavailable or invalid output; degraded safely to baseline action ({e}).",
                confidence=0.0,
                expected_irv=0.0,
                knowledge_refs=[],
            ), {"all": [], "financial": []}
