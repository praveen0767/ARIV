"""
app/services/activity.py

Authoritative operational activity logging and timeline retrieval for ARIV.
Bridges audit events, provider events, policy decisions, execution attempts,
and recovery outcomes into a unified operational activity stream.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy import select, desc, cast, String
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.events import AuditEvent
from app.domain.recovery_case import RecoveryCase

logger = logging.getLogger("ariv.services.activity")


# Standardized Operational Event Types
class OperationalEventType:
    WEBHOOK_RECEIVED = "WEBHOOK_RECEIVED"
    CASE_CREATED = "CASE_CREATED"
    FAILURE_CLASSIFIED = "FAILURE_CLASSIFIED"
    RECOVERY_CONTEXT_BUILT = "RECOVERY_CONTEXT_BUILT"
    MEMORY_RETRIEVED = "MEMORY_RETRIEVED"
    DECISION_CREATED = "DECISION_CREATED"
    POLICY_APPROVED = "POLICY_APPROVED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    ACTION_AUTHORIZED = "ACTION_AUTHORIZED"
    EXECUTION_STARTED = "EXECUTION_STARTED"
    EXECUTION_SUCCEEDED = "EXECUTION_SUCCEEDED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    EXECUTION_UNKNOWN = "EXECUTION_UNKNOWN"
    RECONCILIATION_STARTED = "RECONCILIATION_STARTED"
    RECONCILIATION_SUCCEEDED = "RECONCILIATION_SUCCEEDED"
    RECOVERY_RECORDED = "RECOVERY_RECORDED"
    MEASUREMENT_RECORDED = "MEASUREMENT_RECORDED"
    TELEGRAM_SENT = "TELEGRAM_SENT"
    TELEGRAM_FAILED = "TELEGRAM_FAILED"


EVENT_ICONS = {
    OperationalEventType.WEBHOOK_RECEIVED: "⚡",
    OperationalEventType.CASE_CREATED: "📋",
    OperationalEventType.FAILURE_CLASSIFIED: "🧠",
    OperationalEventType.RECOVERY_CONTEXT_BUILT: "🧩",
    OperationalEventType.MEMORY_RETRIEVED: "🔎",
    OperationalEventType.DECISION_CREATED: "🤖",
    OperationalEventType.POLICY_APPROVED: "🛡️",
    OperationalEventType.POLICY_BLOCKED: "🚫",
    OperationalEventType.ACTION_AUTHORIZED: "🔒",
    OperationalEventType.EXECUTION_STARTED: "🚀",
    OperationalEventType.EXECUTION_SUCCEEDED: "✅",
    OperationalEventType.EXECUTION_FAILED: "❌",
    OperationalEventType.EXECUTION_UNKNOWN: "⚠️",
    OperationalEventType.RECONCILIATION_STARTED: "🔄",
    OperationalEventType.RECONCILIATION_SUCCEEDED: "🔍",
    OperationalEventType.RECOVERY_RECORDED: "💰",
    OperationalEventType.MEASUREMENT_RECORDED: "📈",
    OperationalEventType.TELEGRAM_SENT: "📲",
    OperationalEventType.TELEGRAM_FAILED: "⚠️",
}

EVENT_SEVERITY = {
    OperationalEventType.WEBHOOK_RECEIVED: "info",
    OperationalEventType.CASE_CREATED: "info",
    OperationalEventType.FAILURE_CLASSIFIED: "info",
    OperationalEventType.RECOVERY_CONTEXT_BUILT: "info",
    OperationalEventType.MEMORY_RETRIEVED: "info",
    OperationalEventType.DECISION_CREATED: "info",
    OperationalEventType.POLICY_APPROVED: "success",
    OperationalEventType.POLICY_BLOCKED: "warning",
    OperationalEventType.ACTION_AUTHORIZED: "info",
    OperationalEventType.EXECUTION_STARTED: "info",
    OperationalEventType.EXECUTION_SUCCEEDED: "success",
    OperationalEventType.EXECUTION_FAILED: "error",
    OperationalEventType.EXECUTION_UNKNOWN: "warning",
    OperationalEventType.RECONCILIATION_STARTED: "info",
    OperationalEventType.RECONCILIATION_SUCCEEDED: "success",
    OperationalEventType.RECOVERY_RECORDED: "success",
    OperationalEventType.MEASUREMENT_RECORDED: "success",
    OperationalEventType.TELEGRAM_SENT: "info",
    OperationalEventType.TELEGRAM_FAILED: "warning",
}


class ActivityService:
    """
    Service for writing and reading authoritative operational activity.
    """

    @classmethod
    async def record_event(
        cls,
        session: AsyncSession,
        event_type: str,
        message: str,
        case_id: Optional[uuid.UUID] = None,
        action_id: Optional[uuid.UUID] = None,
        tenant_id: Optional[uuid.UUID] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """
        Records an authoritative operational event into audit_event table.
        """
        payload_details = details.copy() if details else {}
        payload_details["human_readable_message"] = message
        if action_id:
            payload_details["action_id"] = str(action_id)
        if tenant_id:
            payload_details["tenant_id"] = str(tenant_id)

        audit = AuditEvent(
            case_id=case_id,
            event_type=event_type,
            details=payload_details,
            timestamp=datetime.now(timezone.utc),
        )
        session.add(audit)
        await session.flush()
        return audit

    @classmethod
    async def get_recent_activity(
        cls,
        session: AsyncSession,
        tenant_id: Optional[uuid.UUID] = None,
        case_id: Optional[uuid.UUID] = None,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """
        Queries authoritative audit events and formats them for the operational stream.
        Strictly tenant-scoped when tenant_id is provided.
        """
        query = select(AuditEvent)
        if tenant_id:
            query = query.outerjoin(RecoveryCase, AuditEvent.case_id == RecoveryCase.id).where(
                (RecoveryCase.tenant_id == tenant_id) | (cast(AuditEvent.details["tenant_id"], String) == str(tenant_id))
            )
        if case_id:
            query = query.where(AuditEvent.case_id == case_id)

        query = query.order_by(desc(AuditEvent.timestamp)).limit(limit)
        result = await session.execute(query)
        audits = result.scalars().all()

        formatted = []
        for a in audits:
            details = a.details or {}
            event_type = a.event_type
            icon = EVENT_ICONS.get(event_type, "📌")
            severity = EVENT_SEVERITY.get(event_type, "info")
            msg = details.get("human_readable_message") or details.get("reason") or event_type.replace("_", " ").title()

            formatted.append({
                "id": str(a.id),
                "timestamp": a.timestamp.isoformat() if a.timestamp else datetime.now(timezone.utc).isoformat(),
                "event_type": event_type,
                "case_id": str(a.case_id) if a.case_id else None,
                "action_id": details.get("action_id"),
                "severity": severity,
                "icon": icon,
                "human_readable_message": msg,
                "status": details.get("new_status") or details.get("status") or "CONFIRMED",
                "metadata": {k: v for k, v in details.items() if k not in ("human_readable_message", "action_id", "tenant_id")},
            })

        return formatted
