# functions_mcp_server_governance.py

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class InboundMcpGovernanceDecision:
    allowed: bool
    error: str
    reason: str
    policy_id: str = ""

    def to_dict(self):
        return asdict(self)


def get_inbound_mcp_governance_baseline():
    """Return the disabled-shell governance posture for inbound MCP."""
    return {
        "default_effect": "deny",
        "personal_scope_enabled": False,
        "group_scope_enabled": False,
        "public_scope_enabled": False,
        "all_scope_enabled": False,
        "resource_operations_enabled": [],
        "explicit_deny_wins": True,
    }


def evaluate_inbound_mcp_governance(
    auth_context=None,
    tool_id="",
    resource_family="",
    operation="",
    scope="",
    target_scope_id="",
):
    """Deny all inbound MCP tools until B2/B3 policy storage is implemented."""
    _ = auth_context
    _ = tool_id
    _ = resource_family
    _ = operation
    _ = scope
    _ = target_scope_id
    return InboundMcpGovernanceDecision(
        allowed=False,
        error="mcp_tool_not_allowed",
        reason="No inbound MCP tools are enabled in the disabled shell.",
    )
