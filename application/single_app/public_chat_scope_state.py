# public_chat_scope_state.py
"""Pure request and worker state for aggregate public chat."""

from contextlib import contextmanager
from contextvars import ContextVar

from flask import g, has_request_context


_PUBLIC_CHAT_SCOPE = ContextVar("public_chat_scope", default=None)


class PublicChatScopeError(ValueError):
    """A safe refusal that must not be downgraded to an ordinary document search."""

    def __init__(self, message, code="public_chat_scope_invalid", status_code=400):
        super().__init__(message)
        self.public_message = message
        self.code = code
        self.status_code = status_code


def normalize_public_workspace_selection(value):
    if value is None:
        return None
    if not isinstance(value, str) or value not in ("all", "visible"):
        raise PublicChatScopeError("Choose All or Visible public workspaces.")
    return value


def current_public_chat_scope(user_id):
    scope = _PUBLIC_CHAT_SCOPE.get()
    if scope is None and has_request_context():
        scope = getattr(g, "public_chat_scope", None)
    return scope if isinstance(scope, dict) and scope.get("user_id") == user_id else None


@contextmanager
def public_chat_scope_context(user_id, selection, workspace_ids, resolve_workspace_ids=None):
    selection = normalize_public_workspace_selection(selection)
    scope = {
        "user_id": user_id,
        "selection": selection,
        "workspace_ids": list(workspace_ids),
        "resolve_public_chat_workspace_ids": resolve_workspace_ids,
    }
    token = _PUBLIC_CHAT_SCOPE.set(scope if selection else None)
    try:
        yield
    finally:
        _PUBLIC_CHAT_SCOPE.reset(token)


def aggregate_public_workspace_ids(user_id):
    """Recheck availability without allowing downstream tools to widen an admitted turn."""
    scope = current_public_chat_scope(user_id)
    if not scope:
        return None
    resolver = scope.get("resolve_public_chat_workspace_ids")
    if not callable(resolver):
        raise PublicChatScopeError(
            "Could not verify the public workspace scope.", "public_chat_scope_unavailable", 503,
        )
    eligible = resolver(user_id, scope["selection"])
    allowed = set(scope["workspace_ids"])
    workspace_ids = [workspace_id for workspace_id in eligible if workspace_id in allowed]
    if not workspace_ids:
        raise PublicChatScopeError(
            "No public workspaces remain available for this search.", "public_chat_scope_empty", 409,
        )
    return workspace_ids
