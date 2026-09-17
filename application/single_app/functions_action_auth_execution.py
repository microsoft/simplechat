# functions_action_auth_execution.py
"""Private authentication control responses at browser execution boundaries."""

import json
import logging

from azure.core.exceptions import AzureError
from flask import g, jsonify

from functions_action_auth import ActionAuthConflict, ActionAuthStorageError, ActionCredentialsRequired
from functions_action_auth_state import authorize_action_auth_execution
from functions_appinsights import log_event


def action_auth_control_payload(error, *, execution_started=False):
    payload = error.to_payload()
    action_ref = getattr(error, "action_ref", None)
    if isinstance(action_ref, str) and action_ref.startswith("action:v1:"):
        payload["action_ref"] = action_ref
    payload.update({
        "type": "action_credentials_required",
        "error_code": "action_credentials_required",
        "execution_started": execution_started,
    })
    return payload


def action_auth_error_response(error, *, execution_started=False):
    if isinstance(error, ActionCredentialsRequired):
        payload = action_auth_control_payload(error, execution_started=execution_started)
        status = 409
    elif isinstance(error, ActionAuthConflict):
        payload = {
            "error": "The authentication request changed or was already used. Check the selected action again.",
            "error_code": "action_auth_conflict",
        }
        status = 409
    elif isinstance(error, PermissionError):
        payload = {"error": "You are not permitted to use this action or authentication request."}
        status = 403
    elif isinstance(error, LookupError):
        payload = {"error": "The action or authentication request is unavailable."}
        status = 404
    elif isinstance(error, (AzureError, ActionAuthStorageError)):
        payload = {"error": "Credential storage is temporarily unavailable. Please try again."}
        status = 503
    else:
        payload = {"error": "Invalid action authentication request."}
        status = 400
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, status


def _action_auth_guard_stamp(user_id, payload):
    selection = {
        key: payload.get(key) for key in ("agent_info", "action_ref", "run_id")
    }
    return user_id, payload.get("action_auth_request_id"), json.dumps(selection, sort_keys=True)


def enforce_action_auth_request(user_id, payload, *, claim=True):
    """Check before publishing a message; only trusted nested routes reuse a claim."""
    if not isinstance(payload, dict):
        return action_auth_error_response(ValueError())
    request_id = payload.get("action_auth_request_id")
    if not request_id and not any(payload.get(key) for key in ("agent_info", "action_ref", "run_id")):
        return None
    stamp = _action_auth_guard_stamp(user_id, payload)
    verified = getattr(g, "action_auth_verified_request", None)
    if claim and verified == stamp:
        return None
    try:
        receipt = authorize_action_auth_execution(user_id, payload, claim=claim)
    except (ActionCredentialsRequired, ActionAuthConflict, ActionAuthStorageError, PermissionError, LookupError, ValueError, AzureError) as error:
        log_event(
            "[ACTION_AUTH] Execution requires authentication or could not be authorized.",
            level=logging.WARNING,
            extra={"error_type": type(error).__name__},
        )
        return action_auth_error_response(error)
    if claim and (not request_id or receipt is not None):
        g.action_auth_verified_request = stamp
    return None
