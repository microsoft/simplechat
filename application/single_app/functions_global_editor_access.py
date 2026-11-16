# functions_global_editor_access.py
"""Orchestration for the V2 Admin Settings global agent and action editors.

The classic ``/api/admin/agents`` and ``/api/admin/plugins`` routes save whole
documents addressed by name, with no revision. These routes serve the V2 agent and
action editors instead, so global records get the contract personal and group
records already have: reads answer with ``{record, revision, secret_paths,
read_only}``, writes accept ``{updates, expected_revision, clear_secret_paths,
removed_paths}``, and a write made against a stale revision is refused with nothing
written. Persistence, secret handling and the conditional writes are the shared
engine in ``functions_workspace_authoring``; the routes enforce the Admin role.

Enabling, disabling and choosing the default agent stay on the classic routes, which
already update those fields without rewriting stored secret references.
"""

import json
import logging
import re
from importlib import import_module

from flask import jsonify, request
from werkzeug.exceptions import HTTPException

from functions_appinsights import log_event
from functions_settings import get_settings, update_settings
from functions_workspace_authoring import (
    apply_global_action_write,
    apply_global_agent_write,
    build_global_agent_editor_options,
    build_secret_reminder_defaults,
    delete_global_editor_record,
    editor_error_response,
    editor_resource,
    list_global_editor_records,
    log_committed_global_editor_change,
    project_editor_record,
    read_global_editor_record,
)


INVALID_GLOBAL_RESOURCE_ID = re.compile(r"[/\\?#,\x00-\x1f\x7f]")


class GlobalEditorError(HTTPException):
    """A stable, non-sensitive failure at the global editor boundary."""

    def __init__(self, message, status_code):
        super().__init__(description=message)
        self.code = status_code


def _validate_identifier(value, label):
    if (
        not isinstance(value, str) or not value or len(value) > 512
        or value != value.strip() or value in (".", "..")
        or INVALID_GLOBAL_RESOURCE_ID.search(value)
    ):
        raise GlobalEditorError(f"Invalid {label}.", 400)


def global_editor_error_response(exc):
    """Map boundary errors and shared editor-engine errors to HTTP responses."""
    if isinstance(exc, GlobalEditorError):
        response = jsonify({"error": exc.description})
        response.headers["Cache-Control"] = "no-store"
        return response, exc.code
    return editor_error_response(exc)


def reject_query_parameters():
    """These routes take no query parameters; a stray one is refused, not ignored."""
    if request.args:
        raise GlobalEditorError("This request does not accept query parameters.", 400)


def reject_request_body():
    if request.get_data():
        raise GlobalEditorError("This read does not accept a request body.", 400)


def read_json_body():
    """Parse a JSON object body, rejecting duplicate keys so a smuggled second value
    cannot shadow a validated one."""
    def unique_fields(pairs):
        payload = {}
        for key, value in pairs:
            if key in payload:
                raise GlobalEditorError("Duplicate fields are not supported.", 400)
            payload[key] = value
        return payload

    if not request.is_json:
        raise GlobalEditorError("A JSON object is required for this action.", 400)
    try:
        body = json.loads(request.get_data(), object_pairs_hook=unique_fields)
    except (ValueError, UnicodeDecodeError) as error:
        raise GlobalEditorError("Provide valid JSON with no duplicate fields.", 400) from error
    if not isinstance(body, dict):
        raise GlobalEditorError("A JSON object is required for this action.", 400)
    return body


def _resource(record, kind):
    # Global records are read-only everywhere else; here they are the administrator's own.
    return editor_resource(record, kind, global_scope=True, read_only=False)


def selected_agent_name(settings):
    """The default global agent, which settings store by name."""
    selected = settings.get("global_selected_agent")
    if isinstance(selected, dict):
        return str(selected.get("name") or "")
    return selected if isinstance(selected, str) else ""


def _follow_default_agent_rename(existing, saved, settings):
    """Keep the default agent selected when it is renamed.

    The selection is stored by name, so a rename would otherwise leave it naming an
    agent that no longer exists. The agent is already saved when this runs; a failure
    here is logged rather than reported as a failed save.
    """
    old_name = existing.get("name")
    new_name = saved.get("name")
    selected = settings.get("global_selected_agent")
    if old_name == new_name or not isinstance(selected, dict) or selected.get("name") != old_name:
        return
    try:
        if not update_settings({"global_selected_agent": {**selected, "name": new_name}}):
            raise RuntimeError("The settings update was not saved.")
    except Exception as exc:
        log_event(
            "[GLOBAL_AGENTS] The renamed default agent could not be reselected.",
            level=logging.WARNING,
            extra={"agent_id": saved.get("id", ""), "error_type": type(exc).__name__},
        )


def list_global_agents():
    settings = get_settings()
    agents = [
        project_editor_record(record, "agents", global_scope=True)
        for record in list_global_editor_records("agents")
    ]
    return {"agents": agents, "selected_agent_name": selected_agent_name(settings)}, 200


def get_global_agent(agent_id):
    _validate_identifier(agent_id, "agent identifier")
    return _resource(read_global_editor_record("agents", agent_id), "agents"), 200


def get_global_agent_options():
    settings = get_settings()
    # Bound lazily so this module does not import the agent route blueprint at load.
    route_agents = import_module("route_backend_agents")
    endpoints = route_agents.build_combined_model_endpoints(settings)
    return build_global_agent_editor_options(settings, endpoints), 200


def create_global_agent(user_id, body, prepare):
    settings = get_settings()
    saved = apply_global_agent_write(user_id, None, body, prepare, settings)
    log_committed_global_editor_change("agents", user_id, saved, "creation")
    return _resource(saved, "agents"), 201


def update_global_agent(user_id, agent_id, body, prepare):
    _validate_identifier(agent_id, "agent identifier")
    settings = get_settings()
    existing = read_global_editor_record("agents", agent_id)
    saved = apply_global_agent_write(user_id, existing, body, prepare, settings)
    _follow_default_agent_rename(existing, saved, settings)
    log_committed_global_editor_change("agents", user_id, saved, "update")
    return _resource(saved, "agents"), 200


def delete_global_agent_record(user_id, agent_id):
    _validate_identifier(agent_id, "agent identifier")
    settings = get_settings()
    existing = read_global_editor_record("agents", agent_id)
    delete_global_editor_record("agents", user_id, existing, settings)
    log_committed_global_editor_change("agents", user_id, existing, "deletion")
    return {"success": True}, 200


def list_global_actions():
    actions = [
        project_editor_record(record, "actions", global_scope=True)
        for record in list_global_editor_records("actions")
    ]
    return {"actions": actions}, 200


def get_global_action(action_id):
    _validate_identifier(action_id, "action identifier")
    return _resource(read_global_editor_record("actions", action_id), "actions"), 200


def get_global_action_options():
    """The tenant-level Key Vault reminder defaults the action editor shows."""
    return {"secret_reminders": build_secret_reminder_defaults(get_settings())}, 200


def create_global_action(user_id, body, prepare):
    settings = get_settings()
    saved = apply_global_action_write(user_id, None, body, prepare, settings)
    log_committed_global_editor_change("actions", user_id, saved, "creation")
    return _resource(saved, "actions"), 201


def update_global_action(user_id, action_id, body, prepare):
    _validate_identifier(action_id, "action identifier")
    settings = get_settings()
    existing = read_global_editor_record("actions", action_id)
    saved = apply_global_action_write(user_id, existing, body, prepare, settings)
    log_committed_global_editor_change("actions", user_id, saved, "update")
    return _resource(saved, "actions"), 200


def delete_global_action_record(user_id, action_id):
    _validate_identifier(action_id, "action identifier")
    settings = get_settings()
    existing = read_global_editor_record("actions", action_id)
    delete_global_editor_record("actions", user_id, existing, settings)
    log_committed_global_editor_change("actions", user_id, existing, "deletion")
    return {"success": True}, 200
