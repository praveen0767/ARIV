"""app/services/telegram.py

Production-grade Telegram Notification Service for ARIV.
Provides non-blocking, tenant-isolated operational alerts for recovery lifecycle events.

Key Guarantees:
- Strict secrecy: Never logs bot tokens, authorization URLs, or payment secrets.
- Fault tolerance: Network/Telegram failures NEVER raise or block financial execution.
- Idempotency: Duplicate alerts on retries are suppressed via Redis + in-memory cache.
- Safe formatting: Deterministic HTML formatting with dynamic values escaped & sanitized.
"""

import html
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional
from uuid import UUID

import httpx

from app.core.config import settings

logger = logging.getLogger("ariv.services.telegram")

# Patterns for sanitization
SENSITIVE_PATTERNS = [
    (re.compile(r"bot\d+:[A-Za-z0-9_-]+", re.IGNORECASE), "[REDACTED_BOT_TOKEN]"),
    (re.compile(r"rzp_(?:test|live)_[A-Za-z0-9]+", re.IGNORECASE), "[REDACTED_KEY]"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[REDACTED_CARD]"),
    (re.compile(r"\b\d{3,4}\b(?=.*(?:cvv|cvc))", re.IGNORECASE), "[REDACTED_CVV]"),
]


def sanitize_text(text: Any) -> str:
    """Sanitize strings by redacting known secret formats and HTML-escaping dynamic values."""
    if text is None:
        return ""
    val = str(text)
    for pattern, replacement in SENSITIVE_PATTERNS:
        val = pattern.sub(replacement, val)
    return html.escape(val)


def format_inr(minor_amount: Optional[int]) -> str:
    """Format paise (minor currency units) into ₹ formatted string."""
    if minor_amount is None:
        return "0.00"
    major = minor_amount / 100.0
    return f"{major:,.2f}"


def short_id(val: Any) -> str:
    """Return first 8 chars of an ID/UUID safely."""
    if not val:
        return "UNKNOWN"
    return str(val).split("-")[0][:8]


@dataclass
class TelegramNotificationResult:
    success: bool
    message_id: Optional[int] = None
    error: Optional[str] = None
    skipped: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message_id": self.message_id,
            "error": self.error,
            "skipped": self.skipped,
        }


class TelegramNotifier:
    """
    Non-blocking, production-grade operational notification service.
    """

    _local_sent_cache: set[str] = set()

    @classmethod
    async def check_health(cls) -> str:
        """
        Probe Telegram Bot API status without sending messages.
        Semantics:
        - "unknown": missing token or chat ID (not configured)
        - "ok": configured and getMe probe succeeds (HTTP 200 with ok=True)
        - "degraded": configured but probe fails or times out
        """
        token = settings.TELEGRAM_BOT_TOKEN
        chat_id = settings.TELEGRAM_CHAT_ID

        if not token or not chat_id or not token.strip() or not chat_id.strip():
            return "unknown"

        # Probe getMe safely — verifies bot credentials without dispatching any messages
        url = f"https://api.telegram.org/bot{token.strip()}/getMe"
        timeout = httpx.Timeout(settings.TELEGRAM_TIMEOUT_SECONDS, connect=3.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("ok") is True:
                        return "ok"
            return "degraded"
        except Exception as exc:
            logger.warning("Telegram health check probe failed: %s", type(exc).__name__)
            return "degraded"

    @classmethod
    async def _is_duplicate(cls, idempotency_key: Optional[str]) -> bool:
        if not idempotency_key:
            return False

        if idempotency_key in cls._local_sent_cache:
            return True

        try:
            from app.infrastructure.redis import get_redis
            r = await get_redis()
            if r:
                val = await r.get(idempotency_key)
                if val is not None:
                    cls._local_sent_cache.add(idempotency_key)
                    return True
        except Exception as e:
            logger.debug("Redis idempotency check error (falling back to local cache): %s", type(e).__name__)

        return False

    @classmethod
    async def _mark_sent(cls, idempotency_key: Optional[str]) -> None:
        if not idempotency_key:
            return

        cls._local_sent_cache.add(idempotency_key)
        try:
            from app.infrastructure.redis import get_redis
            r = await get_redis()
            if r:
                await r.set(idempotency_key, "1", ex=86400)
        except Exception as e:
            logger.debug("Redis idempotency mark error: %s", type(e).__name__)

    @classmethod
    async def send_message(
        cls,
        text: str,
        idempotency_key: Optional[str] = None,
        parse_mode: str = "HTML",
    ) -> TelegramNotificationResult:
        """
        Send a message to the configured Telegram chat.
        Fails gracefully — never raises exceptions to the caller.
        Never logs sensitive credentials or complete URLs.
        """
        token = settings.TELEGRAM_BOT_TOKEN
        chat_id = settings.TELEGRAM_CHAT_ID

        if not token or not chat_id or not token.strip() or not chat_id.strip():
            return TelegramNotificationResult(
                success=False,
                error="Telegram credentials not configured",
                skipped=True,
            )

        # Idempotency check
        if idempotency_key and await cls._is_duplicate(idempotency_key):
            logger.info("Telegram notification suppressed (duplicate key: %s)", idempotency_key)
            return TelegramNotificationResult(
                success=True,
                skipped=True,
            )

        url = f"https://api.telegram.org/bot{token.strip()}/sendMessage"
        payload = {
            "chat_id": chat_id.strip(),
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }

        timeout = httpx.Timeout(settings.TELEGRAM_TIMEOUT_SECONDS, connect=3.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    msg_id = data.get("result", {}).get("message_id")
                    if idempotency_key:
                        await cls._mark_sent(idempotency_key)
                    logger.info("Telegram notification delivered (msg_id=%s)", msg_id)
                    return TelegramNotificationResult(success=True, message_id=msg_id)

                # If HTML parsing failed on Telegram side, retry once cleanly as plain text
                if resp.status_code == 400 and "can't parse entities" in resp.text:
                    logger.warning("Telegram parse error; falling back to plain text")
                    payload["parse_mode"] = None
                    fallback_resp = await client.post(url, json=payload)
                    if fallback_resp.status_code == 200:
                        data = fallback_resp.json()
                        msg_id = data.get("result", {}).get("message_id")
                        if idempotency_key:
                            await cls._mark_sent(idempotency_key)
                        return TelegramNotificationResult(success=True, message_id=msg_id)

                error_summary = f"Telegram API HTTP {resp.status_code}"
                logger.warning("Telegram delivery failed: %s", error_summary)
                return TelegramNotificationResult(success=False, error=error_summary)

        except httpx.TimeoutException:
            logger.warning("Telegram delivery timed out")
            return TelegramNotificationResult(success=False, error="Timeout")
        except Exception as exc:
            logger.warning("Telegram delivery error: %s", type(exc).__name__)
            return TelegramNotificationResult(success=False, error=type(exc).__name__)

    # ---------------------------------------------------------------------------
    # High-Value Operational Event Notification Hooks
    # ---------------------------------------------------------------------------

    @classmethod
    async def notify_action_started(
        cls,
        case: Any,
        action: Any,
        amount_minor: int,
        currency: str = "INR",
        provider_label: str = "Razorpay Test",
    ) -> TelegramNotificationResult:
        """Alert when a recovery action starts executing."""
        action_id = str(getattr(action, "id", ""))
        cid = short_id(getattr(case, "id", None))
        act_type = sanitize_text(getattr(action, "action_type", "UNKNOWN"))
        amt_formatted = format_inr(amount_minor)

        text = (
            f"⚡ <b>ARIV RECOVERY ACTION</b>\n"
            f"Case: <code>{cid}</code>\n"
            f"Action: <code>{act_type}</code>\n"
            f"Amount: ₹{amt_formatted}\n"
            f"Provider: {sanitize_text(provider_label)}\n"
            f"Status: EXECUTING"
        )
        key = f"telegram:action_started:{action_id}" if action_id else None
        return await cls.send_message(text, idempotency_key=key)

    @classmethod
    async def notify_action_succeeded(
        cls,
        case: Any,
        action: Any,
        provider_resource_id: Optional[str] = None,
    ) -> TelegramNotificationResult:
        """Alert when a provider recovery action succeeds."""
        action_id = str(getattr(action, "id", ""))
        cid = short_id(getattr(case, "id", None))
        act_type = sanitize_text(getattr(action, "action_type", "UNKNOWN"))
        res_id = sanitize_text(provider_resource_id or "N/A")

        text = (
            f"✅ <b>ARIV RECOVERY ACTION SUCCEEDED</b>\n"
            f"Case: <code>{cid}</code>\n"
            f"Action: <code>{act_type}</code>\n"
            f"Provider reference: <code>{res_id}</code>\n"
            f"Status: SUCCEEDED"
        )
        key = f"telegram:action_succeeded:{action_id}" if action_id else None
        return await cls.send_message(text, idempotency_key=key)

    @classmethod
    async def notify_recovery_verified(
        cls,
        case: Any,
        outcome: Any,
    ) -> TelegramNotificationResult:
        """Alert when recovery outcome is attributed and verified."""
        outcome_id = str(getattr(outcome, "id", getattr(outcome, "action_id", "")))
        cid = short_id(getattr(case, "id", None))
        recovered_minor = getattr(outcome, "recovered_amount_minor", None)
        amt_formatted = format_inr(recovered_minor)
        source_raw = getattr(outcome, "recovery_source", "UNKNOWN")
        source = sanitize_text(source_raw.value if hasattr(source_raw, "value") else source_raw)
        status_raw = getattr(outcome, "outcome_status", "RECOVERED")
        status = sanitize_text(status_raw.value if hasattr(status_raw, "value") else status_raw)

        text = (
            f"💰 <b>ARIV RECOVERY VERIFIED</b>\n"
            f"Case: <code>{cid}</code>\n"
            f"Recovered: ₹{amt_formatted}\n"
            f"Source: <code>{source}</code>\n"
            f"Outcome: <code>{status}</code>"
        )
        key = f"telegram:recovery_verified:{outcome_id}" if outcome_id else None
        return await cls.send_message(text, idempotency_key=key)

    @classmethod
    async def notify_action_failed(
        cls,
        case: Any,
        action: Any,
        reason: Optional[str] = None,
    ) -> TelegramNotificationResult:
        """Alert when an action execution fails at the provider."""
        action_id = str(getattr(action, "id", ""))
        cid = short_id(getattr(case, "id", None))
        act_type = sanitize_text(getattr(action, "action_type", "UNKNOWN"))
        sanitized_reason = sanitize_text(reason or "Provider execution failed")

        text = (
            f"❌ <b>ARIV RECOVERY ACTION FAILED</b>\n"
            f"Case: <code>{cid}</code>\n"
            f"Action: <code>{act_type}</code>\n"
            f"Reason: {sanitized_reason}"
        )
        key = f"telegram:action_failed:{action_id}" if action_id else None
        return await cls.send_message(text, idempotency_key=key)

    @classmethod
    async def notify_action_unknown(
        cls,
        case: Any,
        action: Any,
        reconciliation_status: str = "PENDING",
    ) -> TelegramNotificationResult:
        """Alert when an action enters an ambiguous UNKNOWN provider state."""
        action_id = str(getattr(action, "id", ""))
        cid = short_id(getattr(case, "id", None))
        act_type = sanitize_text(getattr(action, "action_type", "UNKNOWN"))
        rec_status = sanitize_text(reconciliation_status)

        text = (
            f"⚠️ <b>ARIV EXECUTION UNKNOWN</b>\n"
            f"Case: <code>{cid}</code>\n"
            f"Action: <code>{act_type}</code>\n"
            f"Status: UNKNOWN\n"
            f"Reconciliation: {rec_status}"
        )
        key = f"telegram:action_unknown:{action_id}" if action_id else None
        return await cls.send_message(text, idempotency_key=key)

    @classmethod
    async def notify_policy_blocked(
        cls,
        case: Any,
        action: Any,
        reason: Optional[str] = None,
    ) -> TelegramNotificationResult:
        """Alert when an action is blocked by PolicyEngine or safety preflight gates."""
        action_id = str(getattr(action, "id", ""))
        cid = short_id(getattr(case, "id", None))
        act_type = sanitize_text(getattr(action, "action_type", "UNKNOWN"))
        sanitized_reason = sanitize_text(reason or "Action blocked by safety policy")

        text = (
            f"🛡️ <b>ARIV POLICY BLOCK</b>\n"
            f"Case: <code>{cid}</code>\n"
            f"Action: <code>{act_type}</code>\n"
            f"Decision: BLOCKED\n"
            f"Reason: {sanitized_reason}"
        )
        key = f"telegram:policy_blocked:{action_id}" if action_id else None
        return await cls.send_message(text, idempotency_key=key)
