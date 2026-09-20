# functions_m365_action_cards.py
"""Request-owned pending-action references and scoped creation events.

Implemented in: 0.261.038 (2026-09-19).
Only the authoritative pending-action producer may record a reference here.
"""

from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import logging
from threading import Lock

from flask import has_request_context, request

from functions_m365_context import get_m365_execution_context


@dataclass
class _References:
    scope: tuple
    items: dict = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock, repr=False)


@dataclass
class _EventSubscription:
    callback: object
    request_scope: object
    execution_scope: tuple | None
    active: bool = True


_task_references = ContextVar("m365_pending_action_references", default=None)
_event_subscription = ContextVar("m365_action_card_events", default=None)
_REFERENCE_FIELDS = ("id", "user_id", "conversation_id", "request_id")


def _valid_identifier(value):
    return (
        isinstance(value, str) and bool(value) and len(value) <= 256
        and not any(ord(char) < 32 for char in value)
    )


def _execution_scope():
    context = get_m365_execution_context()
    if context is None:
        return None
    scope = (context.data_user_id, context.conversation_id, context.request_id)
    return scope if all(_valid_identifier(value) for value in scope) else None


def _references(*, create=False):
    scope = _execution_scope()
    if scope is None:
        return None
    if has_request_context():
        # The actual Request survives copied async contexts and is more specific
        # than g, whose app context can be shared by nested HTTP requests.
        owner = request._get_current_object()
        collections = getattr(owner, "_m365_pending_action_references", None)
        if collections is None:
            if not create:
                return None
            collections = {}
            owner._m365_pending_action_references = collections
        if create:
            return collections.setdefault(scope, _References(scope))
        return collections.get(scope)
    references = _task_references.get()
    if references is None or references.scope != scope:
        if not create:
            return None
        references = _References(scope)
        _task_references.set(references)
    return references


def _log_reference_error(log_event, message, reference, error=None):
    if not callable(log_event):
        raise RuntimeError("The pending-action producer must supply its runtime logger.")
    log_event(
        message,
        extra={
            **{key: value for key, value in reference.items() if _valid_identifier(value)},
            "exception_type": type(error).__name__ if error is not None else None,
            "recovery": "Reload the conversation pending actions; do not repeat the tool call.",
        },
        level=logging.ERROR,
    )


def record_pending_action_reference(action, *, log_event=None):
    """Record an already-persisted action, never a model/tool response snapshot."""
    if not isinstance(action, Mapping):
        return None
    reference = {name: action.get(name) for name in _REFERENCE_FIELDS}
    scope = _execution_scope()
    if (
        scope is None
        or not all(_valid_identifier(value) for value in reference.values())
        or tuple(reference[name] for name in _REFERENCE_FIELDS[1:]) != scope
    ):
        _log_reference_error(
            log_event,
            "[STREAMING] Saved Microsoft 365 action has no matching execution reference.",
            reference,
        )
        return None

    references = _references(create=True)
    with references.lock:
        if reference["id"] in references.items:
            return dict(references.items[reference["id"]])
        references.items[reference["id"]] = reference

    subscription = _event_subscription.get()
    request_scope = request._get_current_object() if has_request_context() else None
    if (
        subscription is not None and subscription.active
        and subscription.request_scope is request_scope
        and subscription.execution_scope in (None, scope)
    ):
        try:
            subscription.callback(dict(reference))
        except Exception as error:
            # The write succeeded. Retain its reference and never turn a UI
            # delivery failure into a retryable tool failure (or a second draft).
            _log_reference_error(
                log_event,
                "[STREAMING] Microsoft 365 action was saved but its live card could not be published.",
                reference,
                error,
            )
    return dict(reference)


def get_request_pending_action_references():
    """Return defensive copies for this exact execution, not inherited requests."""
    references = _references()
    if references is None:
        return []
    with references.lock:
        return [dict(reference) for reference in references.items.values()]


def attach_pending_action_references(message):
    """Persist only IDs on the message belonging to the producing request."""
    if not isinstance(message, dict):
        return message
    scope = _execution_scope()
    if scope is None or message.get("conversation_id") != scope[1]:
        return message
    metadata = message.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        return message
    metadata = metadata if metadata is not None else {}
    if (
        metadata.get("m365_request_id", scope[2]) != scope[2]
        or message.get("request_id", scope[2]) != scope[2]
    ):
        return message
    references = get_request_pending_action_references()
    if references:
        metadata["m365_pending_action_ids"] = [reference["id"] for reference in references]
        message["metadata"] = metadata
    return message


def strip_pending_action_references(value):
    """Copy historical content without carrying executable delivery references."""
    def is_card(item):
        return isinstance(item, dict) and item.get("type") == "msgraph_pending_action"

    if isinstance(value, dict):
        reference_fields = {
            "m365_pending_action_id", "m365_pending_action_ids", "m365_pending_actions",
        }
        result = {
            key: strip_pending_action_references(item)
            for key, item in value.items()
            if key not in reference_fields and not is_card(item)
        }
        if any(key in value for key in reference_fields) or is_card(value.get("pending_action")):
            result.pop("pending_user_action", None)
        return result
    if isinstance(value, list):
        return [strip_pending_action_references(item) for item in value if not is_card(item)]
    return value


@contextmanager
def m365_action_card_events(callback):
    """Bind a task-local callback; copied tasks cannot publish after scope close."""
    if not callable(callback):
        raise TypeError("A Microsoft 365 action-card callback is required.")
    _references(create=True)
    subscription = _EventSubscription(
        callback=callback,
        request_scope=request._get_current_object() if has_request_context() else None,
        execution_scope=_execution_scope(),
    )
    token = _event_subscription.set(subscription)
    try:
        yield
    finally:
        subscription.active = False
        _event_subscription.reset(token)
