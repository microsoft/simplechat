# functions_agent_delegation.py
"""Configuration and authorization boundaries for explicitly attached agent actions.

Azure-backed modules are imported at the operation boundary so action discovery and
schema validation remain side-effect free and do not introduce loader import cycles.
"""

import builtins
from copy import deepcopy
from datetime import datetime, timezone
from importlib import import_module
from urllib.parse import urlencode


AGENT_PLUGIN_TYPE = "agent"
AGENT_DEFAULT_ENDPOINT = "internal://agent"
AGENT_ACTION_VALIDATION_ERROR = (
    "Invalid Call agent configuration. Select a stored agent and its workspace; "
    "custom endpoints and credentials are not supported."
)
AGENT_TYPES = frozenset({"local", "aifoundry", "new_foundry", "foundry_workflow"})
AGENT_SCOPES = frozenset({"personal", "group", "global"})
_MANIFEST_FIELDS = frozenset({
    "id", "name", "displayName", "type", "description", "is_enabled", "identity_id",
    "endpoint", "auth", "metadata", "additionalFields", "user_id", "group_id",
    "is_global", "is_group", "scope", "created_at", "created_by", "modified_at",
    "modified_by", "updated_at", "last_updated", "_attachments", "_etag", "_rid",
    "_self", "_ts", "_delegation_scope_type", "_delegation_scope_id",
})
UNAVAILABLE_MESSAGE = "The configured agent is unavailable or you are not permitted to use it."


class AgentDelegationConflictError(ValueError):
    """The agent's action bindings changed after the editor loaded them."""


def _identifier(value, label, *, max_bytes=128):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.strip().encode("utf-8")) > max_bytes
        or any(character in value for character in "/\\?#")
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError(f"{label} must be a valid stored identifier.")
    return value.strip()


def _scope(value):
    normalized = str(value or "").strip().lower()
    if normalized == "user":
        normalized = "personal"
    if normalized not in AGENT_SCOPES:
        raise ValueError("An explicit personal, group, or global scope is required.")
    return normalized


def _settings(settings):
    if settings is not None:
        return settings
    return import_module("functions_settings").get_settings()


def normalize_agent_target(reference):
    """Validate the persisted reference without reading any application data."""
    if not isinstance(reference, dict) or set(reference) != {"id", "scope_type", "scope_id"}:
        raise ValueError("Select an agent using its stored ID and workspace scope.")
    result = {
        "id": _identifier(reference.get("id"), "Agent ID", max_bytes=1023),
        "scope_type": _scope(reference.get("scope_type")),
        "scope_id": _identifier(reference.get("scope_id"), "Agent scope"),
    }
    if result["scope_type"] == "global" and result["scope_id"] != "global":
        raise ValueError("Global agent references must use the global scope.")
    return result


def validate_agent_action_manifest(manifest):
    """Return a normalized agent action, without invoking or resolving its target."""
    if not isinstance(manifest, dict) or manifest.get("type") != AGENT_PLUGIN_TYPE:
        raise ValueError("A Call agent action must have type 'agent'.")
    if set(manifest) - _MANIFEST_FIELDS:
        raise ValueError("Call agent actions cannot override target credentials, connections, or configuration.")
    result = deepcopy(manifest)
    endpoint = result.get("endpoint")
    if endpoint not in (None, "", AGENT_DEFAULT_ENDPOINT):
        raise ValueError("Call agent actions must use the internal agent endpoint.")
    auth = result.get("auth", {"type": "user"})
    if not isinstance(auth, dict) or auth.get("type") != "user" or set(auth) != {"type"}:
        raise ValueError("Call agent actions use the invoking user and cannot store credentials.")
    if result.get("identity_id"):
        raise ValueError("Call agent actions cannot use a workspace identity.")
    fields = result.get("additionalFields")
    if not isinstance(fields, dict) or set(fields) != {"target_agent"}:
        raise ValueError("Call agent configuration must contain only target_agent.")
    result["additionalFields"] = {"target_agent": normalize_agent_target(fields["target_agent"])}
    result["endpoint"] = AGENT_DEFAULT_ENDPOINT
    result["auth"] = {"type": "user"}
    return result


def agent_reference(agent, user_id=None):
    """Build an exact reference from either a stored agent or a scoped reference."""
    if not isinstance(agent, dict):
        raise ValueError("A stored calling agent is required.")
    if "scope_type" in agent:
        reference = {
            "id": agent.get("id"),
            "scope_type": agent.get("scope_type"),
            "scope_id": agent.get("scope_id"),
        }
        if reference["scope_type"] == "global" and not reference["scope_id"]:
            reference["scope_id"] = "global"
        return normalize_agent_target(reference)
    if agent.get("is_group") and agent.get("is_global"):
        raise ValueError("Agent scope is ambiguous.")
    if agent.get("is_group"):
        scope_type, scope_id = "group", agent.get("group_id")
    elif agent.get("is_global"):
        scope_type, scope_id = "global", "global"
    else:
        scope_type, scope_id = "personal", agent.get("user_id") or user_id
    return normalize_agent_target({
        "id": agent.get("id"), "scope_type": scope_type, "scope_id": scope_id,
    })


def agent_authentication_url(agent, user_id):
    """Re-enter normal HTTP handling before starting a target's OAuth consent flow."""
    return f"/api/agents/foundry-auth?{urlencode(agent_reference(agent, user_id))}"


def _require_actor(user_id):
    if not isinstance(user_id, str) or not user_id.strip() or user_id == "system":
        raise PermissionError("An authenticated execution identity is required for agent delegation.")
    return _identifier(user_id, "User ID")


def _is_admin():
    # This is used only for management, never to grant runtime access to a target.
    from flask import has_request_context, session

    return bool(has_request_context() and "Admin" in (session.get("user") or {}).get("roles", []))


def _assert_scope_access(user_id, scope_type, scope_id, settings, *, manage=False):
    user_id = _require_actor(user_id)
    if not settings.get("enable_semantic_kernel", False):
        raise PermissionError("Agents are disabled.")
    governance = import_module("functions_governance")
    if scope_type == "personal":
        if scope_id != user_id:
            raise PermissionError(UNAVAILABLE_MESSAGE)
        if not settings.get("allow_user_agents", False):
            raise PermissionError("Personal agents are disabled.")
        governance.ensure_governance_access("governance_user_agents", user_id)
    elif scope_type == "group":
        if not settings.get("enable_group_workspaces", False) or not settings.get("allow_group_agents", False):
            raise PermissionError("Group agents are disabled.")
        roles = ("Owner", "Admin", "DocumentManager", "User")
        if manage:
            roles = ("Owner",) if settings.get("require_owner_for_group_agent_management") else ("Owner", "Admin")
        import_module("functions_group").assert_group_role(user_id, scope_id, allowed_roles=roles)
        governance.ensure_governance_access("governance_group_agents", user_id)
    elif scope_type == "global":
        if scope_id != "global":
            raise PermissionError(UNAVAILABLE_MESSAGE)
        if manage and not _is_admin():
            raise PermissionError("Administrator access is required to manage global agent actions.")
    else:
        raise ValueError("Invalid agent scope.")


def resolve_delegation_scope(user_id, scope_type, group_id=None, *, manage=False, settings=None):
    """Resolve an editor scope without changing the user's active workspace."""
    scope_type = _scope(scope_type)
    settings = _settings(settings)
    if scope_type == "personal":
        scope_id = _require_actor(user_id)
    elif scope_type == "global":
        scope_id = "global"
        if not _is_admin():
            raise PermissionError("Administrator access is required for global action management.")
    elif group_id is not None:
        scope_id = _identifier(group_id, "Group ID")
    else:
        scope_id = import_module("functions_group").require_active_group(user_id)
    _assert_scope_access(user_id, scope_type, scope_id, settings, manage=manage)
    return scope_type, scope_id


def resolve_delegation_group_scope(user_id, group_id=None, *, allowed_roles=("Owner", "Admin", "DocumentManager", "User")):
    """Explicit group API scoping; retain the existing active-group default."""
    groups = import_module("functions_group")
    if group_id is None:
        return groups.require_active_group(user_id, allowed_roles=allowed_roles)
    group_id = _identifier(group_id, "Group ID")
    groups.assert_group_role(user_id, group_id, allowed_roles=allowed_roles)
    return group_id


def _container(kind, scope_type):
    attribute = {
        ("agents", "personal"): "cosmos_personal_agents_container",
        ("agents", "group"): "cosmos_group_agents_container",
        ("agents", "global"): "cosmos_global_agents_container",
        ("actions", "personal"): "cosmos_personal_actions_container",
        ("actions", "group"): "cosmos_group_actions_container",
        ("actions", "global"): "cosmos_global_actions_container",
    }[(kind, scope_type)]
    return getattr(import_module("config"), attribute)


def _read_agent(reference):
    # Runtime-only Azure import: metadata and schema discovery must not require Cosmos.
    from azure.cosmos.exceptions import CosmosResourceNotFoundError

    partition = reference["id"] if reference["scope_type"] == "global" else reference["scope_id"]
    try:
        record = _container("agents", reference["scope_type"]).read_item(
            item=reference["id"], partition_key=partition,
        )
    except CosmosResourceNotFoundError as exc:
        raise LookupError(UNAVAILABLE_MESSAGE) from exc
    return _canonical_agent(record, reference["scope_type"], reference["scope_id"])


def _canonical_agent(record, scope_type, scope_id):
    result = deepcopy(record)
    if scope_type == "personal" and result.get("user_id") != scope_id:
        raise PermissionError(UNAVAILABLE_MESSAGE)
    if scope_type == "group" and result.get("group_id") != scope_id:
        raise PermissionError(UNAVAILABLE_MESSAGE)
    result["is_global"] = scope_type == "global"
    result["is_group"] = scope_type == "group"
    result["group_id"] = scope_id if scope_type == "group" else None
    result["user_id"] = scope_id if scope_type == "personal" else None
    result["scope_type"] = scope_type
    result["scope_id"] = scope_id
    return result


def _list_records(kind, scope_type, scope_id):
    parameters = []
    conditions = []
    if kind == "actions":
        conditions.append("c.type = @type")
        parameters.append({"name": "@type", "value": AGENT_PLUGIN_TYPE})
    if scope_type != "global":
        field = "user_id" if scope_type == "personal" else "group_id"
        conditions.append(f"c.{field} = @scope_id")
        parameters.append({"name": "@scope_id", "value": scope_id})
    query = "SELECT * FROM c" + (" WHERE " + " AND ".join(conditions) if conditions else "")
    options = {"enable_cross_partition_query": True} if scope_type == "global" else {"partition_key": scope_id}
    return list(_container(kind, scope_type).query_items(query=query, parameters=parameters, **options))


def _assert_target_scope(reference, owner_scope, owner_id, settings):
    if reference["scope_type"] == owner_scope and reference["scope_id"] == owner_id:
        return
    if (
        reference["scope_type"] == "global"
        and owner_scope != "global"
        and settings.get("merge_global_semantic_kernel_with_workspace", False)
    ):
        return
    raise PermissionError("Agent calls must stay in the same workspace or use a permitted global agent.")


def resolve_delegation_agent(agent_ref, *, user_id, settings=None):
    """Reauthorize and load an exact stored agent for a trusted execution actor."""
    settings = _settings(settings)
    reference = agent_reference(agent_ref, user_id)
    _assert_scope_access(user_id, reference["scope_type"], reference["scope_id"], settings)
    if reference["scope_type"] == "global":
        import_module("functions_governance").ensure_governance_access(
            "governance_global_agents_usage", user_id,
            item_entity_type="global_agent", item_id=reference["id"],
        )
    agent = _read_agent(reference)
    if str(agent.get("id") or "") != reference["id"] or agent.get("is_enabled", True) is not True:
        raise LookupError(UNAVAILABLE_MESSAGE)
    if agent.get("agent_type", "local") not in AGENT_TYPES:
        raise ValueError("This agent type cannot be called.")
    return agent


def _authorize_action(action, user_id, scope_type, scope_id, settings):
    if action.get("is_enabled", True) is not True:
        raise PermissionError("This Call agent action is disabled.")
    governance = import_module("functions_governance")
    if scope_type == "global":
        governance.ensure_global_action_access(user_id, action)
    else:
        flag = "allow_user_plugins" if scope_type == "personal" else "allow_group_plugins"
        if not settings.get(flag, False):
            raise PermissionError("Actions are disabled in this workspace.")
        feature = "governance_user_actions" if scope_type == "personal" else "governance_group_actions"
        governance.ensure_action_type_access(feature, user_id, AGENT_PLUGIN_TYPE, scope_type)


def validate_agent_action_for_scope(manifest, *, user_id, scope_type, scope_id, settings=None):
    """Validate a new/edited Call agent action before it can be persisted."""
    if not isinstance(manifest, dict) or manifest.get("type") != AGENT_PLUGIN_TYPE:
        return manifest
    result = validate_agent_action_manifest(manifest)
    settings = _settings(settings)
    scope_type = _scope(scope_type)
    _assert_scope_access(user_id, scope_type, scope_id, settings, manage=True)
    target = result["additionalFields"]["target_agent"]
    _assert_target_scope(target, scope_type, scope_id, settings)
    # A disabled action may be edited, but it must still reference an authorized target.
    if scope_type != "global":
        _authorize_action({**result, "is_enabled": True}, user_id, scope_type, scope_id, settings)
    resolve_delegation_agent(target, user_id=user_id, settings=settings)
    return result


def _agent_actions(scope_type, scope_id, settings):
    sources = [(scope_type, scope_id)]
    if scope_type != "global" and settings.get("merge_global_semantic_kernel_with_workspace", False):
        sources.append(("global", "global"))
    results = []
    for action_scope, action_scope_id in sources:
        for record in _list_records("actions", action_scope, action_scope_id):
            if record.get("type") == AGENT_PLUGIN_TYPE:
                action = deepcopy(record)
                action["_delegation_scope_type"] = action_scope
                action["_delegation_scope_id"] = action_scope_id
                results.append(action)
    return results


def _resolve_attached_action(action_id, caller, user_id, settings):
    if action_id not in (caller.get("actions_to_load") or []):
        raise PermissionError("This Call agent action is not attached to the calling agent.")
    reference = agent_reference(caller, user_id)
    matches = [
        action for action in _agent_actions(reference["scope_type"], reference["scope_id"], settings)
        if action.get("id") == action_id
    ]
    if len(matches) != 1:
        raise LookupError("The attached Call agent action is unavailable or ambiguous.")
    action = validate_agent_action_manifest(matches[0])
    action_scope = action["_delegation_scope_type"]
    action_scope_id = action["_delegation_scope_id"]
    _authorize_action(action, user_id, action_scope, action_scope_id, settings)
    target_ref = action["additionalFields"]["target_agent"]
    _assert_target_scope(target_ref, action_scope, action_scope_id, settings)
    _assert_target_scope(target_ref, reference["scope_type"], reference["scope_id"], settings)
    target = resolve_delegation_agent(target_ref, user_id=user_id, settings=settings)
    if agent_reference(target, user_id) == reference:
        raise ValueError("An agent cannot call itself.")
    return action, target


def resolve_delegation_call(action_id, *, caller_agent, user_id, settings=None):
    """Return freshly authorized (caller, attached action, target), never name fallbacks."""
    settings = _settings(settings)
    caller = resolve_delegation_agent(caller_agent, user_id=user_id, settings=settings)
    if caller.get("agent_type", "local") != "local":
        raise PermissionError("Only local agents can call SimpleChat agent actions.")
    action, target = _resolve_attached_action(
        _identifier(action_id, "Action ID", max_bytes=1023), caller, user_id, settings,
    )
    return caller, action, target


def validate_agent_delegation_bindings(agent, *, user_id, scope_type, scope_id, settings=None, existing_agent=None):
    """Check agent-action attachments while leaving other action types unchanged."""
    references = agent.get("actions_to_load") or []
    if not references:
        return
    if (
        existing_agent is not None
        and references == (existing_agent.get("actions_to_load") or [])
        and agent.get("agent_type", "local") == existing_agent.get("agent_type", "local")
    ):
        # Unrelated edits (including administrator model migrations) do not reassign
        # these capabilities. Actual execution still reauthorizes every stored call.
        return
    settings = _settings(settings)
    actions = _agent_actions(scope_type, scope_id, settings)
    selected = [action for action in actions if action.get("id") in references or action.get("name") in references]
    if not selected:
        return
    _assert_scope_access(user_id, scope_type, scope_id, settings, manage=True)
    if agent.get("agent_type", "local") != "local":
        raise ValueError("Foundry-backed agents cannot attach SimpleChat Call agent actions.")
    caller = {
        **agent, "scope_type": scope_type, "scope_id": scope_id,
        "is_global": scope_type == "global", "is_group": scope_type == "group",
    }
    for action in selected:
        if action.get("id") not in references:
            raise ValueError("Attach Call agent actions by their stored action ID, not their name.")
        _resolve_attached_action(action["id"], caller, user_id, settings)


def build_agent_delegation_catalog(user_id, scope_type, group_id=None):
    """Project authorized targets for the editor; never return target configuration."""
    settings = _settings(None)
    scope_type, scope_id = resolve_delegation_scope(user_id, scope_type, group_id, settings=settings)
    try:
        _assert_scope_access(user_id, scope_type, scope_id, settings, manage=True)
        action_flag = {"personal": "allow_user_plugins", "group": "allow_group_plugins"}.get(scope_type)
        can_manage = not action_flag or bool(settings.get(action_flag, False))
        if can_manage and scope_type != "global":
            feature = "governance_user_actions" if scope_type == "personal" else "governance_group_actions"
            import_module("functions_governance").ensure_action_type_access(
                feature, user_id, AGENT_PLUGIN_TYPE, scope_type,
            )
    except PermissionError:
        can_manage = False
    sources = [(scope_type, scope_id)]
    if scope_type != "global" and settings.get("merge_global_semantic_kernel_with_workspace", False):
        sources.append(("global", "global"))
    targets = []
    for target_scope, target_scope_id in sources:
        for record in _list_records("agents", target_scope, target_scope_id):
            if record.get("agent_type", "local") not in AGENT_TYPES:
                continue
            ref = {"id": record.get("id"), "scope_type": target_scope, "scope_id": target_scope_id}
            try:
                agent = resolve_delegation_agent(ref, user_id=user_id, settings=settings)
            except (PermissionError, LookupError):
                continue
            except ValueError:
                import_module("functions_appinsights").log_event(
                    "[AGENT_DELEGATION] Excluded an invalid stored agent reference from the catalogue.",
                    level="WARNING", extra={"scope_type": target_scope},
                )
                continue
            targets.append({
                "id": agent["id"],
                "name": str(agent.get("name") or ""),
                "display_name": str(agent.get("display_name") or agent.get("name") or agent["id"]),
                "description": str(agent.get("description") or ""),
                "agent_type": agent.get("agent_type", "local"),
                "scope_type": target_scope,
                "scope_id": target_scope_id,
                "is_global": target_scope == "global",
                "is_group": target_scope == "group",
                "group_id": target_scope_id if target_scope == "group" else None,
            })
    targets.sort(key=lambda target: (target["display_name"].casefold(), target["scope_type"], target["id"]))
    return {"targets": targets, "can_manage": can_manage, "scope_type": scope_type, "scope_id": scope_id}


def _string_references(values, label):
    if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{label} must be an array of stored action references.")
    return list(dict.fromkeys(values))


def _visible_binding_action_ids(actions, user_id, scope_type):
    """Match action-list visibility so editing cannot drop unlisted existing references."""
    governance = import_module("functions_governance")
    visible = set()
    for action in actions:
        action_scope = action["_delegation_scope_type"]
        try:
            if scope_type != "global" and action_scope == "global":
                if action.get("is_enabled", True) is not True:
                    continue
                governance.ensure_global_action_access(user_id, action)
            elif scope_type != "global":
                feature = "governance_user_actions" if scope_type == "personal" else "governance_group_actions"
                governance.ensure_action_type_access(feature, user_id, AGENT_PLUGIN_TYPE, scope_type)
        except PermissionError:
            continue
        visible.add(action["id"])
    return visible


def update_agent_delegation_bindings(user_id, scope_type, agent_id, payload, group_id=None):
    """Atomically replace only agent-action bindings, preserving all other agent fields."""
    # Only mutation paths require these SDK/cache dependencies.
    from azure.core import MatchConditions
    from azure.cosmos.exceptions import CosmosHttpResponseError
    from functions_activity_logging import log_agent_update
    from functions_chat_bootstrap_cache import (
        bump_chat_bootstrap_global_cache_version,
        bump_chat_bootstrap_user_cache_version,
    )

    if not isinstance(payload, dict) or set(payload) != {"action_ids", "expected_actions_to_load"}:
        raise ValueError("Supply action_ids and the original expected_actions_to_load.")
    selected = _string_references(payload["action_ids"], "action_ids")
    _string_references(payload["expected_actions_to_load"], "expected_actions_to_load")
    expected = payload["expected_actions_to_load"]
    settings = _settings(None)
    scope_type, scope_id = resolve_delegation_scope(user_id, scope_type, group_id, manage=True, settings=settings)
    reference = normalize_agent_target({"id": agent_id, "scope_type": scope_type, "scope_id": scope_id})
    current = _read_agent(reference)
    if current.get("agent_type", "local") != "local":
        raise ValueError("Only local agents can attach Call agent actions.")
    original = current.get("actions_to_load") or []
    if original != expected:
        raise AgentDelegationConflictError("Agent actions changed. Reload the agent before saving.")
    candidates = _agent_actions(scope_type, scope_id, settings)
    agent_ids = _visible_binding_action_ids(candidates, user_id, scope_type)
    if any(action_id not in agent_ids for action_id in selected):
        raise ValueError("Select available Call agent actions from this workspace.")
    updated = {**current, "actions_to_load": [value for value in original if value not in agent_ids] + selected}
    validate_agent_delegation_bindings(
        {**current, "actions_to_load": selected},
        user_id=user_id, scope_type=scope_type, scope_id=scope_id, settings=settings,
    )
    etag = current.get("_etag")
    if not etag:
        raise AgentDelegationConflictError("The agent version is unavailable. Reload before saving.")
    now = datetime.now(timezone.utc).isoformat()
    operations = [
        {"op": "set", "path": "/actions_to_load", "value": updated["actions_to_load"]},
        {"op": "set", "path": "/modified_by", "value": user_id},
        {"op": "set", "path": "/modified_at", "value": now},
        {"op": "set", "path": "/updated_at" if scope_type == "global" else "/last_updated", "value": now},
    ]
    try:
        _container("agents", scope_type).patch_item(
            item=reference["id"],
            partition_key=reference["id"] if scope_type == "global" else scope_id,
            patch_operations=operations, etag=etag, match_condition=MatchConditions.IfNotModified,
        )
    except CosmosHttpResponseError as exc:
        if exc.status_code == 412:
            raise AgentDelegationConflictError("Agent actions changed. Reload before saving.") from exc
        raise
    if scope_type == "personal":
        bump_chat_bootstrap_user_cache_version(user_id, reason="agent_delegation_updated")
    else:
        bump_chat_bootstrap_global_cache_version(reason="agent_delegation_updated")
    builtins.kernel_reload_needed = True
    log_agent_update(
        user_id=user_id, agent_id=reference["id"], agent_name=current.get("name", ""),
        agent_display_name=current.get("display_name", ""), scope=scope_type,
        **({"group_id": scope_id} if scope_type == "group" else {}),
    )
    return {
        "id": reference["id"], "name": current.get("name", ""),
        "display_name": current.get("display_name", ""), "agent_type": "local",
        "is_global": scope_type == "global", "is_group": scope_type == "group",
        "actions_to_load": updated["actions_to_load"],
    }
