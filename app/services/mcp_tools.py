"""
app/services/mcp_tools.py

Declaration and deterministic registration of ARIV's real Razorpay provider tools.
Wraps existing provider capabilities without inventing synthetic endpoints or dynamic arbitrary functions.
"""

from app.domain.provider import ProviderCapability
from app.interfaces.mcp import (
    MCPToolRegistry,
    ToolDefinition,
    ToolRiskClassification,
    tool_registry,
)


FETCH_PAYMENT_TOOL = ToolDefinition(
    name="razorpay_fetch_payment",
    description="Fetch status, amount, and provider metadata for a Razorpay payment transaction.",
    risk_classification=ToolRiskClassification.READ,
    input_schema={
        "type": "object",
        "properties": {
            "payment_id": {
                "type": "string",
                "description": "The Razorpay payment ID (e.g., pay_1234567890).",
            },
        },
        "required": ["payment_id"],
    },
    required_capabilities={ProviderCapability.FETCH_PAYMENT},
    is_mutating=False,
    requires_policy_authorization=False,
    requires_durable_execution=False,
)

FETCH_PAYMENT_LINK_TOOL = ToolDefinition(
    name="razorpay_fetch_payment_link",
    description="Fetch live status, short URL, and details for an issued Razorpay payment link.",
    risk_classification=ToolRiskClassification.READ,
    input_schema={
        "type": "object",
        "properties": {
            "payment_link_id": {
                "type": "string",
                "description": "The Razorpay payment link ID (e.g., plink_1234567890).",
            },
        },
        "required": ["payment_link_id"],
    },
    required_capabilities={ProviderCapability.FETCH_PAYMENT_LINK},
    is_mutating=False,
    requires_policy_authorization=False,
    requires_durable_execution=False,
)

CREATE_PAYMENT_LINK_TOOL = ToolDefinition(
    name="razorpay_create_payment_link",
    description=(
        "Generate a governed Razorpay payment link for an active recovery case. "
        "Strictly gated by PolicyEngine, kill switch, and durable outbox execution."
    ),
    risk_classification=ToolRiskClassification.FINANCIAL,
    input_schema={
        "type": "object",
        "properties": {
            "amount": {
                "type": "integer",
                "description": "Recovery amount in paise (minor currency units, e.g., 50000 = ₹500.00).",
                "minimum": 100,
            },
            "currency": {
                "type": "string",
                "description": "Currency code (default: INR).",
                "default": "INR",
            },
            "description": {
                "type": "string",
                "description": "Description of the recovery payment link.",
            },
            "customer_name": {
                "type": "string",
                "description": "Optional customer name.",
            },
            "customer_email": {
                "type": "string",
                "description": "Optional customer email.",
            },
            "customer_phone": {
                "type": "string",
                "description": "Optional customer phone.",
            },
        },
        "required": ["amount"],
    },
    required_capabilities={ProviderCapability.CREATE_PAYMENT_LINK},
    is_mutating=True,
    requires_policy_authorization=True,
    requires_durable_execution=True,
)

CANCEL_PAYMENT_LINK_TOOL = ToolDefinition(
    name="razorpay_cancel_payment_link",
    description=(
        "Cancel an active Razorpay payment link. "
        "Strictly gated by PolicyEngine, kill switch, and durable outbox execution."
    ),
    risk_classification=ToolRiskClassification.FINANCIAL,
    input_schema={
        "type": "object",
        "properties": {
            "payment_link_id": {
                "type": "string",
                "description": "The Razorpay payment link ID to cancel.",
            },
        },
        "required": ["payment_link_id"],
    },
    required_capabilities={ProviderCapability.CANCEL_PAYMENT_LINK},
    is_mutating=True,
    requires_policy_authorization=True,
    requires_durable_execution=True,
)


def register_default_tools(registry: MCPToolRegistry) -> None:
    """Registers the allowlisted provider tools into the provided registry."""
    tools = [
        FETCH_PAYMENT_TOOL,
        FETCH_PAYMENT_LINK_TOOL,
        CREATE_PAYMENT_LINK_TOOL,
        CANCEL_PAYMENT_LINK_TOOL,
    ]
    for t in tools:
        if not registry.get(t.name):
            registry.register(t)


# Pre-register into the global tool registry
register_default_tools(tool_registry)
