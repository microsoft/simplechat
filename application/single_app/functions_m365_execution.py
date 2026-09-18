# functions_m365_execution.py
"""Authoritative, scoped identity and source-policy boundary for Microsoft 365."""

from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Callable

from azure.core.exceptions import AzureError
from flask import g, has_request_context, request

from functions_m365_approvals import (
    M365ApprovalRequired,
    M365PolicyError,
    M365SourceDenied,
    _identifier,
    approval_context,
    get_m365_approval_service,
    logical_request_fingerprint,
    normalize_sharing_policy,
    strictest_sharing_policy,
)
from functions_m365_operations import (
    M365_ACTION_DEFINITIONS,
    M365_INTERNAL_OPERATION_FUNCTIONS,
    M365_LEGACY_OPERATION_SOURCES,
    M365_SOURCES,
    get_m365_action_definition,
    get_m365_enabled_function_names,
    is_m365_action_type,
)
from functions_msgraph_operations import get_msgraph_enabled_function_names
from functions_m365_workflow_binding import workflow_execution_fingerprint


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
_workflow_validator: Callable | None = None
_action_config_resolver: Callable | None = None
_workflow_binding_resolver: Callable | None = None
_action_selection_resolver: Callable | None = None
_AUTHORIZATION_DEPENDENCY_ERRORS = (
    AttributeError, TypeError, ValueError, RuntimeError, LookupError,
    ImportError, OSError, AzureError,
)


def configure_m365_execution(
    *, workflow_validator=None, action_config_resolver=None, workflow_binding_resolver=None,
    action_selection_resolver=None,
):
    """The owner supplies fresh workflow/object authorization, never a session swap."""
    global _workflow_validator, _action_config_resolver, _workflow_binding_resolver, _action_selection_resolver
    _workflow_validator = workflow_validator
    if action_config_resolver is not None:
        _action_config_resolver = action_config_resolver
    if workflow_binding_resolver is not None:
        _workflow_binding_resolver = workflow_binding_resolver
    if action_selection_resolver is not None:
        _action_selection_resolver = action_selection_resolver


def get_m365_execution_context():
    """Flask requests use their own authoritative g; workers use ContextVar scope."""
    if has_request_context():
        context = getattr(g, "m365_execution_context", None)
        return context if isinstance(context, M365ExecutionContext) else None
    return _execution_context.get()


def get_execution_context():
    """Provider-facing alias for the same authoritative scoped context."""
    return get_m365_execution_context()


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


def _update_scoped_context(context):
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


def _invoke_authorizer(callback, *args):
    try:
        return callback(*args)
    except M365PolicyError:
        raise
    except _AUTHORIZATION_DEPENDENCY_ERRORS as exc:
        raise M365PolicyError(
            "m365_authorization_unavailable",
            "Microsoft 365 authorization could not be verified. No source access has been allowed.",
        ) from exc


def require_m365_execution_context(context=None):
    context = context or get_m365_execution_context()
    if not isinstance(context, M365ExecutionContext) or not context.request_id:
        raise M365PolicyError("m365_context_required", "Microsoft 365 requires an authorized logical request.")
    if context.workflow_id:
        if not context.workflow_fingerprint or not context.connection_id:
            raise M365PolicyError("m365_run_as_required", "Select and approve a workflow Run as account first.")
        if _workflow_validator is None or _invoke_authorizer(_workflow_validator, context) is not True:
            raise M365PolicyError(
                "m365_workflow_not_authorized",
                "The current workflow revision and data principal could not be authorized.",
            )
    return context


def validate_m365_workflow_context(context, source=None):
    context = require_m365_execution_context(context)
    if not context.workflow_id:
        raise M365PolicyError("m365_workflow_required", "A workflow Run as context is required.")
    if not context.run_id:
        raise M365PolicyError("m365_run_context_required", "Microsoft 365 workflow access requires an authorized run.")
    # Connection functions do not import config or policy owners at module load.
    from functions_m365_connections import get_m365_connection_service
    connection = get_m365_connection_service().read_connection(
        context.connection_id, context.data_user_id, context.tenant_id,
    )
    return get_m365_approval_service().validate_workflow_binding(context, connection, source)


def _action_sources(config):
    action_type = config.get("type")
    configured_source = config.get("source")
    if configured_source is not None and not isinstance(configured_source, str):
        raise ValueError("Invalid saved Microsoft 365 action source.")
    if is_m365_action_type(action_type):
        source = get_m365_action_definition(action_type)["source"]
        if configured_source is not None and configured_source != source:
            raise M365PolicyError("m365_source_not_authorized", "The saved action source is inconsistent.")
        return {source}
    if action_type == "msgraph" or (action_type is None and configured_source == "legacy"):
        return set(M365_LEGACY_OPERATION_SOURCES.values())
    if action_type is None and configured_source in M365_SOURCES:
        return {configured_source}
    return set()


def _saved_action_policy(context, source, action_id, action_policy):
    config = context.action_configs.get(action_id)
    if config is None and _action_config_resolver is not None:
        config = _invoke_authorizer(_action_config_resolver, context, action_id, source)
    if not isinstance(config, Mapping):
        raise M365PolicyError("m365_action_not_authorized", "This Microsoft 365 action is outside the authorized request.")
    if source not in _action_sources(config):
        raise M365PolicyError("m365_source_not_authorized", "This action cannot access the requested Microsoft 365 source.")
    policies = [_config_policy(config), normalize_sharing_policy(action_policy)]
    for other in context.action_configs.values():
        if isinstance(other, Mapping) and source in _action_sources(other):
            policies.append(_config_policy(other))
    return strictest_sharing_policy(*policies)


def _selected_action_ids(context):
    if _action_selection_resolver is None:
        return None
    selection = _invoke_authorizer(_action_selection_resolver, context)
    if not isinstance(selection, (list, tuple, set, frozenset)) or len(selection) > 1000:
        raise M365PolicyError(
            "m365_action_selection_unavailable",
            "The selected Microsoft 365 actions could not be resolved.",
        )
    try:
        return frozenset(_identifier(action_id) for action_id in selection)
    except ValueError as exc:
        raise M365PolicyError(
            "m365_action_selection_unavailable",
            "The selected Microsoft 365 actions could not be resolved.",
        ) from exc


def authorize_m365_capability(action_id, operation_name, action_type, *, context=None):
    """Revalidate saved tool access without acquiring source consent or credentials."""
    context = context or get_m365_execution_context()
    if not isinstance(context, M365ExecutionContext) or not context.request_id:
        raise M365PolicyError("m365_context_required", "An authorized Microsoft 365 request is required.")
    if action_type != "msgraph" and not is_m365_action_type(action_type):
        raise M365PolicyError("m365_action_not_authorized", "A supported Microsoft 365 action is required.")
    try:
        action_id = _identifier(action_id)
    except ValueError as error:
        raise M365PolicyError("m365_action_not_authorized", "A saved Microsoft 365 action identifier is required.") from error
    if not isinstance(operation_name, str):
        raise M365PolicyError("m365_function_not_authorized", "A valid Microsoft 365 function is required.")
    operation = M365_INTERNAL_OPERATION_FUNCTIONS.get(operation_name, operation_name)
    selected = _selected_action_ids(context)
    if selected is not None and action_id not in selected:
        raise M365PolicyError("m365_action_not_selected", "This action is not selected for the current request.")
    source = (
        get_m365_action_definition(action_type)["source"]
        if is_m365_action_type(action_type) else M365_LEGACY_OPERATION_SOURCES.get(operation)
    )
    prior = context.action_configs.get(action_id)
    current = (
        _invoke_authorizer(_action_config_resolver, context, action_id, source)
        if _action_config_resolver is not None else prior
    )
    if not isinstance(current, Mapping) or current.get("type") != action_type:
        raise M365PolicyError("m365_action_not_authorized", "The current saved Microsoft 365 action is unavailable.")
    try:
        enabled = set(_manifest_functions(current))
        config = dict(prior) if isinstance(prior, Mapping) else dict(current)
        ceiling = strictest_sharing_policy(_config_policy(config), _config_policy(current))
        if isinstance(prior, Mapping):
            if prior.get("type") not in (None, action_type):
                raise M365PolicyError("m365_action_changed", "The selected action changed type.")
            limits = prior.get("enabled_functions")
            if limits is not None:
                if not isinstance(limits, (list, tuple, set, frozenset)):
                    raise ValueError("Invalid request capability bounds.")
                enabled.intersection_update(limits)
    except (TypeError, ValueError) as error:
        raise M365PolicyError("m365_function_not_authorized", "The saved action capabilities are invalid.") from error
    if operation not in enabled:
        raise M365PolicyError(
            "m365_function_not_authorized",
            "This function is not enabled by the current saved Microsoft 365 action and request.",
        )
    config["maximum_sharing_acknowledgement"] = ceiling
    updated = replace(context, action_configs={**context.action_configs, action_id: config})
    _update_scoped_context(updated)
    return updated


def authorize_m365_publication(source, action_id, action_policy=None, *, operation_name, context=None):
    """Authorize disclosure of captured evidence, not a new Microsoft 365 fetch."""
    if source not in {"onedrive", "spo"}:
        raise M365PolicyError("m365_source_not_authorized", "A retained file source is required for publication.")
    action_type = next(
        name for name, definition in M365_ACTION_DEFINITIONS.items() if definition["source"] == source
    )
    context = authorize_m365_capability(action_id, operation_name, action_type, context=context)
    if not context.shared or not context.conversation_id or not context.audience_version:
        raise M365PolicyError("m365_context_required", "An authoritative shared audience is required for publication.")
    if context.actor_user_id != context.data_user_id:
        validate_m365_workflow_context(context, source)
    policy = _saved_action_policy(context, source, action_id, action_policy)
    grant = get_m365_approval_service().authorize_sources(context, {source: policy})[source]
    return context, {"allowed": True, **grant}


def authorize_m365_operation(source, action_id, action_policy=None, *, operation_name=None):
    context = require_m365_execution_context()
    selected_actions = _selected_action_ids(context)
    if selected_actions is not None and action_id not in selected_actions:
        raise M365PolicyError(
            "m365_action_not_selected",
            "This Microsoft 365 action is not selected for the authorized request.",
        )
    current_config = context.action_configs.get(action_id)
    if _action_config_resolver is not None:
        resolved = _invoke_authorizer(_action_config_resolver, context, action_id, source)
        if not isinstance(resolved, Mapping) or source not in _action_sources(resolved):
            raise M365PolicyError("m365_action_not_authorized", "The Microsoft 365 action could not be authorized.")
        previous_config = context.action_configs.get(action_id)
        config = dict(previous_config) if isinstance(previous_config, Mapping) else dict(resolved)
        config["maximum_sharing_acknowledgement"] = strictest_sharing_policy(
            _config_policy(config), _config_policy(resolved),
        )
        updated = replace(context, action_configs={**context.action_configs, action_id: config})
        _update_scoped_context(updated)
        context = updated
        current_config = resolved
    current_type = current_config.get("type") if isinstance(current_config, Mapping) else None
    current_functions = None
    if current_type == "msgraph" or is_m365_action_type(current_type):
        current_functions = _manifest_functions(current_config)
        approved_config = context.action_configs.get(action_id, {})
        approved_functions = approved_config.get("enabled_functions")
        if approved_functions is not None:
            if not isinstance(approved_functions, (list, tuple, set, frozenset)):
                raise M365PolicyError("m365_action_not_authorized", "The authorized Microsoft 365 functions are invalid.")
            current_functions = [name for name in current_functions if name in approved_functions]
        if source not in _manifest_sources(current_config, current_functions):
            raise M365PolicyError(
                "m365_source_not_authorized",
                "This saved action no longer permits remote access to the requested Microsoft 365 source.",
            )
    if operation_name is not None:
        if not isinstance(operation_name, str):
            raise M365PolicyError("m365_function_not_authorized", "A valid Microsoft 365 function name is required.")
        operation = M365_INTERNAL_OPERATION_FUNCTIONS.get(operation_name, operation_name)
        if current_functions is None or operation not in current_functions:
            raise M365PolicyError(
                "m365_function_not_authorized",
                "This function is not enabled by the current saved Microsoft 365 action and request.",
            )
    if context.workflow_id:
        validate_m365_workflow_context(context, source)
    policy = _saved_action_policy(context, source, action_id, action_policy)
    grant = get_m365_approval_service().authorize_sources(context, {source: policy})[source]
    return {"allowed": True, **grant}


def _manifest_functions(manifest):
    additional = manifest.get("additionalFields", {})
    if not isinstance(additional, Mapping):
        raise ValueError("Invalid Microsoft 365 additional fields.")
    explicit = manifest.get("enabled_functions")
    if explicit is not None and (
        not isinstance(explicit, (list, tuple, set, frozenset))
        or any(not isinstance(name, str) for name in explicit)
    ):
        raise ValueError("Microsoft 365 enabled functions must be function names.")
    action_type = manifest["type"]
    if is_m365_action_type(action_type):
        saved = additional.get("m365_capabilities", manifest.get("m365_capabilities"))
        saved = dict(saved) if isinstance(saved, Mapping) else saved
        runtime = manifest.get("m365_capabilities")
        runtime = dict(runtime) if isinstance(runtime, Mapping) else runtime
        return get_m365_enabled_function_names(
            action_type, saved, enabled_functions=explicit, agent_capabilities=runtime,
        )
    saved = additional.get("msgraph_capabilities", manifest.get("msgraph_capabilities"))
    saved = dict(saved) if isinstance(saved, Mapping) else saved
    functions = get_msgraph_enabled_function_names(saved)
    runtime = manifest.get("msgraph_capabilities")
    if runtime is not None:
        runtime = dict(runtime) if isinstance(runtime, Mapping) else runtime
        runtime_functions = set(get_msgraph_enabled_function_names(runtime))
        functions = [name for name in functions if name in runtime_functions]
    if explicit is not None:
        functions = [name for name in functions if name in explicit]
    return functions


def _manifest_sources(manifest, functions):
    if is_m365_action_type(manifest["type"]):
        if not set(functions) - {"read_file_chunk", "analyze_file"}:
            return set()
        return {get_m365_action_definition(manifest["type"])["source"]}
    return {M365_LEGACY_OPERATION_SOURCES[name] for name in functions if name in M365_LEGACY_OPERATION_SOURCES}


def _config_policy(config):
    additional = config.get("additionalFields", {})
    if not isinstance(additional, Mapping):
        raise ValueError("Invalid saved Microsoft 365 action policy.")
    return strictest_sharing_policy(
        config.get("maximum_sharing_acknowledgement"),
        additional.get("maximum_sharing_acknowledgement"),
    )


def _bind_preflight_manifests(context, manifests):
    configs = dict(context.action_configs)
    selected_actions = _selected_action_ids(context)
    if selected_actions is None and _action_config_resolver is None and configs:
        selected_actions = frozenset(configs)
    policies = {}
    normalized = []
    seen = set()
    for manifest in manifests:
        if not isinstance(manifest, dict):
            raise ValueError("Action manifests must be objects.")
        action_type = manifest.get("type")
        if action_type != "msgraph" and not is_m365_action_type(action_type):
            normalized.append(manifest)
            continue
        action_id = _identifier(manifest.get("id") or manifest.get("name"))
        if selected_actions is not None and action_id not in selected_actions:
            continue
        if action_id in seen:
            raise M365PolicyError("m365_action_ambiguous", "The selected Microsoft 365 actions have ambiguous identifiers.")
        seen.add(action_id)
        enabled = _manifest_functions(manifest)
        if not enabled:
            continue
        sources = _manifest_sources(manifest, enabled)
        effective = {**manifest, "enabled_functions": enabled}
        if not sources:
            normalized.append(effective)
            continue
        prior = configs.get(action_id)
        ceiling = _config_policy(manifest)
        authoritative_configs = []
        for source in sources:
            if _action_config_resolver is not None:
                authoritative = _invoke_authorizer(_action_config_resolver, context, action_id, source)
            else:
                authoritative = prior
            if not isinstance(authoritative, Mapping) or source not in _action_sources(authoritative):
                raise M365PolicyError(
                    "m365_action_not_authorized",
                    "A current saved Microsoft 365 action must be authorized before its tools are enabled.",
                )
            if authoritative.get("type") not in (None, action_type):
                raise M365PolicyError("m365_action_changed", "The selected Microsoft 365 action changed type.")
            authoritative_configs.append(authoritative)
            ceiling = strictest_sharing_policy(ceiling, _config_policy(authoritative))
        for authoritative in authoritative_configs:
            saved_functions = authoritative.get("enabled_functions")
            if saved_functions is not None:
                if not isinstance(saved_functions, (list, tuple, set, frozenset)):
                    raise ValueError("Invalid saved Microsoft 365 functions.")
                enabled = [name for name in enabled if name in saved_functions]
            if authoritative.get("type") == action_type and (
                "m365_capabilities" in authoritative or "msgraph_capabilities" in authoritative
                or "additionalFields" in authoritative
            ):
                saved_enabled = set(_manifest_functions(authoritative))
                enabled = [name for name in enabled if name in saved_enabled]
        if not enabled:
            continue
        sources = _manifest_sources(manifest, enabled)
        if not sources:
            normalized.append({**effective, "enabled_functions": enabled})
            continue
        if isinstance(prior, Mapping):
            if not sources.issubset(_action_sources(prior)):
                raise M365PolicyError("m365_action_changed", "The selected Microsoft 365 action changed source.")
            ceiling = strictest_sharing_policy(ceiling, _config_policy(prior))
        prior_functions = prior.get("enabled_functions", ()) if isinstance(prior, Mapping) else ()
        if not isinstance(prior_functions, (list, tuple, set, frozenset)):
            raise ValueError("Invalid authorized Microsoft 365 function snapshot.")
        configs[action_id] = {
            "type": action_type,
            "source": "legacy" if action_type == "msgraph" else next(iter(sources)),
            "additionalFields": authoritative_configs[0].get("additionalFields", {}),
            "maximum_sharing_acknowledgement": ceiling,
            # A narrower repeated loader pass must not invalidate a request grant.
            "enabled_functions": sorted(set(prior_functions) | set(enabled)),
        }
        for source in sources:
            policies[source] = strictest_sharing_policy(policies.get(source), ceiling)
        normalized.append({
            **effective, "enabled_functions": enabled,
            "maximum_sharing_acknowledgement": ceiling,
        })
    return replace(context, action_configs=configs), normalized, policies


def preflight_m365_manifests(manifests):
    """Authorize effective saved tools before loading; absence of a context is bootstrap only."""
    context = get_execution_context()
    if context is None:
        return manifests
    if not isinstance(manifests, list):
        raise M365PolicyError("m365_preflight_invalid", "Microsoft 365 action manifests must be a list.")
    try:
        context, permitted, policies = _bind_preflight_manifests(context, manifests)
        _update_scoped_context(context)
        if not policies:
            return permitted
        if context.workflow_id and _workflow_binding_resolver is not None:
            resolved = _invoke_authorizer(_workflow_binding_resolver, context, permitted, dict(policies))
            fixed_fields = (
                "actor_user_id", "data_user_id", "tenant_id", "conversation_id",
                "shared", "request_id", "workflow_id", "run_id", "audience_version",
                "group_id", "agent_id", "step_id", "action_configs",
            )
            if not isinstance(resolved, M365ExecutionContext) or any(
                getattr(context, name) != getattr(resolved, name) for name in fixed_fields
            ):
                raise M365PolicyError(
                    "m365_principal_mismatch",
                    "The workflow binding resolver cannot replace the request's identity, actions or audience.",
                )
            context = resolved
            _update_scoped_context(context)
        denied = set()
        grants = {}
        while policies:
            try:
                grants = authorize_m365_sources(policies, context=context)
                break
            except M365SourceDenied as exc:
                source = exc.payload["source"]
                if source not in policies:
                    raise
                denied.add(source)
                policies.pop(source)
        if has_request_context():
            logical_request = logical_request_fingerprint(context)
            previous_denied = (
                set(getattr(g, "m365_declined_sources", ()))
                if getattr(g, "m365_declined_sources_request", None) == logical_request
                else set()
            )
            g.m365_source_grants = grants
            g.m365_declined_sources = sorted(previous_denied | denied)
            g.m365_declined_sources_request = logical_request
        if not denied:
            return permitted
        filtered = []
        for manifest in permitted:
            action_type = manifest.get("type")
            if action_type == "msgraph":
                enabled = [
                    name for name in manifest["enabled_functions"]
                    if M365_LEGACY_OPERATION_SOURCES.get(name) not in denied
                ]
                if enabled:
                    filtered.append({**manifest, "enabled_functions": enabled})
            elif is_m365_action_type(action_type):
                source = get_m365_action_definition(action_type)["source"]
                if source not in denied:
                    filtered.append(manifest)
                else:
                    snapshot_functions = [
                        name for name in manifest["enabled_functions"]
                        if name in {"read_file_chunk", "analyze_file"}
                    ]
                    if snapshot_functions:
                        filtered.append({**manifest, "enabled_functions": snapshot_functions})
            else:
                filtered.append(manifest)
        return filtered
    except M365PolicyError:
        raise
    except _AUTHORIZATION_DEPENDENCY_ERRORS as exc:
        raise M365PolicyError(
            "m365_preflight_unavailable",
            "Microsoft 365 authorization could not be verified. No source access has been allowed.",
        ) from exc


def authorize_m365_sources(sources, context=None):
    """Preflight an authoritative source-to-ceiling mapping for one combined prompt."""
    context = require_m365_execution_context(context)
    if context.workflow_id:
        for source in sources:
            validate_m365_workflow_context(context, source)
    return get_m365_approval_service().authorize_sources(context, sources)


def authorize_m365_extended_analysis(source, proposal=None, *, action_id=None, context=None):
    context = require_m365_execution_context(context)
    if action_id is not None:
        with m365_execution_context(context):
            authorize_m365_operation(source, action_id)
    elif context.workflow_id:
        validate_m365_workflow_context(context, source)
    return get_m365_approval_service().authorize_extended_analysis(context, source, proposal)


def create_m365_workflow_binding(context, sources, *, review):
    """Create a consent request only after current workflow and connection checks."""
    context = require_m365_execution_context(context)
    if not context.workflow_id:
        raise M365PolicyError("m365_workflow_required", "A workflow Run as context is required.")
    from functions_m365_connections import get_m365_connection_service
    connection = get_m365_connection_service().read_connection(
        context.connection_id, context.data_user_id, context.tenant_id,
    )
    return get_m365_approval_service().ensure_workflow_binding(
        context, sources, connection, review=review,
    )


def prepare_m365_workflow_binding(context, workflow, effective_manifests, *, review):
    """Bind an owner-authorized workflow using its actual effective action revision."""
    if not isinstance(context, M365ExecutionContext) or not context.workflow_id:
        raise M365PolicyError("m365_workflow_required", "An authoritative workflow execution context is required.")
    if not isinstance(workflow, Mapping) or workflow.get("id") != context.workflow_id:
        raise M365PolicyError("m365_workflow_not_authorized", "The workflow does not match this execution.")
    selected_user = workflow.get("m365_run_as_user_id")
    if not isinstance(selected_user, str) or not selected_user.strip():
        raise M365PolicyError("m365_run_as_required", "Select a Microsoft 365 Run as account explicitly.")
    if selected_user.strip() != context.data_user_id:
        raise M365PolicyError("m365_principal_mismatch", "The selected Run as user does not match the data principal.")
    if not isinstance(effective_manifests, list) or any(not isinstance(item, dict) for item in effective_manifests):
        raise M365PolicyError("m365_preflight_invalid", "Effective workflow actions must be supplied.")
    sources = set()
    for manifest in effective_manifests:
        if manifest.get("type") == "msgraph" or is_m365_action_type(manifest.get("type")):
            sources.update(_manifest_sources(manifest, _manifest_functions(manifest)))
    if not sources:
        raise M365PolicyError("m365_workflow_sources_required", "This workflow has no effective remote Microsoft 365 operations.")
    fingerprint = workflow_execution_fingerprint(workflow, effective_manifests)
    candidate = replace(context, workflow_fingerprint=fingerprint, connection_id=None, binding_id=None)
    if (
        not candidate.request_id or _workflow_validator is None
        or _invoke_authorizer(_workflow_validator, candidate) is not True
    ):
        raise M365PolicyError("m365_workflow_not_authorized", "The current workflow and selected data user could not be authorized.")
    # Configured connection lookup is runtime-only and never substitutes an owner.
    from functions_m365_connections import get_m365_connection_service
    connection = get_m365_connection_service().current_connection(
        context.data_user_id, context.tenant_id,
    )
    if not connection or connection.get("status") != "connected":
        raise M365PolicyError("m365_connection_required", "The selected Run as user must connect Microsoft 365 in Profile.")
    resolved = replace(
        candidate, connection_id=connection["id"],
    )
    require_m365_execution_context(resolved)
    approval = get_m365_approval_service().ensure_workflow_binding(
        resolved, sources, connection, review=review,
    )
    return replace(resolved, binding_id=approval["id"])
