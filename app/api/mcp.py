"""
app/api/mcp.py

Model Context Protocol (MCP) JSON-RPC 2.0 compliant endpoint for ARIV.
Provides `tools/list` and `tools/call` over HTTP.
Enforces HMAC tenant authentication and delegates strictly to the MCPToolGateway.
"""

import hmac
import hashlib
import json
import logging
from typing import Any, Dict, Optional, Union
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.tenant import Tenant
from app.infrastructure.database import get_db_session
from app.interfaces.mcp import ToolInvocation, tool_registry
from app.services.ingestion import resolve_tenant
from app.services.mcp_gateway import MCPToolGateway

logger = logging.getLogger("ariv.api.mcp")

router = APIRouter(prefix="/v1/mcp", tags=["mcp"])


# ---------------------------------------------------------------------------
# Auth dependency (HMAC-SHA256)
# ---------------------------------------------------------------------------

async def get_current_tenant(
    x_account_id: str = Header(..., alias="X-Account-ID"),
    x_signature: str = Header(..., alias="X-Signature"),
    session: AsyncSession = Depends(get_db_session),
) -> Tenant:
    """Verifies HMAC signature and resolves tenant context."""
    expected = hmac.new(
        settings.INTERNAL_API_KEY.encode("utf-8"),
        x_account_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, x_signature):
        logger.warning("MCP API: invalid signature for account_id=%s", x_account_id)
        raise HTTPException(status_code=401, detail="Invalid signature")

    tenant = await resolve_tenant(session, x_account_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 Models
# ---------------------------------------------------------------------------

class JSONRPCRequest(BaseModel):
    jsonrpc: str = Field(default="2.0")
    id: Optional[Union[str, int]] = None
    method: str
    params: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# MCP Endpoints
# ---------------------------------------------------------------------------

@router.post("")
async def handle_mcp_rpc(
    rpc_req: JSONRPCRequest,
    tenant: Tenant = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """
    Standard JSON-RPC 2.0 handler implementing Model Context Protocol methods:
    - tools/list: returns all registered tools matching MCP schema specifications.
    - tools/call: executes an authorized tool invocation via MCPToolGateway.
    """
    req_id = rpc_req.id
    method = rpc_req.method
    params = rpc_req.params or {}

    # 1. tools/list
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": tool_registry.get_tool_schemas(),
            },
        }

    # 2. tools/call
    elif method == "tools/call":
        tool_name = params.get("name")
        if not tool_name or not isinstance(tool_name, str):
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32602,
                    "message": "Invalid params: 'name' is required for tools/call.",
                },
            }

        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            arguments = {}

        # Resolve case_id if present
        raw_case_id = params.get("case_id") or arguments.get("case_id")
        parsed_case_id = None
        if raw_case_id:
            try:
                parsed_case_id = UUID(str(raw_case_id))
            except Exception:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32602,
                        "message": f"Invalid case_id: {raw_case_id}",
                    },
                }

        is_preview = bool(params.get("preview") or arguments.get("preview", False))

        invocation = ToolInvocation(
            tool_name=tool_name,
            tenant_id=tenant.id,
            actor="mcp_rpc",
            input=arguments,
            case_id=parsed_case_id,
            is_preview=is_preview,
        )

        gateway = MCPToolGateway(registry=tool_registry)
        result = await gateway.invoke(session=session, invocation=invocation)

        text_content = json.dumps(
            result.output if result.success else {"error": result.error_message, "code": result.error_code}
        )

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": text_content,
                    }
                ],
                "isError": not result.success,
                "_meta": {
                    "status": result.status,
                    "error_code": result.error_code,
                    "risk_classification": result.risk_classification.value,
                    "execution_ref": result.execution_ref,
                },
            },
        }

    # 3. Method Not Found
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": -32601,
            "message": f"Method '{method}' not found.",
        },
    }
