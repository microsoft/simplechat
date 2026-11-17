# route_backend_bitbucket.py
"""Authenticated, actor-bound Bitbucket connection and authoring discovery endpoints."""

import hmac
import json
import logging
import os
import secrets
from functools import wraps
from urllib.parse import urlsplit

from azure.cosmos.exceptions import CosmosHttpResponseError
from flask import jsonify, make_response, render_template, request, session

from functions_appinsights import log_event
from functions_action_manifest import get_action_origin
from functions_authentication import get_current_user_id, get_current_user_info, login_required, user_required
from functions_bitbucket_connections import bitbucket_connections
from functions_bitbucket_operations import BitbucketClient, BitbucketError
from functions_group import find_group_by_id, get_user_role_in_group
from functions_group_action_policy import group_action_management_operations
from functions_interaction_csrf import get_interaction_csrf_token
from functions_settings import get_settings
from swagger_wrapper import get_auth_security, swagger_route


def _boundary(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            response = function(*args, **kwargs)
        except BitbucketError as error:
            response = jsonify({"error": error.public_message, "code": error.code}), error.status
        except (PermissionError, LookupError):
            response = jsonify({"error": "The Bitbucket action is unavailable."}), 404
        except CosmosHttpResponseError as error:
            log_event("[PLUGINS] Bitbucket connection storage operation failed.",
                      level=logging.WARNING, extra={"error_type": type(error).__name__})
            response = jsonify({"error": "Bitbucket connection changed or storage is unavailable. Refresh and retry."}), 409
        except (ValueError, TypeError, KeyError):
            response = jsonify({"error": "Invalid Bitbucket configuration or request."}), 400
        result = make_response(response)
        result.headers["Cache-Control"] = "no-store"
        result.headers["Referrer-Policy"] = "no-referrer"
        return result
    return wrapped


def _body():
    expected = session.get("action_credentials_csrf_token", "")
    supplied = request.headers.get("X-CSRFToken", "")
    if not expected or not hmac.compare_digest(expected, supplied) or request.headers.get("Sec-Fetch-Site") == "cross-site":
        raise BitbucketError("csrf_invalid", "Refresh the Bitbucket connection controls before submitting.", 403)
    if not request.is_json or (request.content_length or 0) > 32768:
        raise BitbucketError("request_invalid", "Invalid Bitbucket request.")
    raw = request.stream.read(32769)
    if len(raw) > 32768:
        raise BitbucketError("request_invalid", "Invalid Bitbucket request.", 413)
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise BitbucketError("request_invalid", "Invalid Bitbucket request.") from None
    if not isinstance(value, dict):
        raise BitbucketError("request_invalid", "Invalid Bitbucket request.")
    return value


def _reference(value):
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise BitbucketError("request_invalid", "Select a saved Bitbucket action.")
    if value.startswith("personal:self:"):
        return f"personal:{get_current_user_id()}:{value.split(':', 2)[2]}"
    return value


def _authorize_discovery(actor, manifest):
    """Discovery can exceed the runtime allowlist, so it requires action edit rights."""
    origin = get_action_origin(manifest)
    if origin is None:
        raise PermissionError("Action provenance is required.")
    if origin.scope_type == "personal" and origin.scope_id == actor:
        return
    if origin.scope_type == "global" and "Admin" in ((get_current_user_info() or {}).get("roles") or []):
        return
    if origin.scope_type == "group":
        group = find_group_by_id(origin.scope_id)
        if group and "edit" in group_action_management_operations(
            actor, group, get_user_role_in_group(group, actor), get_settings(),
        ):
            return
    raise PermissionError("Bitbucket discovery requires action management rights.")


def register_route_backend_bitbucket(bp):
    @bp.route("/bitbucket/connect", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @_boundary
    def bitbucket_connection_page():
        reference = _reference(request.args.get("action_ref"))
        bitbucket_connections().status(get_current_user_id(), reference)
        return render_template("bitbucket_connection.html", action_ref=reference)

    @bp.route("/api/bitbucket/connection", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @_boundary
    def bitbucket_connection():
        reference = _reference(request.args.get("action_ref"))
        status = bitbucket_connections().status(get_current_user_id(), reference)
        return jsonify({**status, "csrf_token": get_interaction_csrf_token()})

    @bp.route("/api/bitbucket/connect", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @_boundary
    def bitbucket_connect():
        body = _body()
        if not session.get("bitbucket_session_binding"):
            session["bitbucket_session_binding"] = secrets.token_urlsafe(32)
        callback = os.environ.get("BITBUCKET_REDIRECT_URI", "")
        parsed = urlsplit(callback)
        if (
            parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path != "/api/bitbucket/callback" or parsed.query or parsed.fragment
        ):
            raise BitbucketError("callback_required", "Configure the canonical HTTPS BITBUCKET_REDIRECT_URI on the server.", 503)
        return jsonify(bitbucket_connections().start(
            get_current_user_id(), _reference(body.get("action_ref")),
            session["bitbucket_session_binding"], callback,
        ))

    @bp.route("/api/bitbucket/callback", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @_boundary
    def bitbucket_callback():
        if request.args.get("error"):
            raise BitbucketError("consent_cancelled", "Bitbucket sign-in was cancelled. Return to the action and reconnect.")
        bitbucket_connections().complete(
            get_current_user_id(), request.args.get("state"), request.args.get("code"),
            session.get("bitbucket_session_binding", ""),
        )
        return "Bitbucket connected. Close this tab and return to the action.", 200

    @bp.route("/api/bitbucket/disconnect", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @_boundary
    def bitbucket_disconnect():
        body = _body()
        bitbucket_connections().disconnect(get_current_user_id(), _reference(body.get("action_ref")))
        return jsonify({"connected": False})

    @bp.route("/api/bitbucket/discover", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @_boundary
    def bitbucket_discover():
        body = _body()
        service = bitbucket_connections()
        actor = get_current_user_id()
        reference = _reference(body.get("action_ref"))
        manifest, _fingerprint, _item_id = service.binding(actor, reference)
        _authorize_discovery(actor, manifest)
        method = manifest["additionalFields"]["auth_method"]
        auth = {"method": method, "secret": manifest["auth"].get("key", ""),
                "username": manifest["auth"].get("identity", "")}
        if method == "oauth":
            auth = {"method": "bearer_token", "secret": service.token(actor, reference)}
        client = BitbucketClient(manifest, auth)
        if body.get("operation") == "branches":
            return jsonify(client.branches(body.get("repository", ""), body.get("cursor", 0)))
        return jsonify(client.discover(body.get("project", ""), body.get("cursor", 0)))
