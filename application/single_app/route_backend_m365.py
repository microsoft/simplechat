# route_backend_m365.py
"""Authenticated Profile and unified Microsoft 365 approval endpoints."""

import hmac
import logging
import secrets
from urllib.parse import urlencode, urlsplit

import requests
from azure.core.exceptions import AzureError
from flask import Blueprint, jsonify, make_response, redirect, render_template, request, session

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
from functions_m365_connections import (
    CHAT_AUTH_SESSION_KEY,
    CHAT_AUTH_STATE_PREFIX,
    CHAT_CALLBACK_PATH,
    CHAT_RECONNECT_SESSION_KEY,
    COMPLETION_MODES,
    CONNECTION_CALLBACK_PATH,
    get_m365_connection_service,
    workflow_connection_readiness,
)
from swagger_wrapper import swagger_route, get_auth_security


# Fixed classic destinations for full-page sign-ins. Popups report to their opener instead,
# which is how the V2 interface connects, so it never lands on these pages.
CLASSIC_CHAT_CONNECTION_URL = "/profile?tab=settings#m365-chat-connection"
CLASSIC_CHAT_CONNECTED_URL = "/profile?tab=settings&m365_chat_connection=connected#m365-chat-connection"
CLASSIC_WORKFLOW_CONNECTION_URL = "/profile?tab=settings#m365-connection-status"
CLASSIC_WORKFLOW_CONNECTED_URL = "/profile?tab=settings&m365_connection=connected#m365-connection-status"
CLASSIC_CHATS_URL = "/chats"
CONNECTION_RESULT_TEMPLATE = "m365_connection_result.html"
_CALLBACK_RESPONSE_FIELDS = {"state", "code", "error", "error_description", "error_uri", "session_state", "client_info"}


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
        or not hmac.compare_digest(expected.encode("utf-8"), supplied.encode("utf-8"))
        or request.headers.get("Sec-Fetch-Site", "").lower() == "cross-site"
    ):
        raise M365PolicyError("m365_csrf_invalid", "Refresh the Microsoft 365 controls before submitting.")


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


def _error_details(exc):
    """The safe error payload and HTTP status for an M365 failure, shared by JSON and pages."""
    if isinstance(exc, M365PolicyError):
        code = exc.code
        if code == "not_logged_in":
            status = 401
        elif code in {"m365_principal_mismatch", "m365_account_mismatch", "m365_workflow_not_authorized", "m365_csrf_invalid"}:
            status = 403
        elif isinstance(exc, M365ApprovalConflict) or code in {
            "m365_approval_required", "m365_connection_busy", "m365_connection_changed",
            "m365_connection_required", "m365_reconnect_required",
        }:
            status = 409
        elif code in {
            "m365_key_vault_required", "m365_key_unavailable", "m365_key_invalid",
            "m365_key_provision_forbidden", "m365_key_deleted",
            "m365_configuration_invalid", "m365_tenant_authority_required", "m365_callback_invalid",
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
        return dict(exc.payload), status
    if isinstance(exc, PermissionError):
        return {"error": "forbidden", "message": "You cannot perform this Microsoft 365 operation."}, 403
    if isinstance(exc, LookupError):
        return {"error": "not_found", "message": "Microsoft 365 request not found."}, 404
    if isinstance(exc, ValueError):
        log_event(
            "[AUTH] Microsoft 365 request validation failed",
            extra={"exception_type": type(exc).__name__, "endpoint": request.endpoint},
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return {"error": "invalid_request", "message": "Invalid Microsoft 365 request."}, 400
    log_event(
        "[AUTH] Microsoft 365 request dependency unavailable",
        extra={"exception_type": type(exc).__name__, "endpoint": request.endpoint},
        level=logging.ERROR,
    )
    return {
        "error": "m365_service_unavailable",
        "message": "Microsoft 365 request storage or authentication is temporarily unavailable.",
    }, 503


def _error_response(exc):
    payload, status = _error_details(exc)
    return jsonify({"success": False, **payload}), status


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


def _callback_uri(callback_path=CONNECTION_CALLBACK_PATH):
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
        # App Service terminates TLS before forwarding HTTP to the Flask worker.
        parsed = urlsplit(origin)
        if parsed.hostname not in {"localhost", "127.0.0.1"}:
            origin = parsed._replace(scheme="https").geturl()
    return f"{origin}{callback_path}"


def _completion_mode(data):
    """The optional completion mode a connect request asks for; full-page by default."""
    completion = data.get("completion", "page")
    if completion not in COMPLETION_MODES:
        raise ValueError("Unsupported sign-in completion mode.")
    return completion


def _callback_auth_response():
    auth_response = request.args.to_dict()
    if (
        set(auth_response) - _CALLBACK_RESPONSE_FIELDS
        or any(len(value) > 16384 for value in auth_response.values())
    ):
        raise ValueError("Invalid authorization response.")
    return auth_response


def _connection_result_page(*, kind, outcome, completion, continue_url, code=None, message="", status=200):
    """A small page that ends a Microsoft 365 sign-in instead of raw JSON.

    In a popup its script tells the window that opened it (same origin only) and closes;
    on a full page it shows the outcome with a link back. Every value is server-chosen or a
    safe error message, and continue_url is always one of this module's fixed paths.
    """
    if outcome == "connected":
        message_type = "m365-profile-reconnected" if kind == "chat" else "m365-workflow-connected"
        title = "Microsoft 365 is connected"
        message = message or (
            "Sign-in completed. You can return to SimpleChat." if kind == "chat"
            else "Workflows can now run as your Microsoft 365 account once you authorize them."
        )
    else:
        message_type = "m365-connect-failed"
        title = "Microsoft 365 was not connected"
    result = {
        "type": message_type, "kind": kind, "outcome": outcome, "completion": completion,
        "code": code, "message": message, "continue_url": continue_url,
    }
    response = make_response(render_template(
        CONNECTION_RESULT_TEMPLATE, result=result, title=title, message=message,
        continue_url=continue_url,
        continue_label="Return to settings" if continue_url != CLASSIC_CHATS_URL else "Return to chat",
    ), status)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


def _pending_chat_flow(state):
    """Completion mode and purpose of the chat sign-in this callback answers, read before it is consumed."""
    record = session.get(CHAT_AUTH_SESSION_KEY)
    flow = record.get("flow") if isinstance(record, dict) else None
    expected = flow.get("state") if isinstance(flow, dict) else None
    if (
        not isinstance(expected, str) or not isinstance(state, str)
        or not hmac.compare_digest(expected.encode("utf-8"), state.encode("utf-8"))
    ):
        return "auto", None
    completion = record.get("completion")
    return (completion if completion in COMPLETION_MODES else "page"), record.get("purpose")


def _complete_chat_connection(user_id, tenant_id, auth_response):
    # These owners are initialized before an authenticated OAuth callback.
    from functions_m365_request_resume import get_m365_chat_request
    from functions_m365_runtime import _conversation_access
    completed = get_m365_connection_service().complete_chat_connection(user_id, tenant_id, auth_response)
    if completed.get("return_to") == "profile":
        if completed.get("completion") == "popup":
            return _connection_result_page(
                kind="chat", outcome="connected", completion="popup", continue_url=CLASSIC_CHAT_CONNECTED_URL,
            )
        return redirect(CLASSIC_CHAT_CONNECTED_URL)
    job = get_m365_chat_request(completed["request_id"], user_id)
    if job.get("conversation_id") != completed["conversation_id"]:
        raise M365PolicyError("m365_request_changed", "The conversation request changed during sign-in.")
    conversation, access, _shared = _conversation_access(user_id, job["conversation_id"])
    if conversation is None:
        raise LookupError("The original conversation no longer exists.")
    visible_id = (access or {}).get("collaboration_conversation_id") or conversation["id"]
    query = urlencode({
        'conversationId': visible_id,
        'm365_request_id': job['id'],
        'm365_auth': 'connected',
    })
    return redirect(f"/chats?{query}")


def _publish_verified_workflow_cache_to_session(serialized):
    session["token_cache"] = serialized
    session.pop(CHAT_RECONNECT_SESSION_KEY, None)


def _complete_workflow_connection(user_id, tenant_id, auth_response, completion):
    session_binding = session.pop("m365_workflow_oauth_binding", None)
    if not session_binding:
        raise M365PolicyError(
            "m365_auth_state_invalid",
            "This workflow sign-in request expired or was replaced by a newer one. Start Connect for workflows again.",
        )
    get_m365_connection_service().complete_connection(
        user_id, tenant_id, auth_response, session_binding,
        cache_writer=_publish_verified_workflow_cache_to_session,
    )
    if completion == "popup":
        return _connection_result_page(
            kind="workflow", outcome="connected", completion="popup", continue_url=CLASSIC_WORKFLOW_CONNECTED_URL,
        )
    return redirect(CLASSIC_WORKFLOW_CONNECTED_URL)


@login_required
@user_required
def complete_m365_chat_connection_callback():
    """Use the registered login callback without replacing the SimpleChat principal."""
    completion, purpose = _pending_chat_flow(request.args.get("state"))
    try:
        user_id, tenant_id = _subject()
        result = _complete_chat_connection(user_id, tenant_id, _callback_auth_response())
    except (M365PolicyError, PermissionError, LookupError, ValueError, AzureError, requests.RequestException) as exc:
        payload, status = _error_details(exc)
        result = _connection_result_page(
            kind="chat", outcome="failed", completion=completion, status=status,
            code=payload["error"], message=payload["message"],
            continue_url=CLASSIC_CHATS_URL if purpose == "chat_request" else CLASSIC_CHAT_CONNECTION_URL,
        )
    response = make_response(result)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@login_required
@user_required
def complete_m365_workflow_connection_callback():
    """Finish a workflow sign-in that returned to the registered /getAToken callback."""
    completion = "auto"
    try:
        user_id, tenant_id = _subject()
        completion = get_m365_connection_service().connection_flow_completion(user_id, request.args.get("state"))
        result = _complete_workflow_connection(user_id, tenant_id, _callback_auth_response(), completion)
    except (M365PolicyError, PermissionError, LookupError, ValueError, AzureError, requests.RequestException) as exc:
        payload, status = _error_details(exc)
        result = _connection_result_page(
            kind="workflow", outcome="failed", completion=completion, status=status,
            code=payload["error"], message=payload["message"], continue_url=CLASSIC_WORKFLOW_CONNECTION_URL,
        )
    response = make_response(result)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


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

    @bp.route("/api/m365/requests/<request_id>/connect", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def connect_m365_chat_request(request_id):
        # Request storage belongs to the initialized chat/runtime owner.
        from functions_m365_request_resume import get_m365_chat_request
        user_id, tenant_id = _subject()
        validate_m365_csrf()
        if _body():
            raise ValueError("The saved request supplies the Microsoft 365 connection scope.")
        job = get_m365_chat_request(request_id, user_id)
        if job["status"] != "awaiting_sign_in":
            raise M365PolicyError("m365_request_not_waiting", "This request is not waiting for Microsoft 365 sign-in.")
        result = get_m365_connection_service().start_chat_connection(
            user_id, tenant_id, request_id, job["conversation_id"],
            job.get("required_scopes") or [], _callback_uri(CHAT_CALLBACK_PATH),
        )
        return jsonify({"success": True, **result})

    @bp.route("/api/m365/chat/connection", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def read_m365_chat_connection():
        user_id, tenant_id = _subject()
        return jsonify({
            "success": True,
            "connection": get_m365_connection_service().read_chat_connection(user_id, tenant_id),
            "csrf_token": get_m365_csrf_token(),
        })

    @bp.route("/api/m365/chat/connection/connect", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def reconnect_m365_chat_connection():
        user_id, tenant_id = _subject()
        validate_m365_csrf()
        data = _body()
        if "sources" not in data or set(data) - {"sources", "completion"}:
            raise ValueError("Select only the Microsoft 365 sources to reconnect.")
        result = get_m365_connection_service().start_profile_chat_connection(
            user_id, tenant_id, data["sources"], _callback_uri(CHAT_CALLBACK_PATH),
            completion=_completion_mode(data),
        )
        return jsonify({"success": True, **result})

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
        # Settings are initialized before an authenticated profile request.
        from functions_settings import get_settings
        user_id, tenant_id = _subject()
        return jsonify({
            "success": True,
            "connection": get_m365_connection_service().current_connection(user_id, tenant_id),
            "workflow_connections": workflow_connection_readiness(get_settings()),
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
        if set(data) - {"sources", "scopes", "completion"}:
            raise ValueError("Invalid connection fields.")
        completion = _completion_mode(data)
        session_binding = secrets.token_urlsafe(32)
        session["m365_workflow_oauth_binding"] = session_binding
        # The registered sign-in callback; its state prefix routes the result here.
        result = get_m365_connection_service().start_connection(
            user_id, tenant_id, data.get("sources"),
            _callback_uri(CHAT_CALLBACK_PATH), session_binding, scopes=data.get("scopes"),
            completion=completion,
        )
        return jsonify({"success": True, **result})

    @bp.route("/api/m365/connections/callback", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def complete_m365_profile_connection():
        # Kept for deployments that registered this callback; new sign-ins use /getAToken.
        if (request.args.get("state") or "").startswith(CHAT_AUTH_STATE_PREFIX):
            return complete_m365_chat_connection_callback()
        return complete_m365_workflow_connection_callback()

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
