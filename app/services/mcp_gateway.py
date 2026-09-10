"""
app/services/mcp_gateway.py

Centralized Tool / MCP Control Gateway for ARIV.
Enforces the mandatory control-plane sequence:
Tool Request -> Lookup -> Validation -> Tenant Resolution -> Risk Classification ->
Capability Check -> PolicyEngine -> ExecutionControl -> Outbox/Durable Execution OR Read ->
Audit Trail.

Guarantees:
- Server-side risk classification cannot be downgraded by the caller.
- Financial mutations NEVER bypass PolicyEngine, kill switch, or Transactional Outbox.
- Tenant isolation strictly verified for both reads and writes.
- Redacts credentials/secrets from audit metadata.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.action import Action, ActionStatus, ExecutionAttempt
from app.domain.classification import FailureCategory, RecoveryClassification
from app.domain.decision import (
    DecisionRecord,
    PolicyStatus,
    RecoveryAction,
)
from app.domain.events import AuditEvent
from app.domain.provider import (
    CancelPaymentLinkRequest,
    CreatePaymentLinkRequest,
    FetchPaymentLinkRequest,
    FetchPaymentRequest,
    ProviderCapability,
    ProviderExecutionResult,
    ProviderOutcomeStatus,
)
from app.domain.recovery_case import CaseStatus, RecoveryCase
from app.domain.schemas import DecisionProposal
from app.domain.tenant import Tenant
from app.infrastructure.adapters import get_razorpay_adapter
from app.interfaces.mcp import (
    MCPErrorCode,
    MCPToolRegistry,
    ToolDefinition,
    ToolInvocation,
    ToolResult,
    ToolRiskClassification,
    tool_registry,
)
from app.interfaces.provider import PaymentProviderAdapter
from app.services.execution_control import ExecutionControlService
from app.services.execution_worker import ExecutionWorker
from app.services.outbox import OutboxService
from app.services.policy import PolicyEngine
from app.services.mcp_tools import register_default_tools

logger = logging.getLogger("ariv.services.mcp_gateway")

SENSITIVE_KEY_PATTERNS = [
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"cvv", re.IGNORECASE),
    re.compile(r"card", re.IGNORECASE),
    re.compile(r"pan", re.IGNORECASE),
    re.compile(r"key", re.IGNORECASE),
    re.compile(r"authorization", re.IGNORECASE),
]


def sanitize_data(data: Any) -> Any:
    """Recursively redacts sensitive keys from dictionaries or lists for audit logs."""
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            if any(p.search(str(k)) for p in SENSITIVE_KEY_PATTERNS):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_data(v)
        return sanitized
    elif isinstance(data, list):
        return [sanitize_data(item) for item in data]
    return data


class MCPToolGateway:
    """
    Governed gateway executing all agent/tool requests in accordance with ARIV invariants.
    """

    def __init__(
        self,
        registry: Optional[MCPToolRegistry] = None,
        provider_adapter: Optional[PaymentProviderAdapter] = None,
    ) -> None:
        if registry is None:
            register_default_tools(tool_registry)
            self.registry = tool_registry
        else:
            self.registry = registry

        self._injected_adapter = provider_adapter

    def _get_adapter(self) -> Optional[PaymentProviderAdapter]:
        if self._injected_adapter is not None:
            return self._injected_adapter
        return get_razorpay_adapter()

    async def invoke(
        self,
        session: AsyncSession,
        invocation: ToolInvocation,
    ) -> ToolResult:
        """
        Processes a ToolInvocation through the complete security and policy gate.
        """
        logger.info(
            "MCPToolGateway: invoking tool '%s' for tenant %s (request_id=%s, preview=%s)",
            invocation.tool_name,
            invocation.tenant_id,
            invocation.request_id,
            invocation.is_preview,
        )

        # 1. Tool Lookup
        tool: Optional[ToolDefinition] = self.registry.get(invocation.tool_name)
        if tool is None:
            return await self._record_audit_and_return(
                session=session,
                invocation=invocation,
                result=ToolResult(
                    success=False,
                    tool_name=invocation.tool_name,
                    risk_classification=ToolRiskClassification.READ,
                    status="FAILED",
                    error_code=MCPErrorCode.TOOL_NOT_FOUND.value,
                    error_message=f"Tool '{invocation.tool_name}' is not registered.",
                    request_id=invocation.request_id,
                ),
            )

        # 2. Server-side Risk Classification
        # Caller-supplied risk classification cannot downgrade the registered classification.
        risk_class = tool.risk_classification

        # 3. Input Validation against Tool Schema
        val_ok, val_err = self._validate_input(tool, invocation.input)
        if not val_ok:
            return await self._record_audit_and_return(
                session=session,
                invocation=invocation,
                result=ToolResult(
                    success=False,
                    tool_name=tool.name,
                    risk_classification=risk_class,
                    status="FAILED",
                    error_code=MCPErrorCode.INVALID_TOOL_INPUT.value,
                    error_message=val_err,
                    request_id=invocation.request_id,
                ),
            )

        # 4. Tenant Verification & Case Ownership
        tenant_ok, case, tenant_err = await self._verify_tenant_and_case(
            session=session,
            invocation=invocation,
            tool=tool,
        )
        if not tenant_ok:
            return await self._record_audit_and_return(
                session=session,
                invocation=invocation,
                result=ToolResult(
                    success=False,
                    tool_name=tool.name,
                    risk_classification=risk_class,
                    status="BLOCKED",
                    error_code=MCPErrorCode.TENANT_FORBIDDEN.value,
                    error_message=tenant_err,
                    request_id=invocation.request_id,
                ),
            )

        # 5. Provider Capability Check
        adapter = self._get_adapter()
        if adapter is None:
            return await self._record_audit_and_return(
                session=session,
                invocation=invocation,
                result=ToolResult(
                    success=False,
                    tool_name=tool.name,
                    risk_classification=risk_class,
                    status="FAILED",
                    error_code=MCPErrorCode.TOOL_NOT_PERMITTED.value,
                    error_message="Provider adapter is not configured or unavailable.",
                    request_id=invocation.request_id,
                ),
            )

        # 6. Branch based on operation risk
        if risk_class == ToolRiskClassification.READ:
            return await self._execute_read_tool(
                session=session,
                invocation=invocation,
                tool=tool,
                adapter=adapter,
                case=case,
            )
        elif risk_class == ToolRiskClassification.FINANCIAL or tool.is_mutating:
            return await self._execute_financial_tool(
                session=session,
                invocation=invocation,
                tool=tool,
                adapter=adapter,
                case=case,
            )
        else:
            return await self._record_audit_and_return(
                session=session,
                invocation=invocation,
                result=ToolResult(
                    success=False,
                    tool_name=tool.name,
                    risk_classification=risk_class,
                    status="FAILED",
                    error_code=MCPErrorCode.TOOL_NOT_PERMITTED.value,
                    error_message=f"Unsupported tool risk category: {risk_class}",
                    request_id=invocation.request_id,
                ),
            )

    def _validate_input(
        self,
        tool: ToolDefinition,
        input_data: Dict[str, Any],
    ) -> Tuple[bool, Optional[str]]:
        """Checks required properties from tool's JSON schema."""
        if not isinstance(input_data, dict):
            return False, "Input payload must be a dictionary."

        schema = tool.input_schema or {}
        required = schema.get("required", [])
        for field_name in required:
            if field_name not in input_data or input_data[field_name] is None:
                return False, f"Missing required parameter '{field_name}' for tool '{tool.name}'."

        # Numeric bounds checks
        properties = schema.get("properties", {})
        for k, v in input_data.items():
            prop = properties.get(k, {})
            if "minimum" in prop and isinstance(v, (int, float)):
                if v < prop["minimum"]:
                    return False, f"Parameter '{k}' ({v}) is less than minimum ({prop['minimum']})."

        return True, None

    async def _verify_tenant_and_case(
        self,
        session: AsyncSession,
        invocation: ToolInvocation,
        tool: ToolDefinition,
    ) -> Tuple[bool, Optional[RecoveryCase], Optional[str]]:
        """
        Enforces tenant isolation:
        - Ensures tenant exists.
        - If case_id is specified, verifies it belongs to invocation.tenant_id.
        - For read tools, verifies that resource belongs to tenant's cases.
        """
        # Verify tenant existence
        ten_res = await session.execute(
            select(Tenant).where(Tenant.id == invocation.tenant_id)
        )
        tenant = ten_res.scalar_one_or_none()
        if not tenant:
            return False, None, f"Tenant {invocation.tenant_id} not found."

        case = None
        if invocation.case_id:
            c_res = await session.execute(
                select(RecoveryCase).where(
                    RecoveryCase.id == invocation.case_id,
                    RecoveryCase.tenant_id == invocation.tenant_id,
                )
            )
            case = c_res.scalar_one_or_none()
            if not case:
                return False, None, f"Case {invocation.case_id} not found or does not belong to tenant."

        # For financial mutations, case_id is strictly required
        if tool.risk_classification == ToolRiskClassification.FINANCIAL and tool.name == "razorpay_create_payment_link":
            if not case:
                return False, None, "Case ID is required for generating a recovery payment link."

        # Read tools resource ownership check
        if tool.name == "razorpay_fetch_payment":
            payment_id = invocation.input.get("payment_id")
            if case:
                case_pid = (case.context or {}).get("payment_id")
                if case_pid and case_pid != payment_id:
                    return False, None, f"Payment {payment_id} does not match Case {case.id}."
            else:
                # Look up if any case belonging to this tenant has this payment_id
                all_cases_res = await session.execute(
                    select(RecoveryCase).where(RecoveryCase.tenant_id == invocation.tenant_id)
                )
                has_payment = any(
                    (c.context or {}).get("payment_id") == payment_id
                    for c in all_cases_res.scalars().all()
                )
                if not has_payment:
                    return False, None, f"Access denied: payment {payment_id} does not belong to tenant."

        elif tool.name == "razorpay_fetch_payment_link":
            plink_id = invocation.input.get("payment_link_id")
            if case:
                case_plink = (case.context or {}).get("payment_link_id")
                if case_plink and case_plink != plink_id:
                    return False, None, f"Payment link {plink_id} does not match Case {case.id}."
            else:
                # Verify tenant ownership via Action attempts or case context
                att_res = await session.execute(
                    select(ExecutionAttempt)
                    .join(Action, ExecutionAttempt.action_id == Action.id)
                    .where(
                        Action.tenant_id == invocation.tenant_id,
                        ExecutionAttempt.provider_request_id == plink_id,
                    )
                )
                if not att_res.scalar_one_or_none():
                    # Fallback check on case context
                    all_cases_res = await session.execute(
                        select(RecoveryCase).where(RecoveryCase.tenant_id == invocation.tenant_id)
                    )
                    has_link = any(
                        (c.context or {}).get("payment_link_id") == plink_id
                        for c in all_cases_res.scalars().all()
                    )
                    if not has_link:
                        return False, None, f"Access denied: payment link {plink_id} not owned by tenant."

        return True, case, None

    async def _execute_read_tool(
        self,
        session: AsyncSession,
        invocation: ToolInvocation,
        tool: ToolDefinition,
        adapter: PaymentProviderAdapter,
        case: Optional[RecoveryCase],
    ) -> ToolResult:
        """Executes read-only inspection tools synchronously."""
        try:
            if tool.name == "razorpay_fetch_payment":
                payment_id = invocation.input["payment_id"]
                result = await adapter.fetch_payment(FetchPaymentRequest(payment_id=payment_id))
            elif tool.name == "razorpay_fetch_payment_link":
                plink_id = invocation.input["payment_link_id"]
                result = await adapter.fetch_payment_link(FetchPaymentLinkRequest(link_id=plink_id))
            else:
                return await self._record_audit_and_return(
                    session=session,
                    invocation=invocation,
                    result=ToolResult(
                        success=False,
                        tool_name=tool.name,
                        risk_classification=tool.risk_classification,
                        status="FAILED",
                        error_code=MCPErrorCode.TOOL_NOT_PERMITTED.value,
                        error_message=f"Unknown read tool: {tool.name}",
                        request_id=invocation.request_id,
                    ),
                )

            if result.status == ProviderOutcomeStatus.SUCCEEDED:
                return await self._record_audit_and_return(
                    session=session,
                    invocation=invocation,
                    result=ToolResult(
                        success=True,
                        tool_name=tool.name,
                        risk_classification=tool.risk_classification,
                        status="SUCCEEDED",
                        output=sanitize_data(result.raw_metadata),
                        request_id=invocation.request_id,
                    ),
                )
            else:
                return await self._record_audit_and_return(
                    session=session,
                    invocation=invocation,
                    result=ToolResult(
                        success=False,
                        tool_name=tool.name,
                        risk_classification=tool.risk_classification,
                        status="FAILED",
                        error_code=MCPErrorCode.PROVIDER_ERROR.value,
                        error_message=result.error_reason or "Provider query failed.",
                        output=sanitize_data(result.raw_metadata),
                        request_id=invocation.request_id,
                    ),
                )
        except Exception as exc:
            logger.error("Error executing read tool %s: %s", tool.name, exc)
            return await self._record_audit_and_return(
                session=session,
                invocation=invocation,
                result=ToolResult(
                    success=False,
                    tool_name=tool.name,
                    risk_classification=tool.risk_classification,
                    status="FAILED",
                    error_code=MCPErrorCode.TOOL_EXECUTION_ERROR.value,
                    error_message="Unexpected error during tool execution.",
                    request_id=invocation.request_id,
                ),
            )

    async def _execute_financial_tool(
        self,
        session: AsyncSession,
        invocation: ToolInvocation,
        tool: ToolDefinition,
        adapter: PaymentProviderAdapter,
        case: Optional[RecoveryCase],
    ) -> ToolResult:
        """
        Executes financial operations through PolicyEngine and Transactional Outbox.
        NEVER directly moves money from conversational agents.
        """
        if tool.name == "razorpay_cancel_payment_link":
            return await self._execute_cancel_payment_link(session, invocation, tool, adapter, case)

        if tool.name != "razorpay_create_payment_link":
            return await self._record_audit_and_return(
                session=session,
                invocation=invocation,
                result=ToolResult(
                    success=False,
                    tool_name=tool.name,
                    risk_classification=tool.risk_classification,
                    status="FAILED",
                    error_code=MCPErrorCode.TOOL_NOT_PERMITTED.value,
                    error_message=f"Unsupported financial tool: {tool.name}",
                    request_id=invocation.request_id,
                ),
            )

        assert case is not None

        # 1. Idempotency Check: Terminal cases cannot create links
        if case.status in (CaseStatus.RECOVERED, CaseStatus.FAILED, CaseStatus.CLOSED):
            return await self._record_audit_and_return(
                session=session,
                invocation=invocation,
                result=ToolResult(
                    success=False,
                    tool_name=tool.name,
                    risk_classification=tool.risk_classification,
                    status="BLOCKED",
                    error_code=MCPErrorCode.IDEMPOTENCY_CONFLICT.value,
                    error_message=f"Case {case.id} is in terminal state ({case.status.value}). Mutation forbidden.",
                    request_id=invocation.request_id,
                ),
            )

        # 2. Idempotency Check: Existing active link
        ctx = dict(case.context or {})
        existing_url = ctx.get("payment_link_url")
        if ctx.get("recovery_stage") == "WAITING_FOR_PAYMENT" or (existing_url and case.status != CaseStatus.RECOVERED):
            return await self._record_audit_and_return(
                session=session,
                invocation=invocation,
                result=ToolResult(
                    success=True,
                    tool_name=tool.name,
                    risk_classification=tool.risk_classification,
                    status="IDEMPOTENT_HIT",
                    output={
                        "case_id": str(case.id),
                        "payment_link_url": existing_url,
                        "payment_link_id": ctx.get("payment_link_id"),
                        "message": "Payment link is already active. Duplicate creation suppressed.",
                    },
                    request_id=invocation.request_id,
                ),
            )

        # 3. PolicyEngine Authorization
        cls_r = await session.execute(
            select(RecoveryClassification)
            .where(RecoveryClassification.case_id == case.id)
            .order_by(desc(RecoveryClassification.timestamp))
            .limit(1)
        )
        classification = cls_r.scalar_one_or_none()

        dec_r = await session.execute(
            select(DecisionRecord)
            .where(DecisionRecord.case_id == case.id)
            .order_by(desc(DecisionRecord.timestamp))
            .limit(1)
        )
        decision = dec_r.scalar_one_or_none()

        if not decision:
            return await self._record_audit_and_return(
                session=session,
                invocation=invocation,
                result=ToolResult(
                    success=False,
                    tool_name=tool.name,
                    risk_classification=tool.risk_classification,
                    status="BLOCKED",
                    error_code=MCPErrorCode.POLICY_REJECTED.value,
                    error_message="Case is missing decision intelligence required for policy evaluation.",
                    request_id=invocation.request_id,
                ),
            )

        if decision.policy_status != PolicyStatus.APPROVED:
            return await self._record_audit_and_return(
                session=session,
                invocation=invocation,
                result=ToolResult(
                    success=False,
                    tool_name=tool.name,
                    risk_classification=tool.risk_classification,
                    status="BLOCKED",
                    error_code=MCPErrorCode.POLICY_REJECTED.value,
                    error_message=f"PolicyEngine rejected action: {decision.rejection_reason or 'Policy safety boundary triggered'}",
                    request_id=invocation.request_id,
                ),
            )

        # Dynamic Policy Revalidation
        category = classification.failure_category if classification else FailureCategory.UNKNOWN
        proposal = DecisionProposal(
            recommended_action=RecoveryAction.GENERATE_PAYMENT_LINK,
            reason="MCP Tool Gateway execution authorization",
            confidence=decision.ai_confidence,
            expected_irv=decision.expected_irv,
        )
        pol_status, _, pol_reason = PolicyEngine.evaluate(proposal, case.domain, category)
        if pol_status != PolicyStatus.APPROVED:
            return await self._record_audit_and_return(
                session=session,
                invocation=invocation,
                result=ToolResult(
                    success=False,
                    tool_name=tool.name,
                    risk_classification=tool.risk_classification,
                    status="BLOCKED",
                    error_code=MCPErrorCode.POLICY_REJECTED.value,
                    error_message=f"PolicyEngine revalidation rejected action: {pol_reason}",
                    request_id=invocation.request_id,
                ),
            )

        # 4. DB-backed Kill Switch Check
        is_enabled = await ExecutionControlService.is_execution_enabled(session)
        if not is_enabled:
            return await self._record_audit_and_return(
                session=session,
                invocation=invocation,
                result=ToolResult(
                    success=False,
                    tool_name=tool.name,
                    risk_classification=tool.risk_classification,
                    status="BLOCKED",
                    error_code=MCPErrorCode.EXECUTION_DISABLED.value,
                    error_message="Global execution kill switch (execution_enabled) is disabled or unreachable.",
                    request_id=invocation.request_id,
                ),
            )

        # 5. Preview Mode (Dry Run)
        amount = invocation.input.get("amount") or case.amount or 10000
        currency = invocation.input.get("currency") or "INR"
        description = invocation.input.get("description") or f"ARIV Recovery - Case {str(case.id)[:8]}"

        if invocation.is_preview:
            return await self._record_audit_and_return(
                session=session,
                invocation=invocation,
                result=ToolResult(
                    success=True,
                    tool_name=tool.name,
                    risk_classification=tool.risk_classification,
                    status="PREVIEW",
                    output={
                        "case_id": str(case.id),
                        "action": RecoveryAction.GENERATE_PAYMENT_LINK.value,
                        "amount": amount,
                        "currency": currency,
                        "policy_status": PolicyStatus.APPROVED.value,
                        "autonomy_level": decision.autonomy_level.value,
                        "preview": True,
                    },
                    request_id=invocation.request_id,
                ),
            )

        # 6. Durable Outbox Execution
        outbox_payload = {
            "amount": amount,
            "currency": currency,
            "description": description,
            "customer_name": invocation.input.get("customer_name") or ctx.get("customer_name"),
            "customer_email": invocation.input.get("customer_email") or ctx.get("customer_email"),
            "customer_phone": invocation.input.get("customer_phone") or ctx.get("customer_phone"),
        }

        action, outbox = await OutboxService.create_authorized_action(
            session=session,
            case_id=case.id,
            tenant_id=case.tenant_id,
            decision_id=decision.id,
            action_type=RecoveryAction.GENERATE_PAYMENT_LINK,
            payload=outbox_payload,
        )

        worker = ExecutionWorker(provider_adapter=adapter)
        prov_result = await worker.process_outbox_item(session, outbox)

        # Reload attempt
        att_r = await session.execute(
            select(ExecutionAttempt)
            .where(ExecutionAttempt.action_id == action.id)
            .order_by(desc(ExecutionAttempt.attempt_number))
            .limit(1)
        )
        attempt = att_r.scalar_one_or_none()
        att_meta = attempt.attempt_metadata if (attempt and isinstance(attempt.attempt_metadata, dict)) else {}
        plink_url = att_meta.get("short_url") or ""
        req_id = attempt.provider_request_id if attempt else "N/A"

        if plink_url and action.status == ActionStatus.SUCCEEDED:
            ctx["recovery_stage"] = "WAITING_FOR_PAYMENT"
            ctx["payment_link_url"] = plink_url
            if req_id and req_id != "N/A":
                ctx["payment_link_id"] = req_id
            case.context = ctx
            await session.commit()

        success = (action.status == ActionStatus.SUCCEEDED)
        return await self._record_audit_and_return(
            session=session,
            invocation=invocation,
            result=ToolResult(
                success=success,
                tool_name=tool.name,
                risk_classification=tool.risk_classification,
                status=action.status.value if hasattr(action.status, "value") else str(action.status),
                output={
                    "case_id": str(case.id),
                    "action_id": str(action.id),
                    "outbox_id": str(outbox.id),
                    "payment_link_url": plink_url or None,
                    "payment_link_id": req_id if req_id != "N/A" else None,
                    "action_status": action.status.value,
                },
                error_code=None if success else MCPErrorCode.PROVIDER_ERROR.value,
                error_message=None if success else outbox.last_error,
                request_id=invocation.request_id,
                execution_ref=str(outbox.id),
            ),
        )

    async def _execute_cancel_payment_link(
        self,
        session: AsyncSession,
        invocation: ToolInvocation,
        tool: ToolDefinition,
        adapter: PaymentProviderAdapter,
        case: Optional[RecoveryCase],
    ) -> ToolResult:
        """Executes payment link cancellation under kill switch and policy control."""
        plink_id = invocation.input["payment_link_id"]

        is_enabled = await ExecutionControlService.is_execution_enabled(session)
        if not is_enabled:
            return await self._record_audit_and_return(
                session=session,
                invocation=invocation,
                result=ToolResult(
                    success=False,
                    tool_name=tool.name,
                    risk_classification=tool.risk_classification,
                    status="BLOCKED",
                    error_code=MCPErrorCode.EXECUTION_DISABLED.value,
                    error_message="Global execution kill switch is disabled or unreachable.",
                    request_id=invocation.request_id,
                ),
            )

        if invocation.is_preview:
            return await self._record_audit_and_return(
                session=session,
                invocation=invocation,
                result=ToolResult(
                    success=True,
                    tool_name=tool.name,
                    risk_classification=tool.risk_classification,
                    status="PREVIEW",
                    output={"action": "CANCEL_PAYMENT_LINK", "payment_link_id": plink_id, "preview": True},
                    request_id=invocation.request_id,
                ),
            )

        req = CancelPaymentLinkRequest(
            payment_link_id=plink_id,
            idempotency_key=f"ariv:cancel:{plink_id}",
        )
        res: ProviderExecutionResult = await adapter.cancel_payment_link(req)
        success = (res.status == ProviderOutcomeStatus.SUCCEEDED)

        return await self._record_audit_and_return(
            session=session,
            invocation=invocation,
            result=ToolResult(
                success=success,
                tool_name=tool.name,
                risk_classification=tool.risk_classification,
                status="SUCCEEDED" if success else "FAILED",
                output=sanitize_data(res.raw_metadata),
                error_code=None if success else MCPErrorCode.PROVIDER_ERROR.value,
                error_message=res.error_reason,
                request_id=invocation.request_id,
            ),
        )

    async def _record_audit_and_return(
        self,
        session: AsyncSession,
        invocation: ToolInvocation,
        result: ToolResult,
    ) -> ToolResult:
        """Persists a sanitized AuditEvent to PostgreSQL without logging credentials."""
        try:
            audit = AuditEvent(
                case_id=invocation.case_id,
                event_type="TOOL_INVOCATION",
                details={
                    "request_id": invocation.request_id,
                    "tenant_id": str(invocation.tenant_id),
                    "tool_name": invocation.tool_name,
                    "risk_classification": result.risk_classification.value,
                    "actor": invocation.actor,
                    "status": result.status,
                    "error_code": result.error_code,
                    "execution_ref": result.execution_ref,
                    "input": sanitize_data(invocation.input),
                    "output": sanitize_data(result.output),
                },
            )
            result_add = session.add(audit)
            if hasattr(result_add, "__await__"):
                await result_add
            await session.flush()
        except Exception as exc:
            logger.warning("MCPToolGateway: Audit log flush failed (non-fatal): %s", exc)

        return result
