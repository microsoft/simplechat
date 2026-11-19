# functions_agent_credential_recovery.py
"""Permission-aware, secret-free chat recovery for agent credentials.

Editor policy and storage modules are resolved only for a credential failure.
Normal model errors and the bootstrap-free runtime error contract do not import
the workspace editor or initialize its settings/storage dependency chain.
"""

from importlib import import_module
import re
from urllib.parse import quote

from flask import has_request_context, session

from agent_credential_contracts import AgentCredentialReentryRequired


_INVALID_RESOURCE_ID = re.compile(r"[/\\?#,\x00-\x1f\x7f]")
_PUBLIC_SCOPES = {"user": "personal", "group": "group", "global": "global"}


def _valid_identifier(value):
    return (
        isinstance(value, str) and 0 < len(value) <= 512
        and value == value.strip() and value not in (".", "..")
        and not _INVALID_RESOURCE_ID.search(value)
    )


def model_configuration_error_payload(error):
    """Reauthorize the exact failed resource before advertising an editor link."""
    payload = {"error": error.public_message, "error_code": "model_configuration_invalid"}
    if not isinstance(error, AgentCredentialReentryRequired) or not has_request_context():
        return payload
    user = session.get("user") or {}
    user_id = user.get("oid")
    scope, owner_id, agent_id = error.agent_scope, error.agent_owner_id, error.agent_id
    if not user_id or scope not in _PUBLIC_SCOPES or not _valid_identifier(agent_id):
        return payload
    if scope == "user" and owner_id != user_id:
        return payload
    if scope == "group" and not _valid_identifier(owner_id):
        return payload
    if scope == "global" and owner_id != "global":
        return payload

    subject = "Agent connection settings" if error.incomplete else "Agent credentials"
    contact = "a group owner" if scope == "group" else "a site administrator"
    recovery = {"scope": _PUBLIC_SCOPES[scope], "can_edit": False}
    payload.update({
        "error": f"{subject} need updating. Please contact {contact} to update this agent.",
        "agent_credential_recovery": recovery,
    })

    if scope == "user":
        authoring = import_module("functions_workspace_authoring")
        settings = import_module("functions_settings").get_settings()
        try:
            authoring.ensure_editor_access("agents", user_id, settings)
        except PermissionError:
            return payload
        agents = import_module("functions_personal_agents")
        record = agents.get_personal_agent(
            user_id, agent_id, return_type=agents.SecretReturnType.NAME,
        )
        base_path = "/v2/workspace/agents"
        if not record or record.get("user_id") != user_id:
            return payload
    elif scope == "group":
        settings = import_module("functions_settings").get_settings()
        if not settings.get("enable_group_workspaces", False):
            return payload
        access = import_module("functions_group_agent_access")
        try:
            access.require_group_agent_write_context(user_id, owner_id, "edit")
        except access.GroupAgentError as denied:
            if denied.code not in (400, 401, 403, 404):
                raise
            return payload
        agents = import_module("functions_group_agents")
        record = agents.get_group_agent(
            owner_id, agent_id, return_type=agents.SecretReturnType.NAME,
        )
        base_path = f"/v2/groups/{quote(owner_id, safe='')}/agents"
        if not record or record.get("group_id") != owner_id:
            return payload
    else:
        if "Admin" not in (user.get("roles") or []):
            return payload
        agents = import_module("functions_global_agents")
        record = agents.get_global_agent(agent_id, return_type=agents.SecretReturnType.NAME)
        base_path = "/v2/admin/agents"

    if not record or record.get("id") != agent_id:
        return payload
    recovery.update({
        "can_edit": True,
        "edit_url": f"{base_path}/{quote(agent_id, safe='')}?section=model",
    })
    payload["error"] = (
        f"{subject} need updating. Update the affected values in this agent's "
        "Model & connection settings."
    )
    return payload
