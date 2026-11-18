# action_usage.py
"""Content-free action bindings; importing this module does not bootstrap the app."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
import functools
import inspect
import time
import uuid
from urllib.parse import urlsplit

from functions_action_manifest import get_action_origin, resolve_action_type
import runtime_usage


_attempt = ContextVar("action_usage_attempt", default=None)
_identity = ContextVar("action_usage_identity", default=None)
_AUTH_CATEGORIES = frozenset({
    "none", "unknown", "not_applicable", "api_key", "basic", "bearer", "oauth2",
    "oauth", "managed_identity", "service_principal", "username_password",
    "password", "key_pair", "pat", "identity", "servicePrincipal",
    "personal_access_token", "bearer_token", "user",
})


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


def _execution_identity():
    explicit = _identity.get()
    if explicit is not None:
        return dict(explicit)
    # Execution identity is runtime-owned; defer imports to preserve discovery/bootstrap safety.
    from agent_execution_context import current_agent_execution

    frame = current_agent_execution()
    if frame is not None:
        return {"user_id": frame.identity.user_id, "conversation_id": frame.identity.conversation_id or ""}
    from flask import g, has_request_context

    if not has_request_context():
        return {}
    from functions_authentication import get_current_user_id

    context = {"user_id": get_current_user_id()}
    authorized = getattr(g, "authorized_chat_context", None)
    if isinstance(authorized, dict):
        for field in ("conversation_id", "workspace_type", "group_id", "public_workspace_id"):
            context[field] = authorized.get(field) or ""
    return context


def _auth_category(manifest, action_type):
    auth = manifest.get("auth")
    auth = auth if isinstance(auth, dict) else {}
    fields = manifest.get("additionalFields")
    fields = fields if isinstance(fields, dict) else {}
    auth_type = auth.get("type")
    method = fields.get("auth_method")
    # These pure connector normalizers implement different legacy defaults and aliases.
    if action_type == "mcp":
        from functions_mcp_operations import normalize_mcp_auth_method

        identity_method = fields.get("identity_auth_type")
        if identity_method:
            method = identity_method
        elif auth_type == "identity":
            return "unknown"
        method = normalize_mcp_auth_method(method)
        if method == "none" and fields.get("custom_headers"):
            method = "unknown"
    elif action_type in {"databricks", "databricks_table"}:
        from functions_databricks_operations import normalize_databricks_auth_method

        method = normalize_databricks_auth_method(method, auth_type=auth_type or "")
    elif action_type == "snowflake":
        from functions_snowflake_operations import normalize_snowflake_auth_method

        method = normalize_snowflake_auth_method(method, auth_type=auth_type or "")
    elif action_type == "tableau":
        from functions_tableau_operations import normalize_tableau_auth_method

        method = normalize_tableau_auth_method(fields, auth_type=auth_type or "key")
    elif action_type == "yamcs":
        from functions_yamcs_operations import normalize_yamcs_auth_method

        method = normalize_yamcs_auth_method(fields, auth_type=auth_type or "username_password")
    elif auth_type == "none":
        method = "none"
    elif action_type == "openapi" and not auth_type:
        method = "none"
    elif auth_type == "key":
        method = method or "api_key"
    else:
        method = method or auth_type
        if not method and action_type.lower().replace("_", "").removesuffix("plugin") in {
            "documentsearch", "search",
        }:
            method = "not_applicable"
    return method if isinstance(method, str) and method in _AUTH_CATEGORIES else "unknown"


def action_usage_target(manifest):
    """Snapshot only authorized configuration metadata, never retain the manifest."""
    origin = get_action_origin(manifest)
    if origin is None or not origin.action_id:
        return None
    declared_type = resolve_action_type(manifest)
    compact_type = declared_type.lower().replace("_", "").replace("-", "").removesuffix("plugin")
    connector_types = {
        "mcp": "mcp", "openapi": "openapi", "databricks": "databricks",
        "databrickstable": "databricks_table", "snowflake": "snowflake",
        "tableau": "tableau", "yamcs": "yamcs", "bitbucket": "bitbucket",
    }
    action_type = connector_types.get(compact_type, declared_type)
    fields = manifest.get("additionalFields")
    fields = fields if isinstance(fields, dict) else {}
    endpoint = manifest.get("base_url") or manifest.get("endpoint")
    if not endpoint:
        endpoint = fields.get("server_url") or fields.get("workspace_url")
    # MCP websocket destinations share the same configured-host-only projection.
    if isinstance(endpoint, str):
        try:
            parsed = urlsplit(endpoint)
            if parsed.scheme in {"ws", "wss"} and action_type == "mcp":
                endpoint = parsed._replace(scheme="https").geturl()
        except ValueError:
            endpoint = ""
    host = runtime_usage.configured_host(endpoint) if endpoint else (
        "unknown" if compact_type in connector_types else "not_applicable"
    )
    return runtime_usage.UsageTarget(
        kind="action", entity_id=origin.action_id,
        name=runtime_usage.bounded_text(manifest.get("name")),
        scope_type=origin.scope_type, scope_id=origin.scope_id,
        entity_type=runtime_usage.bounded_text(action_type, 80),
        endpoint_host=host, auth_type=_auth_category(manifest, action_type),
    )


@dataclass
class _Attempt:
    target: runtime_usage.UsageTarget
    identity: dict
    attempt_id: str
    started: float
    failed: bool = False
    dispatched: bool = False
    authentication_pending: bool = False


def report_action_usage_failure():
    """Mark a connector-declared failure without accepting its error text."""
    attempt = _attempt.get()
    if attempt is not None:
        attempt.failed = True


def report_action_authentication_pending():
    """Credential continuation before dispatch is not successful action use."""
    attempt = _attempt.get()
    if attempt is not None:
        attempt.authentication_pending = True


def _emit(attempt, error=None):
    if attempt.dispatched or attempt.authentication_pending or not attempt.identity.get("user_id"):
        return
    if error is not None and type(error).__name__ == "FoundryAgentUserAuthenticationRequired":
        return
    outcome = runtime_usage.exception_outcome(error) if error is not None else (
        "failed" if attempt.failed else "succeeded"
    )
    try:
        runtime_usage.emit_usage(
            attempt.target, **attempt.identity, attempt_id=attempt.attempt_id, outcome=outcome,
            duration_ms=(time.perf_counter() - attempt.started) * 1000,
        )
    except Exception:
        # A telemetry failure must never retry an external effect or mask its exception.
        try:
            from functions_appinsights import log_event

            log_event("[PLUGIN_FUNCTION_LOGGER] Usage persistence failed", extra={"reason": "usage_write_failed"})
        except Exception:
            pass


@contextmanager
def action_dispatch_attempt(operation=None):
    """Count each genuine connector retry, suppressing the surrounding logical wrapper."""
    parent = _attempt.get()
    if parent is None:
        yield
        return
    parent.dispatched = True
    target = replace(parent.target, operation=runtime_usage.bounded_text(operation)) if operation else parent.target
    attempt = _Attempt(target, dict(parent.identity), str(uuid.uuid4()), time.perf_counter())
    token = _attempt.set(attempt)
    error = None
    try:
        yield
    except BaseException as exc:
        error = exc
        raise
    finally:
        _attempt.reset(token)
        _emit(attempt, error)


def bind_action_callable(function, target, operation):
    """Return a binding-local wrapper; class-level/self-logging functions remain untouched."""
    if target is None:
        return function
    target = replace(target, operation=runtime_usage.bounded_text(operation))
    if getattr(function, "__action_usage_target__", None) == target:
        return function

    def begin():
        try:
            identity = _execution_identity()
        except Exception:
            identity = {}
        attempt = _Attempt(target, identity, str(uuid.uuid4()), time.perf_counter())
        return attempt, _attempt.set(attempt)

    def finish(attempt, token, error):
        if attempt is not None:
            _attempt.reset(token)
            _emit(attempt, error)

    if inspect.iscoroutinefunction(function):
        @functools.wraps(function)
        async def wrapped(*args, **kwargs):
            attempt, token = begin()
            error = None
            try:
                return await function(*args, **kwargs)
            except BaseException as exc:
                error = exc
                raise
            finally:
                finish(attempt, token, error)
    else:
        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            attempt, token = begin()
            error = None
            try:
                result = function(*args, **kwargs)
            except BaseException as exc:
                error = exc
                finish(attempt, token, error)
                raise
            if inspect.isawaitable(result):
                # Reset in the creating context; coroutine completion may run in another task.
                if attempt is not None:
                    _attempt.reset(token)

                async def complete():
                    await_token = _attempt.set(attempt) if attempt is not None else None
                    await_error = None
                    try:
                        return await result
                    except BaseException as exc:
                        await_error = exc
                        raise
                    finally:
                        finish(attempt, await_token, await_error)

                return complete()
            finish(attempt, token, error)
            return result
    wrapped.__action_usage_target__ = target
    return wrapped


def bind_prepared_action(prepared, manifest):
    """Bind generated kernel methods as well as native/self-logged methods by canonical origin."""
    target = action_usage_target(manifest)
    fields = manifest.get("additionalFields")
    fields = fields if isinstance(fields, dict) else {}
    tools = fields.get("mcp_tools")
    operations = {
        tool["function_name"]: tool["original_name"]
        for tool in tools if isinstance(tool, dict)
        and isinstance(tool.get("function_name"), str) and isinstance(tool.get("original_name"), str)
    } if isinstance(tools, list) else {}
    for name, function in prepared.functions.items():
        method = getattr(function, "method", None)
        if callable(method):
            function.method = bind_action_callable(method, target, operations.get(name, name))
