# functions_mcp_server_governance.py

from dataclasses import asdict, dataclass

from functions_governance import (
    INBOUND_MCP_SYSTEM_SOURCE_POLICY_ID,
    get_explicit_item_policies,
    get_user_governance_group_ids,
    policy_allows_principal,
    policy_denies_principal,
)


INBOUND_MCP_SOURCE_POLICY_ENTITY = "inbound_mcp_source"


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
        "personal_access_enabled": False,
        "group_scope_enabled": False,
        "public_scope_enabled": False,
        "all_scope_enabled": False,
        "resource_operations_enabled": [],
        "explicit_deny_wins": True,
        "required_policy_entities": [
            INBOUND_MCP_SOURCE_POLICY_ENTITY,
        ],
        "policy_entities": [
            INBOUND_MCP_SOURCE_POLICY_ENTITY,
        ],
        "legacy_policy_entities": [],
        "source_filtering": "inbound_mcp_allowed_source_ids plus inbound_mcp_source governance policies",
    }


def _normalize_policy_value(value):
    return str(value or "").strip().lower()


def _policy_matches_principal(policy, user_id, group_ids):
    return policy_allows_principal(policy or {}, user_id, group_ids)


def _evaluate_explicit_policy_group(policy_checks, user_id, group_ids, error, reason_prefix, ignored_policy_ids=None):
    ignored_policy_ids = {
        str(policy_id or "").strip()
        for policy_id in (ignored_policy_ids or set())
        if str(policy_id or "").strip()
    }
    normalized_item_ids = [
        (
            str(entity_type or "").strip(),
            [
                str(item_id or "").strip()
                for item_id in item_ids
                if str(item_id or "").strip()
            ],
        )
        for entity_type, item_ids in policy_checks
        if str(entity_type or "").strip()
    ]
    matching_allow_policy_ids = []
    inspected_policy_count = 0

    for entity_type, item_ids in normalized_item_ids:
        for item_id in item_ids:
            policies = get_explicit_item_policies(entity_type, item_id)
            for policy in policies:
                policy_id = str(policy.get("policy_id") or policy.get("id") or "").strip()
                if policy_id in ignored_policy_ids:
                    continue
                inspected_policy_count += 1
                if policy_denies_principal(policy, user_id, group_ids):
                    return InboundMcpGovernanceDecision(
                        allowed=False,
                        error=error,
                        reason=f"{reason_prefix} denied by explicit policy block list.",
                        policy_id=policy_id,
                    )
                if not _policy_matches_principal(policy, user_id, group_ids):
                    continue
                effect = _normalize_policy_value(policy.get("effect") or "allow")
                if effect == "deny":
                    return InboundMcpGovernanceDecision(
                        allowed=False,
                        error=error,
                        reason=f"{reason_prefix} denied by explicit policy.",
                        policy_id=policy_id,
                    )
                matching_allow_policy_ids.append(policy_id)

    if matching_allow_policy_ids:
        return InboundMcpGovernanceDecision(
            allowed=True,
            error="",
            reason=f"{reason_prefix} allowed by explicit policy.",
            policy_id=",".join(matching_allow_policy_ids),
        )

    if inspected_policy_count:
        reason = f"{reason_prefix} has no policy that allows this delegated user."
    else:
        reason = f"{reason_prefix} has no explicit inbound MCP policy."
    return InboundMcpGovernanceDecision(
        allowed=False,
        error=error,
        reason=reason,
    )


def evaluate_inbound_mcp_governance(
    auth_context=None,
    tool_id="",
    resource_family="",
    operation="",
    scope="",
    target_scope_id="",
    identity_type="delegated",
):
    """Evaluate explicit inbound MCP governance policies with deny-by-default behavior."""
    normalized_identity_type = str(identity_type or "delegated").strip()

    if not auth_context:
        return InboundMcpGovernanceDecision(
            allowed=False,
            error="mcp_auth_context_required",
            reason="Inbound MCP governance requires an authenticated caller context.",
        )

    token_type = str(getattr(auth_context, "token_type", "") or "").strip()
    if normalized_identity_type and token_type != normalized_identity_type:
        return InboundMcpGovernanceDecision(
            allowed=False,
            error="mcp_identity_type_not_allowed",
            reason=f"Inbound MCP tool requires {normalized_identity_type} identity.",
        )

    delegated_user_id = str(getattr(auth_context, "delegated_user_id", "") or "").strip()
    if normalized_identity_type == "delegated" and not delegated_user_id:
        return InboundMcpGovernanceDecision(
            allowed=False,
            error="mcp_delegated_user_required",
            reason="Inbound MCP tool requires a delegated user identity.",
        )

    normalized_source_id = str(getattr(auth_context, "source_id", "") or "").strip()
    source_policy_item_ids = [normalized_source_id] if normalized_source_id else []
    source_policy_item_ids.append("*")

    user_group_ids = get_user_governance_group_ids(delegated_user_id)
    source_decision = _evaluate_explicit_policy_group(
        [
            (
                INBOUND_MCP_SOURCE_POLICY_ENTITY,
                source_policy_item_ids,
            ),
        ],
        delegated_user_id,
        user_group_ids,
        "mcp_source_not_allowed",
        "Inbound MCP source access",
        ignored_policy_ids={INBOUND_MCP_SYSTEM_SOURCE_POLICY_ID},
    )
    if not source_decision.allowed:
        return source_decision

    return InboundMcpGovernanceDecision(
        allowed=True,
        error="",
        reason="Inbound MCP request allowed by explicit source governance policy.",
        policy_id=source_decision.policy_id,
    )
