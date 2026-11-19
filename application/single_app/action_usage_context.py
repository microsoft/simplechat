# action_usage_context.py
"""Task-local usage identity shared below execution and reporting owners."""

from contextlib import contextmanager
from contextvars import ContextVar


_identity = ContextVar("action_usage_identity", default=None)


def current_action_usage_identity():
    """Return a copy of the explicitly bound, server-authorized execution context."""
    return dict(_identity.get() or {})


@contextmanager
def action_usage_identity(user_id, *, conversation_id="", workspace_type="", group_id="",
                          public_workspace_id="", workflow_id="", run_id="", trigger_type=""):
    """Supply server-authorized background identity, never tool-call arguments."""
    context = dict(
        user_id=user_id, conversation_id=conversation_id, workspace_type=workspace_type,
        group_id=group_id, public_workspace_id=public_workspace_id, workflow_id=workflow_id,
        run_id=run_id, trigger_type=trigger_type,
    )
    token = _identity.set(context)
    try:
        yield
    finally:
        _identity.reset(token)
