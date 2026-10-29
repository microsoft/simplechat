# functions_m365_context.py
"""Dependency-light Microsoft 365 identity, scope, and policy value primitives."""

from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import hashlib
import json
from types import MappingProxyType

from flask import g, has_request_context, request


class M365PolicyError(Exception):
    """A stable, non-content-bearing policy failure."""

    def __init__(self, code: str, message: str, **details):
        super().__init__(message)
        self.code = code
        self.payload = {"error": code, "message": message, **details}


def _identifier(value):
    if (
        not isinstance(value, str) or not value or len(value) > 256
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError("A valid Microsoft 365 context identifier is required.")
    return value


def _json_value(value):
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("Microsoft 365 context must contain JSON-compatible values.")


def material_fingerprint(value):
    encoded = json.dumps(
        _json_value(value), sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def approval_context(context):
    result = {
        name: getattr(context, name, None)
        for name in (
            "actor_user_id", "data_user_id", "tenant_id", "conversation_id",
            "request_id", "workflow_id", "run_id", "step_id", "agent_id",
            "audience_version", "workflow_fingerprint", "connection_id", "binding_id",
            "group_id",
        )
    }
    for name in ("actor_user_id", "data_user_id", "tenant_id"):
        _identifier(result[name])
    for value in result.values():
        if value is not None:
            _identifier(value)
    result["shared"] = bool(context.shared)
    result["action_ids"] = sorted(_identifier(action_id) for action_id in context.action_configs)[:64]
    result["action_count"] = len(context.action_configs)
    result["action_fingerprint"] = material_fingerprint(context.action_configs)
    return result


def _immutable(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _immutable(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_immutable(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("Execution configuration must be JSON-compatible.")


@dataclass(frozen=True)
class M365ExecutionContext:
    actor_user_id: str
    data_user_id: str
    tenant_id: str
    conversation_id: str | None = None
    shared: bool = False
    request_id: str | None = None
    workflow_id: str | None = None
    run_id: str | None = None
    step_id: str | None = None
    agent_id: str | None = None
    audience_version: str | None = None
    action_configs: Mapping = field(default_factory=dict, repr=False)
    binding_id: str | None = None
    workflow_fingerprint: str | None = None
    connection_id: str | None = None
    group_id: str | None = None

    def __post_init__(self):
        if type(self.shared) is not bool or not isinstance(self.action_configs, Mapping):
            raise ValueError("Invalid authoritative Microsoft 365 execution context.")
        object.__setattr__(self, "action_configs", _immutable(self.action_configs))
        approval_context(self)
        if not self.workflow_id and self.actor_user_id != self.data_user_id:
            raise M365PolicyError("m365_principal_mismatch", "Direct Microsoft 365 access must use your own identity.")


@dataclass
class _RequestExecutionToken:
    request_scope: object = field(repr=False)
    previous: object = field(repr=False)
    existed: bool
    used: bool = False


_execution_context = ContextVar("m365_execution_context", default=None)


def get_m365_execution_context():
    """HTTP requests never inherit an unrelated worker's execution identity."""
    if has_request_context():
        context = getattr(g, "m365_execution_context", None)
        return context if isinstance(context, M365ExecutionContext) else None
    return _execution_context.get()


def set_m365_execution_context(context):
    if not isinstance(context, M365ExecutionContext):
        raise TypeError("An authoritative Microsoft 365 context is required.")
    if has_request_context():
        token = _RequestExecutionToken(
            request_scope=request._get_current_object(),
            previous=getattr(g, "m365_execution_context", None),
            existed="m365_execution_context" in g,
        )
        g.m365_execution_context = context
        return token
    return _execution_context.set(context)


def reset_m365_execution_context(token):
    if isinstance(token, _RequestExecutionToken):
        if token.used:
            raise RuntimeError("This Microsoft 365 request scope was already reset.")
        if not has_request_context() or request._get_current_object() is not token.request_scope:
            raise RuntimeError("This Microsoft 365 execution scope belongs to another request.")
        if token.existed:
            g.m365_execution_context = token.previous
        else:
            g.pop("m365_execution_context", None)
        token.used = True
        return
    _execution_context.reset(token)


def update_m365_execution_context(context):
    if has_request_context():
        g.m365_execution_context = context
    elif _execution_context.get() is not None:
        _execution_context.set(context)
    else:
        raise M365PolicyError("m365_context_required", "Enter an explicit Microsoft 365 execution scope first.")


@contextmanager
def m365_execution_context(context):
    token = set_m365_execution_context(context)
    try:
        yield context
    finally:
        reset_m365_execution_context(token)
