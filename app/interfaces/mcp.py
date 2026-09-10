"""
app/interfaces/mcp.py

Typed tool-control abstraction for ARIV's MCP / Tool Runtime.
Defines risk classifications, tool definitions, invocation requests,
results, standardized error codes, and the deterministic tool registry.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from uuid import UUID, uuid4

from app.domain.provider import ProviderCapability


class ToolRiskClassification(str, enum.Enum):
    """
    Risk classifications for MCP tools.
    Derived server-side from registered ToolDefinition; callers cannot override.
    """
    READ = "READ"                    # Safe, read-only provider inspection
    WRITE = "WRITE"                  # Non-financial mutations
    FINANCIAL = "FINANCIAL"          # Payment link creation, cancellation, or fund movement
    COMMUNICATION = "COMMUNICATION"  # Notifications (e.g., Telegram alerts)


class MCPErrorCode(str, enum.Enum):
    """Standardized machine-readable error codes for the MCP Tool Runtime."""
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    INVALID_TOOL_INPUT = "INVALID_TOOL_INPUT"
    TOOL_NOT_PERMITTED = "TOOL_NOT_PERMITTED"
    TENANT_FORBIDDEN = "TENANT_FORBIDDEN"
    POLICY_REJECTED = "POLICY_REJECTED"
    EXECUTION_DISABLED = "EXECUTION_DISABLED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"


@dataclass(frozen=True)
class ToolDefinition:
    """
    Authoritative declaration of a tool's capabilities, schemas, and governance rules.
    Configured deterministically at server boot.
    """
    name: str
    description: str
    risk_classification: ToolRiskClassification
    input_schema: Dict[str, Any]
    output_schema: Optional[Dict[str, Any]] = None
    required_capabilities: Set[ProviderCapability] = field(default_factory=set)
    is_mutating: bool = False
    requires_policy_authorization: bool = False
    requires_durable_execution: bool = False

    def validate(self) -> None:
        """Enforces schema and metadata invariants."""
        if not self.name or not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Tool name must be a non-empty string.")
        if not self.description or not isinstance(self.description, str):
            raise ValueError("Tool description must be a non-empty string.")
        if not isinstance(self.risk_classification, ToolRiskClassification):
            raise ValueError(f"Invalid risk classification: {self.risk_classification}")
        if not isinstance(self.input_schema, dict):
            raise ValueError("Tool input_schema must be a dictionary.")


@dataclass
class ToolInvocation:
    """
    A single invocation request passing through the Tool Gateway.
    Tenant identity is always bound by the authenticated session.
    """
    tool_name: str
    tenant_id: UUID
    actor: str = "agent"
    input: Dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: uuid4().hex)
    case_id: Optional[UUID] = None
    idempotency_key: Optional[str] = None
    is_preview: bool = False


@dataclass
class ToolResult:
    """
    Normalized, sanitized response returned from the Tool Gateway.
    Never leaks credentials, secret keys, or internal tracebacks.
    """
    success: bool
    tool_name: str
    risk_classification: ToolRiskClassification
    status: str
    output: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    request_id: str = ""
    execution_ref: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "tool_name": self.tool_name,
            "risk_classification": self.risk_classification.value,
            "status": self.status,
            "output": self.output,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "request_id": self.request_id,
            "execution_ref": self.execution_ref,
        }


class MCPToolRegistry:
    """
    Deterministic registry for allowlisted tools.
    Rejects duplicate registrations, dynamic code injections, or arbitrary user callables.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Registers a tool definition. Rejects duplicates."""
        tool.validate()
        if tool.name in self._tools:
            raise ValueError(f"Tool with name '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Resolves a tool definition by exact name."""
        return self._tools.get(name)

    def list_tools(self) -> List[ToolDefinition]:
        """Returns all registered tool definitions in deterministic order."""
        return [self._tools[k] for k in sorted(self._tools.keys())]

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """
        Exposes tool schemas matching the Model Context Protocol (MCP) `tools/list` format.
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            }
            for tool in self.list_tools()
        ]


# Default global tool registry instance
tool_registry = MCPToolRegistry()
