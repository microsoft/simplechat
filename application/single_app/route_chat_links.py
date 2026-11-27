# route_chat_links.py
"""User-facing API and compact navigation routes for workspace chat links."""

import logging

from flask import jsonify, make_response, redirect, request
from urllib.parse import urlencode

from chat_link_contract import (
    CHAT_LINK_DEFAULT_LIFETIME_DAYS,
    normalize_chat_link_reference,
)
from functions_appinsights import log_event
from functions_authentication import (
    get_current_user_id,
    login_required,
    user_required,
)
from functions_chat_links import (
    ChatLinkError,
    ChatLinkServiceError,
    create_chat_link,
    list_chat_links,
    resolve_chat_link,
    revoke_chat_link,
)
from functions_settings import get_settings
from functions_ui_pages import is_modern_ui_available
from swagger_wrapper import get_auth_security, swagger_route


MAX_CREATE_REQUEST_BYTES = 512 * 1024


def _chat_link_response(response):
    result = make_response(response)
    result.headers["Cache-Control"] = "no-store"
    result.headers["Pragma"] = "no-cache"
    result.headers["Referrer-Policy"] = "same-origin"
    return result


def _chat_link_error(error):
    if isinstance(error, ChatLinkError):
        log_event(
            "[CHAT_LINKS] Chat link request was refused or unavailable.",
            extra={"code": error.code, "status": error.status_code},
            level=logging.INFO,
            debug_only=True,
        )
        return _chat_link_response(
            (jsonify({
                "error": error.code,
                "message": error.public_message,
            }), error.status_code)
        )
    log_event(
        "[CHAT_LINKS] Unexpected chat link route failure.",
        extra={"error_type": type(error).__name__},
        level=logging.ERROR,
    )
    failure = ChatLinkServiceError()
    return _chat_link_response(
        (jsonify({
            "error": failure.code,
            "message": failure.public_message,
        }), failure.status_code)
    )


def _parse_create_body():
    if (
        request.content_length is None
        or request.content_length > MAX_CREATE_REQUEST_BYTES
    ):
        raise ChatLinkError(
            "chat_link_invalid",
            "Choose a valid chat-link configuration.",
            400,
        )
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        body = {}
    body.setdefault("lifetime_days", CHAT_LINK_DEFAULT_LIFETIME_DAYS)
    return body


def register_route_chat_links(bp):
    @bp.route("/l/<reference>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def chat_link_navigation(reference):
        normalized_reference = normalize_chat_link_reference(reference)
        if not normalized_reference:
            failure = ChatLinkError(
                "chat_link_unavailable",
                "This chat link is unavailable.",
                404,
            )
            return _chat_link_error(failure)

        settings = get_settings() or {}
        target = (
            f"/v2/chat?{urlencode({'chat_link': normalized_reference})}"
            if is_modern_ui_available(settings=settings)
            else f"/chats?{urlencode({'chat_link': normalized_reference})}"
        )
        response = redirect(target, code=302)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @bp.route("/api/chat-links", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def chat_link_create():
        try:
            user_id = get_current_user_id()
            created = create_chat_link(user_id, _parse_create_body())
            return _chat_link_response(
                (jsonify(created["projection"]), 201)
            )
        except ChatLinkError as error:
            return _chat_link_error(error)
        except Exception as error:
            return _chat_link_error(error)

    @bp.route("/api/chat-links", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def chat_links_list_own():
        try:
            page_size_value = request.args.get("page_size", "25")
            try:
                page_size = int(page_size_value)
            except ValueError as error:
                raise ChatLinkError(
                    "chat_link_invalid",
                    "Choose a valid page size.",
                    400,
                ) from error
            result = list_chat_links(
                created_by_user_id=get_current_user_id(),
                page_size=page_size,
                continuation_token=request.args.get("continuation_token") or None,
            )
            return _chat_link_response(jsonify(result))
        except ChatLinkError as error:
            return _chat_link_error(error)
        except Exception as error:
            return _chat_link_error(error)

    @bp.route("/api/chat-links/<reference>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def chat_link_resolve(reference):
        try:
            resolved = resolve_chat_link(reference, get_current_user_id())
            return _chat_link_response(jsonify(resolved["projection"]))
        except ChatLinkError as error:
            return _chat_link_error(error)
        except Exception as error:
            return _chat_link_error(error)

    @bp.route("/api/chat-links/<reference>", methods=["DELETE"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def chat_link_revoke(reference):
        try:
            revoke_chat_link(reference, get_current_user_id())
            return _chat_link_response(("", 204))
        except ChatLinkError as error:
            return _chat_link_error(error)
        except Exception as error:
            return _chat_link_error(error)
