# route_backend_m365.py
"""Authenticated Profile and unified Microsoft 365 approval endpoints."""

import hmac
import logging
import secrets
from urllib.parse import urlsplit

import requests
from azure.core.exceptions import AzureError
from flask import Blueprint, jsonify, redirect, request, session

from functions_appinsights import log_event
from functions_authentication import login_required, user_required, user_required_blueprint
from functions_m365_approvals import (
    M365ApprovalConflict,
    M365PolicyError,
    TYPE_EXTENDED_ANALYSIS,
    TYPE_SOURCE_SHARING,
    TYPE_WORKFLOW_RUN_AS,
    get_m365_approval_service,
    is_m365_approval_subject,
    sanitize_m365_approval,
)
from functions_m365_connections import CONNECTION_CALLBACK_PATH, get_m365_connection_service
from swagger_wrapper import swagger_route, get_auth_security


_conversation_authorizer = None
_decision_callback = None
_audit_conversation_resolver = None


def configure_m365_routes(*, conversation_authorizer=None, decision_callback=None, audit_conversation_resolver=None):
    """The chat owner supplies exact current conversation-read authorization."""
    global _conversation_authorizer, _decision_callback, _audit_conversation_resolver
    _conversation_authorizer = conversation_authorizer
    _decision_callback = decision_callback
    _audit_conversation_resolver = audit_conversation_resolver


def _resume_after_decision(resolved, user_id):
    if _decision_callback is not None and resolved.get("status") in {"approved", "denied"}:
        return {**resolved, **_decision_callback(resolved, user_id)}
    return resolved


def _subject():
    user = session.get("user") or {}
    if not user.get("oid") or not user.get("tid"):
        raise M365PolicyError("not_logged_in", "A tenant-authenticated SimpleChat session is required.")
    if user["tid"] != get_m365_connection_service().config_provider().tenant_id:
        raise M365PolicyError("m365_account_mismatch", "Your account does not belong to this deployment's tenant.")
    return user["oid"], user["tid"]


def get_m365_csrf_token():
    token = session.get("m365_csrf_token")
    if not isinstance(token, str) or len(token) < 32:
        token = secrets.token_urlsafe(32)
        session["m365_csrf_token"] = token
    return token


def validate_m365_csrf():
    expected = session.get("m365_csrf_token")
    supplied = request.headers.get("X-M365-CSRF-Token")
    if (
        not isinstance(expected, str) or not isinstance(supplied, str)
        or not hmac.compare_digest(expected, supplied)
        or request.headers.get("Sec-Fetch-Site", "").lower() == "cross-site"
    ):
        raise PermissionError("Refresh the Microsoft 365 form before submitting.")


def _body():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValueError("A JSON object is required.")
    return value


def _page_options():
    return {
        "page_size": int(request.args.get("page_size", "20")),
        "continuation_token": request.args.get("continuation_token"),
    }


def _error_response(exc):
    if isinstance(exc, M365PolicyError):
        code = exc.code
        if code == "not_logged_in":
            status = 401
        elif code in {"m365_principal_mismatch", "m365_account_mismatch", "m365_workflow_not_authorized"}:
            status = 403
        elif isinstance(exc, M365ApprovalConflict) or code in {
            "m365_approval_required", "m365_connection_busy", "m365_connection_changed",
            "m365_connection_required", "m365_reconnect_required",
        }:
            status = 409
        elif code in {
            "m365_key_vault_required", "m365_key_unavailable", "m365_key_invalid",
            "m365_configuration_invalid", "m365_tenant_authority_required",
            "m365_workflow_validation_unavailable", "m365_audit_validation_unavailable",
            "m365_approval_validation_unavailable",
            "m365_authorization_unavailable", "m365_preflight_unavailable",
            "m365_action_selection_unavailable",
        }:
            status = 503
        elif code == "m365_connection_not_found":
            status = 404
        else:
            status = 400
        return jsonify({"success": False, **exc.payload}), status
    if isinstance(exc, PermissionError):
        return jsonify({"success": False, "error": "forbidden", "message": "You cannot perform this Microsoft 365 operation."}), 403
    if isinstance(exc, LookupError):
        return jsonify({"success": False, "error": "not_found", "message": "Microsoft 365 request not found."}), 404
    if isinstance(exc, ValueError):
        return jsonify({"success": False, "error": "invalid_request", "message": "Invalid Microsoft 365 request."}), 400
    log_event(
        "[AUTH] Microsoft 365 request dependency unavailable",
        extra={"exception_type": type(exc).__name__, "endpoint": request.endpoint},
        level=logging.ERROR,
    )
    return jsonify({
        "success": False, "error": "m365_service_unavailable",
        "message": "Microsoft 365 request storage or authentication is temporarily unavailable.",
    }), 503


@user_required
def m365_approval_decision_response(approval, user_id, data, *, deny=False):
    """Used by both existing Approvals APIs; never invokes an administrative executor."""
    try:
        validate_m365_csrf()
        _current_user_id, _tenant_id = _subject()
        if _current_user_id != user_id or not is_m365_approval_subject(approval, user_id):
            raise PermissionError("Only the data user can decide this request.")
        if approval.get("context", {}).get("tenant_id") != _tenant_id:
            raise LookupError("Microsoft 365 approval not found.")
        request_type = approval["request_type"]
        if request_type == TYPE_SOURCE_SHARING:
            choices = (
                {source: {"duration": "no"} for source in approval["sources"]}
                if deny else data.get("decisions")
            )
            decision = {"decisions": choices}
        elif request_type == TYPE_EXTENDED_ANALYSIS:
            decision = {"choice": "fast" if deny else data.get("choice")}
        else:
            decision = {"choice": "deny" if deny else "approve"}
        resolved = get_m365_approval_service().decide(approval["id"], user_id, decision)
        resolved = _resume_after_decision(resolved, user_id)
        return jsonify({
            "success": True, "message": "Decision recorded. Continuation is queued.",
            "approval": resolved, "execution_status": resolved["execution_status"],
        }), 200
    except (M365PolicyError, PermissionError, LookupError, ValueError, AzureError, requests.RequestException) as exc:
        return _error_response(exc)


def _callback_uri():
    # The configured Front Door URL is an owner-supplied origin, not callback input.
    from config import LOGIN_REDIRECT_URL
    from functions_settings import get_settings
    settings = get_settings()
    if settings.get("enable_front_door") and settings.get("front_door_url"):
        origin = settings["front_door_url"].rstrip("/")
    elif LOGIN_REDIRECT_URL:
        parsed = urlsplit(LOGIN_REDIRECT_URL)
        origin = f"{parsed.scheme}://{parsed.netloc}"
    else:
        origin = request.host_url.rstrip("/")
    return f"{origin}{CONNECTION_CALLBACK_PATH}"


def register_route_backend_m365(bp):
    if not isinstance(bp, Blueprint):
        raise TypeError("Microsoft 365 routes must be registered on a Blueprint.")
    bp.before_request(user_required_blueprint())
    for exception_type in (M365PolicyError, PermissionError, LookupError, ValueError, AzureError, requests.RequestException):
        bp.register_error_handler(exception_type, _error_response)

    @bp.after_request
    def private_m365_response(response):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Pragma"] = "no-cache"
        return response

    @bp.route("/api/m365/requests", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def list_m365_waiting_requests():
        from config import cosmos_m365_execution_runs_container
        user_id, _tenant_id = _subject()
        options = _page_options()
        if not 1 <= options["page_size"] <= 100:
            raise ValueError("Invalid request page size.")
        pages = cosmos_m365_execution_runs_container.query_items(
            query=(
                "SELECT c.id, c.status, c.conversation_id, c.workflow_id, c.authentication_error "
                "FROM c WHERE c.user_id = @user_id AND c.type = 'm365_execution_request' "
                "AND c.status IN ('awaiting_approval', 'awaiting_sign_in', 'recovery_required', 'ready_to_resume')"
            ),
            parameters=[{"name": "@user_id", "value": user_id}],
            partition_key=user_id, max_item_count=options["page_size"],
        ).by_page(continuation_token=options["continuation_token"])
        items = list(next(pages, []))
        return jsonify({
            "items": items, "continuation_token": pages.continuation_token,
            "csrf_token": get_m365_csrf_token(),
        })

    @bp.route("/api/m365/requests/<request_id>/resume", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def resume_m365_waiting_request(request_id):
        from functions_m365_request_resume import resume_m365_chat_request
        user_id, _tenant_id = _subject()
        validate_m365_csrf()
        return jsonify(resume_m365_chat_request(request_id, user_id))

    @bp.route("/api/m365/preferences", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_m365_profile_preferences():
        user_id, _tenant_id = _subject()
        return jsonify({
            "success": True,
            "preferences": get_m365_approval_service().get_preferences(user_id),
            "csrf_token": get_m365_csrf_token(),
        })

    @bp.route("/api/m365/preferences", methods=["PATCH"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def save_m365_profile_preferences():
        user_id, _tenant_id = _subject()
        validate_m365_csrf()
        preferences = get_m365_approval_service().update_preferences(user_id, _body())
        return jsonify({"success": True, "preferences": preferences})

    @bp.route("/api/m365/sources/<source>/revoke", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def revoke_m365_profile_source(source):
        user_id, _tenant_id = _subject()
        validate_m365_csrf()
        return jsonify({"success": True, **get_m365_approval_service().revoke_source(user_id, source)})

    @bp.route("/api/m365/approvals", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def list_m365_user_approvals():
        user_id, _tenant_id = _subject()
        return jsonify(get_m365_approval_service().list_records(user_id, **_page_options()))

    @bp.route("/api/m365/approvals/<approval_id>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def read_m365_user_approval(approval_id):
        user_id, tenant_id = _subject()
        approval = get_m365_approval_service().get_approval(approval_id, user_id)
        if approval["tenant_id"] != tenant_id:
            raise LookupError("Microsoft 365 approval not found.")
        return jsonify(sanitize_m365_approval(approval))

    @bp.route("/api/m365/approvals/<approval_id>/decision", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def decide_m365_user_approval(approval_id):
        user_id, tenant_id = _subject()
        validate_m365_csrf()
        service = get_m365_approval_service()
        approval = service.get_approval(approval_id, user_id)
        if approval["tenant_id"] != tenant_id:
            raise LookupError("Microsoft 365 approval not found.")
        resolved = service.decide(approval_id, user_id, _body())
        return jsonify(_resume_after_decision(resolved, user_id))

    @bp.route("/api/m365/audit", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def list_m365_user_audit():
        user_id, _tenant_id = _subject()
        return jsonify(get_m365_approval_service().list_records(user_id, audit=True, **_page_options()))

    @bp.route("/api/m365/conversations/<conversation_id>/audit", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def list_m365_conversation_audit(conversation_id):
        user_id, _tenant_id = _subject()
        if _conversation_authorizer is None:
            raise M365PolicyError(
                "m365_audit_validation_unavailable",
                "Conversation access must be validated before viewing this audit.",
            )
        if _conversation_authorizer(user_id, conversation_id) is not True:
            raise PermissionError("Conversation access denied.")
        if _audit_conversation_resolver is not None:
            conversation_id = _audit_conversation_resolver(user_id, conversation_id)
        return jsonify(get_m365_approval_service().list_conversation_audit(
            conversation_id, **_page_options(),
        ))

    @bp.route("/api/m365/connections", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def read_m365_profile_connection():
        user_id, tenant_id = _subject()
        return jsonify({
            "success": True,
            "connection": get_m365_connection_service().current_connection(user_id, tenant_id),
            "csrf_token": get_m365_csrf_token(),
        })

    @bp.route("/api/m365/connections/connect", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def connect_m365_profile_account():
        user_id, tenant_id = _subject()
        validate_m365_csrf()
        data = _body()
        if set(data) - {"sources", "scopes"}:
            raise ValueError("Invalid connection fields.")
        session_binding = secrets.token_urlsafe(32)
        session["m365_workflow_oauth_binding"] = session_binding
        result = get_m365_connection_service().start_connection(
            user_id, tenant_id, data.get("sources"),
            _callback_uri(), session_binding, scopes=data.get("scopes"),
        )
        return jsonify({"success": True, **result})

    @bp.route("/api/m365/connections/callback", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def complete_m365_profile_connection():
        user_id, tenant_id = _subject()
        session_binding = session.pop("m365_workflow_oauth_binding", None)
        if not session_binding:
            raise M365PolicyError("m365_auth_state_invalid", "Start Connect again from Profile.")
        auth_response = request.args.to_dict()
        if (
            set(auth_response) - {"state", "code", "error", "error_description", "error_uri", "session_state", "client_info"}
            or any(len(value) > 16384 for value in auth_response.values())
        ):
            raise ValueError("Invalid authorization response.")
        get_m365_connection_service().complete_connection(user_id, tenant_id, auth_response, session_binding)
        return redirect("/profile?m365_connection=connected")

    @bp.route("/api/m365/connections/disconnect", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def disconnect_m365_profile_account():
        user_id, tenant_id = _subject()
        validate_m365_csrf()
        data = _body()
        if set(data) != {"connection_id"}:
            raise ValueError("An own-account connection identifier is required.")
        connection = get_m365_connection_service().disconnect(data["connection_id"], user_id, tenant_id)
        session.pop("m365_workflow_oauth_binding", None)
        return jsonify({"success": True, "connection": connection})

    @bp.route("/api/m365/bindings", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def list_m365_workflow_bindings():
        user_id, _tenant_id = _subject()
        return jsonify(get_m365_approval_service().list_records(
            user_id, request_type=TYPE_WORKFLOW_RUN_AS, **_page_options(),
        ))

    @bp.route("/api/m365/bindings/<binding_id>/revoke", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def revoke_m365_workflow_run_as(binding_id):
        user_id, tenant_id = _subject()
        validate_m365_csrf()
        service = get_m365_approval_service()
        approval = service.get_approval(binding_id, user_id)
        if approval["tenant_id"] != tenant_id:
            raise LookupError("Workflow binding not found.")
        return jsonify({"success": True, "binding": service.revoke_workflow_binding(binding_id, user_id)})
