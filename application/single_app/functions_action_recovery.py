# functions_action_recovery.py
"""Private pre-model action recovery, using the existing expiring interaction store."""

from hashlib import sha256
import hmac
import json
import logging
import time
from urllib.parse import quote

from azure.cosmos.exceptions import CosmosResourceExistsError
from flask import current_app, g, has_request_context, request, session

from action_runtime_contracts import (
    ActionLoadRequired, ActionRecoveryError, ActionRecoveryRequired, action_binding_key,
)
from functions_action_manifest import get_action_origin
import functions_action_credential_state as state


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def request_fingerprint(body):
    return _digest({key: value for key, value in body.items() if key != "action_recovery"})


def manifest_fingerprint(manifests):
    return _digest(sorted(
        [(action_binding_key(manifest), dict(manifest)) for manifest in manifests],
        key=lambda item: item[0],
    ))


def _actor():
    # Authentication and interaction services are initialized by the web owner.
    from functions_authentication import get_current_user_id

    return get_current_user_id()


def apply_action_recovery(manifests):
    """Reauthorize the unchanged action set before consuming a one-shot decision."""
    if not has_request_context() or getattr(g, "action_health_probe", False):
        return manifests
    body = request.get_json(silent=True) or {}
    decision = body.get("action_recovery")
    if decision is None:
        return manifests
    expected = session.get("action_credentials_csrf_token") or ""
    if not expected or not hmac.compare_digest(expected, request.headers.get("X-CSRFToken") or ""):
        raise ActionRecoveryError()
    if type(decision) is not dict or set(decision) != {"id", "decision"} or decision["decision"] != "continue":
        raise ActionRecoveryError()
    from functions_action_credentials import authorize_conversation

    user_id = _actor()
    authorize_conversation(user_id, body.get("conversation_id"))
    item = state.read(user_id, decision["id"], record_type="action_recovery")
    if (
        item["conversation_id"] != body.get("conversation_id")
        or item["request_fingerprint"] != request_fingerprint(body)
        or item["manifest_fingerprint"] != manifest_fingerprint(manifests)
    ):
        raise ActionRecoveryError()
    claim = getattr(g, "action_recovery_claim", None)
    if claim != item["id"]:
        if item["status"] != "pending":
            raise ActionRecoveryError()
        state.replace(user_id, item, {"status": "continued"}, item["_etag"])
        g.action_recovery_claim = item["id"]
    failed = set(item["failed"])
    g.action_recovery_excluded_keys = failed
    return [manifest for manifest in manifests if action_binding_key(manifest) not in failed]


def _remediation(manifest, user_id):
    """Derive UI hints from current action policy, never from the agent's scope."""
    from functions_group import assert_group_role, find_group_by_id
    from functions_group_action_policy import group_action_management_operations
    from functions_settings import get_settings

    origin = get_action_origin(manifest)
    if origin is None or not origin.action_id:
        return {"scope": "unavailable", "can_report": False}
    settings = get_settings()
    roles = session.get("user", {}).get("roles", [])
    action_id = quote(origin.action_id, safe="")
    can_edit = (
        origin.scope_type == "personal" and origin.scope_id == user_id
        and settings.get("allow_user_plugins", False)
    )
    if origin.scope_type == "group":
        role = assert_group_role(user_id, origin.scope_id, ("Owner", "Admin", "DocumentManager", "User"))
        group = find_group_by_id(origin.scope_id)
        can_edit = "edit" in group_action_management_operations(user_id, group, role, settings)
    elif origin.scope_type == "global":
        can_edit = "Admin" in roles
    result = {"scope": origin.scope_type, "can_report": True}
    if can_edit:
        if origin.scope_type == "personal":
            result["edit_url"] = f"/v2/workspace/actions/{action_id}"
        elif origin.scope_type == "group":
            result["edit_url"] = f"/v2/groups/{quote(origin.scope_id, safe='')}/actions/{action_id}"
        else:
            result["edit_url"] = f"/v2/admin/actions/{action_id}"
    return result


def recovery_payload(error, body, *, check_only=False):
    """Project safe diagnostics; keep the unsent request in actor-private state."""
    from functions_action_catalog import _action_ref, resolve_action_manifest
    from functions_action_credentials import authorize_conversation

    user_id = _actor()
    conversation_id = body.get("conversation_id")
    if not check_only:
        authorize_conversation(user_id, conversation_id)
    failed = set(error.failures)
    actions = []
    references = {}
    revisions = {}
    for manifest in error.manifests:
        key = action_binding_key(manifest)
        if key not in failed:
            continue
        origin = get_action_origin(manifest)
        actions.append({
            "key": key,
            "name": str(manifest.get("displayName") or manifest.get("name") or "Assigned action")[:200],
            "reason": "This action could not be loaded. Its capabilities are unavailable for this request.",
            "code": "action_load_failed",
            "capabilities": [
                str(name).replace("_", " ") for name in manifest.get("enabled_functions", [])
                if isinstance(name, str)
            ] or ["All configured operations for this action"],
            **_remediation(manifest, user_id),
        })
        if origin and origin.action_id:
            references[key] = [origin.scope_type, origin.scope_id, origin.action_id]
            current = resolve_action_manifest(user_id, _action_ref(*references[key]))
            revisions[key] = _digest(current)
    selection = body.get("agent_info")
    payload = {
        "type": "action_recovery_required",
        "conversation_id": conversation_id, "actions": actions,
        "agent_name": str(selection.get("display_name") or selection.get("name") or "Selected agent")[:200]
        if isinstance(selection, dict) else "Selected agent",
        "all_actions_unavailable": len(failed) == len(error.manifests),
        "message": "Review unavailable actions before continuing. No model or action has run.",
    }
    if check_only:
        return payload
    now = time.time()
    request_hash = request_fingerprint(body)
    manifests_hash = manifest_fingerprint(error.manifests)
    item_id = "action_recovery_" + state.key_for(conversation_id, request_hash, manifests_hash, sorted(failed))
    fields = {
        "id": item_id, "record_type": "action_recovery", "conversation_id": conversation_id,
        "request_fingerprint": request_hash, "manifest_fingerprint": manifests_hash,
        "failed": sorted(failed), "references": references, "action_revisions": revisions, "payload": payload,
        "agent_fingerprint": getattr(g, "action_recovery_agent_fingerprint", None),
        "status": "pending", "created_at": now, "expires_at": now + 1800, "ttl": 1800,
    }
    try:
        item = state.create(user_id, fields)
    except CosmosResourceExistsError:
        item = state.read(user_id, item_id, record_type="action_recovery")
    # The existing interaction checkpoint owner enforces its bounded, private
    # storage contract. None of this request is copied into a notification.
    state.checkpoint(user_id, item_id + "_draft", conversation_id, {
        key: value for key, value in body.items() if key != "action_recovery"
    })
    return {**payload, "id": item["id"]}


def check_chat_actions(body, *, check_only=False, admit=False):
    """Construction is a local availability check, not a remote credential test."""
    from semantic_kernel import Kernel
    from route_backend_chats import _resolve_canonical_chat_agent
    from semantic_kernel_loader import load_agent_core_plugins, load_agent_specific_plugins
    from functions_action_credentials import authorize_conversation
    from functions_settings import get_settings
    from action_credential_contracts import ActionCredentialsRequired
    from functions_m365_approvals import M365ApprovalRequired
    from m365_interaction import M365SignInRequired

    user_id = _actor()
    # The shared bridge has already persisted its turn and authorized its source.
    # It must never create a personal-chat replay opportunity.
    shared_admission = admit and bool(body.get("m365_collaboration_message_id"))
    if shared_admission and body.get("action_recovery") is not None:
        raise ActionRecoveryError()
    if not check_only and not shared_admission and not (admit and getattr(g, "m365_new_conversation", False)):
        authorize_conversation(user_id, body.get("conversation_id"))
    settings = get_settings()
    agent = _resolve_canonical_chat_agent(user_id, settings, body.get("agent_info"))
    if body.get("agent_info") and agent is None:
        raise PermissionError("This agent is unavailable.")
    if not agent:
        return {"state": "not_checked", "message": "No local agent is selected."}
    if agent.get("agent_type", "local") != "local":
        return {"state": "not_checked", "message": "Remote agent actions are checked by their provider."}
    g.action_recovery_agent_fingerprint = _digest(agent)
    previous = getattr(g, "action_health_probe", False)
    g.action_health_probe = not admit
    try:
        kernel = Kernel()
        load_agent_core_plugins(kernel, settings)
        load_agent_specific_plugins(
            kernel, agent.get("actions_to_load") or [], settings,
            "global" if agent.get("is_global") else "group" if agent.get("is_group") else "per-user",
            user_id=user_id, group_id=agent.get("group_id"),
            agent_other_settings=agent.get("other_settings"), allow_agent_actions=True,
        )
    except (ActionCredentialsRequired, M365ApprovalRequired, M365SignInRequired):
        if admit:
            raise
        return {"state": "not_checked", "message": "Complete the existing credential, sign-in or approval flow when sending."}
    except ActionLoadRequired as error:
        if shared_admission:
            raise
        if admit and getattr(g, "m365_new_conversation", False):
            from route_backend_chats import _create_personal_conversation

            g.m365_initial_conversation = _create_personal_conversation(user_id, body["conversation_id"])
            g.m365_new_conversation = False
        payload = recovery_payload(error, body, check_only=check_only)
        if admit:
            raise ActionRecoveryRequired(payload) from error
        return payload
    finally:
        g.action_health_probe = previous
    return {"state": "ready", "message": "Actions loaded. Service sign-in and approvals are checked when used."}


def validate_recovery_agent(agent, body):
    """Catch removed assignments and changed agent configuration, even with no tools."""
    g.action_recovery_agent_fingerprint = _digest(agent)
    g.action_recovery_selected_agent = agent
    decision = body.get("action_recovery")
    if decision is None:
        return
    if type(decision) is not dict or type(decision.get("id")) is not str:
        raise ActionRecoveryError()
    item = state.read(_actor(), decision["id"], record_type="action_recovery")
    if item["agent_fingerprint"] != g.action_recovery_agent_fingerprint:
        raise ActionRecoveryError()


def read_recovery(recovery_id):
    from functions_action_credentials import authorize_conversation

    user_id = _actor()
    item = state.read(user_id, recovery_id, record_type="action_recovery")
    authorize_conversation(user_id, item["conversation_id"])
    if item["status"] != "pending":
        raise ActionRecoveryError()
    checkpoint = state.read(user_id, recovery_id + "_draft", record_type="credential_checkpoint")
    body = checkpoint["value"]
    # Re-resolve the agent and its scoped actions. A stored incident is not an
    # ongoing grant to read an action whose permissions were since removed.
    current = check_chat_actions(body)
    if current.get("state") in {"ready", "not_checked"}:
        current = {
            **item["payload"], "id": item["id"], "actions": [],
            "all_actions_unavailable": False, "ready": True,
        }
    return {"recovery": current, "pending_body": body}


def report_action_failure(recovery_id, action_key):
    """Report one authorized incident using the existing idempotent notifier."""
    from functions_action_catalog import _action_ref, resolve_action_manifest
    from functions_action_credentials import authorize_conversation
    from functions_group import assert_group_role, find_group_by_id
    from functions_notifications import create_notification
    from functions_settings import get_settings
    from functions_appinsights import log_event

    user_id = _actor()
    item = state.read(user_id, recovery_id, record_type="action_recovery")
    authorize_conversation(user_id, item["conversation_id"])
    reference = item["references"].get(action_key)
    if not reference or action_key not in item["failed"]:
        raise PermissionError("This report is unavailable.")
    scope, scope_id, action_id = reference
    manifest = resolve_action_manifest(user_id, _action_ref(scope, scope_id, action_id))
    if item.get("action_revisions", {}).get(action_key) != _digest(manifest):
        raise ActionRecoveryError()
    remediation = _remediation(manifest, user_id)
    if not remediation["can_report"]:
        raise PermissionError("This report is unavailable.")
    audience = {"personal_workspace_owner_id": scope_id} if scope == "personal" else {"roles": ["Admin"]}
    recipients = []
    if scope == "group":
        assert_group_role(user_id, scope_id, ("Owner", "Admin", "DocumentManager", "User"))
        group = find_group_by_id(scope_id)
        from functions_group_action_policy import group_action_write_roles
        from functions_group import get_user_role_in_group

        candidates = [(group.get("owner") or {}).get("id"), *(group.get("admins") or [])]
        recipients = []
        for candidate in candidates:
            candidate_id = candidate
            if candidate_id and get_user_role_in_group(group, candidate_id) in group_action_write_roles(get_settings()):
                recipients.append(candidate_id)
        if not recipients:
            raise LookupError("The responsible group managers could not be resolved.")
    try:
        for recipient in recipients or [None]:
            notification = create_notification(
                user_id=recipient,
                assignment=None if recipient else audience,
                notification_type="action_load_failure",
                title="An assigned action could not load",
                message="An authorized user reported a loading failure. Review this action's configuration.",
                link_url=_recipient_edit_url(scope, scope_id, action_id),
                metadata={
                    "action_scope": scope, "action_id": action_id, "failure_code": "action_load_failed",
                    "action_name": str(manifest.get("displayName") or manifest.get("name") or "Assigned action")[:200],
                    "application_version": current_app.config.get("VERSION", "unknown"),
                    "correlation_id": "action-load-" + state.key_for(item["id"], action_key)[:24],
                },
                idempotency_key=f"action-load:{item['id']}:{action_key}:{recipient or scope}",
                strict=True,
            )
            if not notification:
                raise RuntimeError("Notification delivery could not be confirmed.")
    except Exception as error:
        log_event("[PLUGINS] Action failure report could not be confirmed.", level=logging.WARNING,
                  extra={"error_type": type(error).__name__})
        raise
    return {"reported": True}


def _recipient_edit_url(scope, scope_id, action_id):
    action_id = quote(action_id, safe="")
    if scope == "global":
        return f"/v2/admin/actions/{action_id}"
    if scope == "group":
        return f"/v2/groups/{quote(scope_id, safe='')}/actions/{action_id}"
    return f"/v2/workspace/actions/{action_id}"
