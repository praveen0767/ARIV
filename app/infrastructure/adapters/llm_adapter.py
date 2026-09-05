import os
import json
import logging
from typing import Any, Dict

from app.core.config import settings

logger = logging.getLogger("ariv.infrastructure.adapters.llm_adapter")

class LLMAdapter:
    @staticmethod
    async def generate_decision(prompt: str) -> Dict[str, Any]:
        """Generate a structured decision proposal from the LLM.

        Expected to return a JSON dict matching `DecisionProposal` schema.
        Raises on any error so caller can fallback.
        """
        api_key = getattr(settings, "LLM_API_KEY", "").strip()
        if not api_key:
            logger.warning("LLM_API_KEY is not configured; caller will fallback.")
            raise RuntimeError("LLM client not configured: missing LLM_API_KEY")

        try:
            from openai import AsyncOpenAI
        except Exception as e:
            logger.error("OpenAI client library not available: %s", e)
            raise RuntimeError(f"OpenAI library not installed or importable: {e}")

        base_url = getattr(settings, "LLM_BASE_URL", "").strip() or None
        timeout = float(getattr(settings, "LLM_TIMEOUT_SECONDS", 10.0))
        model = getattr(settings, "LLM_MODEL", "gpt-4o-mini")

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are the ARIV Decision Engine LLM. "
                            "Analyze the payment failure context and return a valid JSON object matching the DecisionProposal schema: "
                            "{\n"
                            '  "diagnosis": "concise failure diagnosis",\n'
                            '  "recommended_action": "RETRY_NOW" | "RETRY_LATER" | "REQUEST_PAYMENT_METHOD_UPDATE" | "GENERATE_PAYMENT_LINK" | "SEND_REMINDER" | "ESCALATE_TO_HUMAN" | "WAIT" | "STOP_RECOVERY",\n'
                            '  "candidate_actions": ["ACTION_1", "ACTION_2", ...],\n'
                            '  "reason": "concise rationale",\n'
                            '  "confidence": 0.0 to 1.0,\n'
                            '  "knowledge_refs": ["ref1", "ref2"]\n'
                            "}\n"
                            "Do NOT calculate or return economic values (ENR or expected_irv). Only provide recovery action recommendations and confidence."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            return json.loads(content)
        except Exception as e:
            logger.error("LLM generation failed: %s", e)
            raise
