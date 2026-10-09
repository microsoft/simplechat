# public_chat_scope.py
"""Aggregate public search intent, separate from workspace and conversation ownership."""

from contextlib import contextmanager
from functools import wraps
import logging

from flask import g, has_request_context, jsonify, request

from public_chat_scope_state import (
    PublicChatScopeError,
    aggregate_public_workspace_ids,
    current_public_chat_scope,
    normalize_public_workspace_selection,
    public_chat_scope_context,
)


def _intersect_public_scope_lock(workspace_ids, conversation):
    if not isinstance(conversation, dict) or not conversation.get("scope_locked"):
        return workspace_ids
    contexts = conversation.get("locked_contexts") or conversation.get("context") or []
    locked_ids = {
        item.get("id") for item in contexts
        if isinstance(item, dict) and item.get("scope") == "public"
    }
    return [workspace_id for workspace_id in workspace_ids if workspace_id in locked_ids]


@contextmanager
def public_chat_execution_scope(context, user_id, settings):
    """Bind persisted, admitted scope in workers that do not inherit Flask request state."""
    seeds = (context.get("seeds") if isinstance(context, dict) else getattr(context, "seeds", None)) or {}
    selection = normalize_public_workspace_selection(seeds.get("public_workspace_selection"))
    if not selection:
        yield
        return
    resolve_workspace_ids = _context_value(context, "resolve_public_chat_workspace_ids")
    if not callable(resolve_workspace_ids):
        raise PublicChatScopeError("Could not verify the public workspace scope.", "public_chat_scope_unavailable", 503)
    admitted_ids = set(seeds.get("active_public_workspace_ids") or [])
    eligible_ids = resolve_workspace_ids(user_id, selection, settings=settings)
    workspace_ids = [workspace_id for workspace_id in eligible_ids if workspace_id in admitted_ids]
    conversation_id = _context_value(context, "conversation_id")
    if conversation_id:
        read_conversation = _context_value(context, "read_conversation_for_public_chat")
        if not callable(read_conversation):
            raise PublicChatScopeError("Could not verify the conversation's public scope.", "public_chat_conversation_unavailable", 503)
        try:
            conversation = read_conversation(conversation_id)
        except LookupError as error:
            raise PublicChatScopeError("That conversation is no longer available.", "public_chat_conversation_missing", 404) from error
        if not isinstance(conversation, dict):
            raise PublicChatScopeError("Could not verify the conversation's public scope.", "public_chat_conversation_unavailable", 503)
        if conversation.get("user_id") != user_id:
            raise PermissionError("That conversation is not available.")
        workspace_ids = _intersect_public_scope_lock(workspace_ids, conversation)
    if not workspace_ids:
        raise PublicChatScopeError("No public workspaces remain available for this run.", "public_chat_scope_empty", 409)
    with public_chat_scope_context(user_id, selection, workspace_ids, resolve_workspace_ids):
        yield


def _context_value(context, key):
    if isinstance(context, dict):
        return context.get(key)
    return getattr(context, key, None)


def prepare_public_chat_scope(data, user_id, settings, resolve_workspace_ids, conversation=None):
    selection = normalize_public_workspace_selection(data.get("public_workspace_selection"))
    if not selection:
        return None
    if data.get("analysis_result_context") is not None or data.get("workflow_result_context") is not None:
        raise PublicChatScopeError("Return to Current context to ask about a saved result.")
    if data.get("image_generation"):
        raise PublicChatScopeError("Return to Current context to generate an image.")
    workspace_ids = resolve_workspace_ids(user_id, selection, settings=settings)
    workspace_ids = _intersect_public_scope_lock(workspace_ids, conversation)
    if not workspace_ids:
        raise PublicChatScopeError(
            "No public workspaces are available for this scope. Check directory visibility or conversation scope restrictions.",
            "public_chat_scope_empty",
            409,
        )
    scope = {
        "user_id": user_id,
        "selection": selection,
        "workspace_ids": workspace_ids,
        "resolve_public_chat_workspace_ids": resolve_workspace_ids,
    }
    g.public_chat_scope = scope
    data.update({
        "doc_scope": "public",
        "hybrid_search": True,
        "active_group_id": None,
        "active_group_ids": [],
        "active_public_workspace_id": workspace_ids[0],
        "active_public_workspace_ids": workspace_ids,
    })
    return scope


def public_chat_scope_required(
    authorize_conversation, get_current_user_id, get_settings, resolve_workspace_ids, log_event,
):
    """Admit explicit aggregate intent before a route starts model work or streaming."""
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            data = request.get_json(silent=True)
            if not isinstance(data, dict) or data.get("public_workspace_selection") is None:
                return function(*args, **kwargs)
            user_id = get_current_user_id()
            if not user_id:
                return jsonify({"error": "User not authenticated"}), 401
            try:
                conversation_id = data.get("conversation_id")
                conversation = authorize_conversation(user_id, conversation_id) if conversation_id else None
                prepare_public_chat_scope(data, user_id, get_settings(), resolve_workspace_ids, conversation)
            except PublicChatScopeError as error:
                return jsonify({"error": error.public_message, "error_code": error.code}), error.status_code
            except LookupError:
                return jsonify({"error": "Conversation not found"}), 404
            except PermissionError:
                return jsonify({"error": "Forbidden"}), 403
            except Exception as error:
                log_event("[PUBLIC_CHAT_SCOPE] Could not resolve public chat scope.",
                          extra={"error_type": type(error).__name__}, level=logging.ERROR)
                return jsonify({"error": "Could not load the public chat scope. Please retry."}), 503
            return function(*args, **kwargs)
        return wrapped
    return decorate
