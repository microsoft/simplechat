# functions_mcp_server_governance.py

from dataclasses import asdict, dataclass

from functions_governance import get_explicit_item_policies, get_user_governance_group_ids


INBOUND_MCP_ACCESS_POLICY_ENTITY = "inbound_mcp_access"
INBOUND_MCP_ACCESS_ITEM_ID = "inbound_mcp"
INBOUND_MCP_SCOPE_POLICY_ENTITY = "inbound_mcp_scope"
INBOUND_MCP_TARGET_POLICY_ENTITY = "inbound_mcp_target"
LEGACY_INBOUND_MCP_POLICY_ENTITIES = (
    "inbound_mcp_client",
    "inbound_mcp_source",
    "inbound_mcp_tool",
    INBOUND_MCP_SCOPE_POLICY_ENTITY,
    "inbound_mcp_resource_operation",
    INBOUND_MCP_TARGET_POLICY_ENTITY,
)


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
            INBOUND_MCP_ACCESS_POLICY_ENTITY,
        ],
        "policy_entities": [
            INBOUND_MCP_ACCESS_POLICY_ENTITY,
        ],
        "legacy_policy_entities": list(LEGACY_INBOUND_MCP_POLICY_ENTITIES),
        "source_filtering_config_key": "inbound_mcp_allowed_source_ids",
    }


def _normalize_policy_value(value):
    return str(value or "").strip().lower()


def _normalize_policy_values(values):
    if not isinstance(values, (list, tuple, set)):
        return set()
    return {
        str(value or "").strip()
        for value in values
        if str(value or "").strip()
    }


def _policy_matches_principal(policy, user_id, group_ids):
    if bool((policy or {}).get("allow_all", True)):
        return True

    allowed_users = _normalize_policy_values((policy or {}).get("allowed_users", []))
    allowed_groups = _normalize_policy_values((policy or {}).get("allowed_groups", []))
    if not allowed_users and not allowed_groups:
        return False

    normalized_user_id = str(user_id or "").strip()
    if normalized_user_id and normalized_user_id in allowed_users:
        return True

    return bool(set(group_ids or set()).intersection(allowed_groups))


def _evaluate_explicit_policy_group(policy_checks, user_id, group_ids, error, reason_prefix):
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
            inspected_policy_count += len(policies)
            for policy in policies:
                if not _policy_matches_principal(policy, user_id, group_ids):
                    continue
                policy_id = str(policy.get("policy_id") or policy.get("id") or "").strip()
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


def _first_denial_or_none(decisions):
    for decision in decisions:
        if not decision.allowed:
            return decision
    return None


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
    normalized_scope = str(scope or "").strip()
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

    normalized_target_scope_id = str(target_scope_id or "").strip()
    if normalized_scope == "personal" and not normalized_target_scope_id:
        normalized_target_scope_id = delegated_user_id

    user_group_ids = get_user_governance_group_ids(delegated_user_id)
    decisions = [
        _evaluate_explicit_policy_group(
            [
                (
                    INBOUND_MCP_ACCESS_POLICY_ENTITY,
                    [INBOUND_MCP_ACCESS_ITEM_ID, normalized_scope],
                ),
                (INBOUND_MCP_SCOPE_POLICY_ENTITY, [normalized_scope]),
                (
                    INBOUND_MCP_TARGET_POLICY_ENTITY,
                    [
                        f"{normalized_scope}:{normalized_target_scope_id}",
                        f"{normalized_scope}:*",
                    ],
                ),
            ],
            delegated_user_id,
            user_group_ids,
            "mcp_access_not_allowed",
            "Inbound MCP access",
        ),
    ]

    denied_decision = _first_denial_or_none(decisions)
    if denied_decision:
        return denied_decision

    return InboundMcpGovernanceDecision(
        allowed=True,
        error="",
        reason="Inbound MCP request allowed by explicit governance policies.",
        policy_id=";".join(
            decision.policy_id
            for decision in decisions
            if decision.policy_id
        ),
    )
