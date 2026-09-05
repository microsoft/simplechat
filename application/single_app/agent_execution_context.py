# agent_execution_context.py
"""Task-local identity and per-turn limits for agent execution."""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable, Optional
import uuid


class AgentDelegationError(RuntimeError):
    """A safe, attributable delegation failure."""


class AgentExecutionCancelled(AgentDelegationError):
    """The invoking turn was stopped; remote effects are not rolled back."""


@dataclass
class DelegationBudget:
    """One lock-protected budget shared by descendants, siblings and retries."""

    attempts: int = 0
    maximum: int = 10
    root_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    records: list = field(default_factory=list)
    _tool_invocations: list = field(default_factory=list, repr=False)
    _authentication_requirement: Optional[Exception] = field(default=None, repr=False)
    _authentication_published: bool = field(default=False, repr=False)
    _drained_records: dict = field(default_factory=dict, repr=False)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def consume(self):
        with self._lock:
            self.attempts += 1
            if self.attempts > self.maximum:
                raise AgentDelegationError("The agent call limit for this turn was reached.")

    def record(self, record):
        with self._lock:
            if not any(item["invocation_id"] == record["invocation_id"] for item in self.records):
                self.records.append(deepcopy(record))

    def snapshot(self):
        with self._lock:
            return deepcopy(self.records)

    def record_tool_invocation(self, invocation):
        with self._lock:
            self._tool_invocations.append(invocation)

    def invocations(self):
        with self._lock:
            return list(self._tool_invocations)

    def require_authentication(self, error):
        with self._lock:
            if self._authentication_requirement is None:
                self._authentication_requirement = error

    def raise_authentication_requirement(self, identity):
        with self._lock:
            error = self._authentication_requirement
            publish = error is not None and not self._authentication_published
            if publish:
                self._authentication_published = True
        if error is not None:
            if publish and identity.publish_authentication_requirement:
                identity.publish_authentication_requirement(deepcopy(getattr(error, "auth_response", {}) or {}))
            raise error

    def drain_completed_records(self, consumer_id, excluded_ids=()):
        with self._lock:
            drained = self._drained_records.setdefault(consumer_id, set(excluded_ids))
            records = [
                record for record in self.records
                if record.get("success") and record["invocation_id"] not in drained
            ]
            drained.update(record["invocation_id"] for record in records)
            return deepcopy(records)


@dataclass(frozen=True)
class ExecutionIdentity:
    user_id: str
    conversation_id: Optional[str] = None
    bridge: Optional[Callable] = field(default=None, repr=False, compare=False)
    roles: tuple = ()
    email: Optional[str] = None
    publish_authentication_requirement: Optional[Callable] = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class AgentExecutionFrame:
    identity: ExecutionIdentity
    caller: dict
    budget: DelegationBudget
    ancestors: tuple = ()
    depth: int = 0
    invocation_id: Optional[str] = None
    parent_invocation_id: Optional[str] = None
    action_id: Optional[str] = None
    deadline: Optional[float] = None
    cancel_requested: Optional[Callable] = field(default=None, repr=False, compare=False)


_execution_frame = ContextVar("agent_execution_frame", default=None)


def current_agent_execution():
    return _execution_frame.get()


def execution_user_id():
    frame = current_agent_execution()
    return frame.identity.user_id if frame else None


@contextmanager
def agent_execution(frame):
    token = _execution_frame.set(frame)
    try:
        yield frame
    finally:
        _execution_frame.reset(token)


def capture_execution_identity(user_id, conversation_id=None):
    """Capture only server-authenticated identity, never parent prompt or workspace state.

    Flask is imported here because workers use the context types without a Flask
    dependency. The closure creates a distinct app/request context for every
    invocation; concurrent children never share ``g`` or a mutable session.
    """
    from flask import current_app, g, has_request_context, request, session

    if not has_request_context():
        return ExecutionIdentity(user_id, conversation_id)
    authenticated_user = session.get("user") or {}
    if str(authenticated_user.get("oid") or "") != str(user_id or ""):
        raise PermissionError("The agent execution identity is unavailable.")
    app = current_app._get_current_object()
    origin = request.host_url
    identity_session = {"user": deepcopy(authenticated_user)}
    root_session = session._get_current_object()
    if session.get("token_cache"):
        identity_session["token_cache"] = session["token_cache"]

    def publish_authentication_requirement(auth_response):
        # Only the trusted OAuth scope request crosses back into the original
        # session. Streamed consent URLs additionally re-enter a normal auth-init
        # request because this session may already have been saved with headers.
        # Child caches, roles and workspace preferences remain isolated.
        scopes = auth_response.get("scopes")
        if isinstance(scopes, (list, tuple)):
            root_session["requested_oauth_scopes"] = list(dict.fromkeys(
                scope.strip() for scope in scopes if isinstance(scope, str) and scope.strip()
            ))

    @contextmanager
    def bridge(agent):
        # An app context as well as a request context is needed to isolate g.
        with app.app_context(), app.test_request_context("/internal/agent-execution", base_url=origin):
            session.update(deepcopy(identity_session))
            g.conversation_id = conversation_id
            g.request_agent_info = deepcopy(agent)
            g.request_agent_name = agent.get("name")
            group_id = agent.get("group_id") if agent.get("is_group") else None
            g.authorized_chat_context = {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "active_group_ids": [group_id] if group_id else [],
                "active_group_id": group_id,
                "active_public_workspace_ids": [],
                "active_public_workspace_id": None,
                "fact_memory_scope_type": "group" if group_id else "personal",
                "fact_memory_scope_id": group_id or user_id,
            }
            if group_id:
                g.conversation_group_id = group_id
            yield

    return ExecutionIdentity(
        user_id, conversation_id, bridge,
        tuple(authenticated_user.get("roles") or ()), authenticated_user.get("preferred_username"),
        publish_authentication_requirement,
    )
