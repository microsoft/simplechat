# functions_orchestration_external_metadata.py
"""Initialized-application, metadata-only reconstruction of external sources.

Version: 0.261.127

This is a composition boundary, not a configuration or credential factory for
execution. Runtime stores, loaders and SDKs are imported only after current
conversation ownership is established. No acquisition capture is read here.
"""

from contextlib import ExitStack
from copy import deepcopy
import math
from time import monotonic
from urllib.parse import urlsplit

from functions_action_catalog import _action_ref, resolve_action_manifest
from functions_action_manifest import get_action_origin, resolve_action_type
from functions_agent_delegation import agent_reference, resolve_delegation_agent
from functions_orchestration_external_configuration import (
    EXTERNAL_ACQUISITION_VERSION,
    FOUNDRY_OBSERVED_RUN,
    MAX_CONFIGURATION_BYTES,
    ExternalConfigurationCancelledError,
    ExternalConfigurationServiceError,
    _endpoint,
    _http_failure,
    _pinned_tools,
    _read_metadata,
    _record_configuration,
    foundry_definition_snapshot,
)
from functions_orchestration_result_contracts import (
    ProducerIdentity, ResultContractError, canonical_bytes, identifier,
)
from functions_orchestration_results import ResultUnavailableError


_CAPABILITIES = {
    "web": "web_search", "url": "url_fetch", "deep_research": "deep_research",
    "agent": "agent_invoke", "action": "action_invoke",
}
_MODEL_FIELDS = ("model_deployment", "model_endpoint_id", "model_id", "model_provider")
_PLANNER_FIELDS = {
    "model_deployment": "chat_orchestration_planner_deployment",
    "model_endpoint_id": "chat_orchestration_planner_model_endpoint_id",
    "model_id": "chat_orchestration_planner_model_id",
    "model_provider": "chat_orchestration_planner_model_provider",
}
_CONNECTION_TIMEOUT = 5.0
_READ_TIMEOUT = 10.0
_MAX_ELAPSED = 30.0


def _invalid():
    raise ExternalConfigurationServiceError("external_configuration_metadata_invalid")


def _unsupported():
    raise ResultUnavailableError("external_configuration_metadata_unsupported")


def _mapping(value, *, optional=False):
    if optional and value is None:
        return {}
    if type(value) is not dict:
        _invalid()
    return value


def _text(value, *, optional=False, limit=2048):
    if optional and value in (None, ""):
        return ""
    if type(value) is not str or not value.strip():
        _invalid()
    value = value.strip()
    try:
        identifier(value, limit=limit)
    except ResultContractError:
        _invalid()
    return value


def _metadata_json(value, depth=0):
    if depth > 64:
        _invalid()
    if isinstance(value, dict):
        if type(value) is not dict and get_action_origin(value) is None:
            _invalid()
        return {key: _metadata_json(item, depth + 1) for key, item in value.items()}
    if type(value) is list:
        return [_metadata_json(item, depth + 1) for item in value]
    return value


def _copy_metadata(value):
    try:
        size = len(canonical_bytes(_metadata_json(value)))
    except ResultContractError:
        _invalid()
    if size > MAX_CONFIGURATION_BYTES:
        raise ExternalConfigurationServiceError("external_configuration_limit_exceeded")
    return deepcopy(value)


def _flag(settings, name):
    value = settings.get(name, False)
    if type(value) is not bool:
        _invalid()
    return value


def _envelope(kind, **values):
    return {
        "version": EXTERNAL_ACQUISITION_VERSION, "kind": kind, "phase": "current",
        **values,
    }


def _model_metadata_operation(callback, *args, **kwargs):
    # Model policy is initialized by the application, never by reader construction.
    from functions_ai_connections import AIConnectionError

    try:
        return callback(*args, **kwargs)
    except AIConnectionError as error:
        if error.code == "model_capability_unavailable":
            raise ResultUnavailableError("external_configuration_model_unavailable") from None
        raise


def _sdk_metadata_operation(callback, *args, **kwargs):
    # SDK failures are classified at the metadata I/O boundary, without leaking
    # the provider's response or converting throttled authentication into denial.
    from azure.core.exceptions import ClientAuthenticationError, DecodeError

    try:
        return callback(*args, **kwargs)
    except DecodeError as error:
        raise _http_failure(error.status_code) from None
    except ClientAuthenticationError as error:
        if type(error.status_code) is int and (error.status_code == 429 or 500 <= error.status_code < 600):
            raise _http_failure(error.status_code) from None
        raise


def _require_inline_configuration(value):
    # Legacy hydration helpers can swallow backend failures. Until they expose a
    # typed metadata seam, indirect secrets are outside this bounded reader.
    from functions_keyvault import validate_secret_name_dynamic

    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 64:
            _invalid()
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str and (
            item == "Stored_In_KeyVault" or validate_secret_name_dynamic(item)
        ):
            _unsupported()


class _MetadataRead:
    def __init__(self, user_id, conversation_id, read_conversation, execution_check):
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.read_conversation = read_conversation
        self.execution_check = execution_check
        self.deadline = monotonic() + _MAX_ELAPSED

    def check(self):
        if self.execution_check is not None:
            allowed = self.execution_check()
            if allowed is False:
                raise ExternalConfigurationCancelledError()
            if allowed is not None and allowed is not True:
                raise ResultContractError("external_configuration_check_invalid")
        if monotonic() >= self.deadline:
            raise ExternalConfigurationServiceError("external_configuration_timeout")

    def call(self, callback, *args, **kwargs):
        self.check()
        result = _read_metadata(callback, *args, **kwargs)
        self.check()
        return result

    def own(self, resources, factory, *args, **kwargs):
        self.check()
        resource = _read_metadata(factory, *args, **kwargs)

        def close(_kind, prior, _traceback):
            try:
                _read_metadata(resource.close)
            except (ExternalConfigurationServiceError, ResultUnavailableError) as error:
                if prior is None:
                    raise
                # Cleanup must not replace an active cancellation/lease failure.
                from functions_appinsights import log_event

                log_event(
                    "[ORCHESTRATION_ADAPTERS] External metadata resource cleanup failed.",
                    extra={"error_type": type(error).__name__},
                )
            return False

        resources.push(close)
        self.check()
        return resource

    def authorize(self):
        conversation = self.call(self.read_conversation, self.conversation_id)
        if (
            type(conversation) is not dict or conversation.get("id") != self.conversation_id
            or conversation.get("user_id") != self.user_id
            or conversation.get("orchestration_deleted")
        ):
            raise ResultUnavailableError("external_configuration_conversation_unavailable")


def _run_seeds(read, producer):
    # This initialized store is needed only for saved model selectors. Saved
    # roles, endpoint configuration and prior client/capture data are never used.
    from functions_orchestration_runs import get_orchestration_run

    run = read.call(
        get_orchestration_run, producer.run_id, read.user_id,
        conversation_id=read.conversation_id, strict=True,
    )
    if (
        type(run) is not dict or run.get("id") != producer.run_id
        or run.get("user_id") != read.user_id or run.get("conversation_id") != read.conversation_id
        or type(run.get("attempt_index")) is not int or run["attempt_index"] != producer.attempt_index
        or run.get("checkpoints_deleted")
        or type(run.get("plan")) is not dict
        or type(run["plan"].get("planner_contract_version")) is not int
        or run["plan"]["planner_contract_version"] != 2
    ):
        raise ResultUnavailableError("external_configuration_producer_unavailable")
    seeds = _mapping(run.get("seeds"), optional=True)
    model = _mapping(seeds.get("model"), optional=True)
    return _copy_metadata({
        "model": {name: model[name] for name in _MODEL_FIELDS if name in model},
        **{name: seeds[name] for name in ("reasoning_effort", "active_group_ids") if name in seeds},
    })


def _current_model(read, producer, settings, *, planner):
    # These are metadata/policy resolvers, not any of the runtime client builders.
    from functions_ai_connections import require_model_capability
    from functions_model_endpoint_providers import MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI
    from functions_model_endpoint_runtime import resolve_model_endpoint_from_context
    from functions_model_endpoint_types import (
        get_model_endpoint_api_type, resolve_model_endpoint_request_model,
    )
    from model_endpoint_clients import infer_model_endpoint_protocol

    seeds = _run_seeds(read, producer)
    supplied = _mapping(seeds.get("model"), optional=True)
    selection = {name: _text(supplied.get(name), optional=True) for name in _MODEL_FIELDS}
    reasoning_effort = _text(seeds.get("reasoning_effort"), optional=True, limit=128)
    overrides = {
        name: _text(settings.get(key), optional=True) for name, key in _PLANNER_FIELDS.items()
    } if planner else {}
    overridden = any(overrides.values())
    if overridden:
        selection = overrides
        reasoning_effort = ""
    multi_endpoint = _flag(settings, "enable_multi_model_endpoints")
    if not any(selection.values()) and multi_endpoint:
        default = _mapping(settings.get("default_model_selection"), optional=True)
        selection.update(
            model_endpoint_id=_text(default.get("endpoint_id"), optional=True),
            model_id=_text(default.get("model_id"), optional=True),
            model_provider=_text(default.get("provider"), optional=True),
        )
    if (
        selection["model_id"] and not selection["model_endpoint_id"]
        or selection["model_endpoint_id"] and not (selection["model_id"] or selection["model_deployment"])
        or selection["model_provider"] and not (selection["model_endpoint_id"] or selection["model_deployment"])
    ):
        _unsupported()
    if not planner and multi_endpoint and not selection["model_endpoint_id"]:
        # The action factory can match an unnamed deployment to a different
        # endpoint. This implicit routing is outside the supported capture set.
        _unsupported()
    deployment = selection["model_deployment"]
    endpoint_id = model_id = None
    if selection["model_endpoint_id"]:
        if not multi_endpoint:
            _unsupported()
        groups = seeds.get("active_group_ids") or []
        if type(groups) is not list or len(groups) > 128:
            _invalid()
        groups = [_text(group, limit=128) for group in groups]
        endpoint = read.call(
            _model_metadata_operation, resolve_model_endpoint_from_context, settings, {
                "user_id": read.user_id, "active_group_ids": groups,
                "endpoint_id": selection["model_endpoint_id"], "model_id": selection["model_id"],
                "model_deployment": deployment, "provider": selection["model_provider"],
            }, authorize=True,
        )
        if type(endpoint) is not dict or endpoint.get("enabled", True) is not True:
            _unsupported()
        endpoint_id = _text(endpoint.get("id"), limit=256)
        provider = _text(endpoint.get("provider"), limit=128).lower()
        if endpoint_id != selection["model_endpoint_id"] or provider != "aoai":
            _unsupported()
        if selection["model_provider"] and selection["model_provider"].lower() != provider:
            _unsupported()
        models = endpoint.get("models")
        if type(models) is not list or len(models) > 4096:
            _invalid()
        matches = [
            model for model in models if type(model) is dict and (
                model.get("id") == selection["model_id"] if selection["model_id"] else
                resolve_model_endpoint_request_model(endpoint, model) == deployment
            )
        ]
        if len(matches) != 1 or matches[0].get("enabled", True) is not True:
            _unsupported()
        model = matches[0]
        read.call(_model_metadata_operation, require_model_capability, model, provider=provider)
        actual_deployment = resolve_model_endpoint_request_model(endpoint, model)
        if deployment and deployment != actual_deployment:
            _unsupported()
        deployment = _text(actual_deployment, limit=256)
        model_id = _text(model.get("id"), limit=256)
        connection = _mapping(endpoint.get("connection"))
        address = _text(connection.get("endpoint"), limit=8192)
        api_version = _text(connection.get("openai_api_version") or connection.get("api_version"), limit=128)
        api_type = get_model_endpoint_api_type(endpoint)
    else:
        if _flag(settings, "enable_gpt_apim"):
            _unsupported()
        if selection["model_provider"].lower() not in ("", "aoai"):
            _unsupported()
        provider, api_type = "aoai", ""
        model_settings = _mapping(settings.get("gpt_model"), optional=True)
        models = model_settings.get("selected") or []
        if type(models) is not list or len(models) > 4096 or any(type(model) is not dict for model in models):
            _invalid()
        if not deployment:
            # Do not reproduce implicit "first model" or environment fallbacks.
            _unsupported()
        matches = [model for model in models if model.get("deploymentName") == deployment]
        if len(matches) > 1 or (not matches and not overridden):
            _unsupported()
        model = matches[0] if matches else {}
        if model.get("enabled", True) is not True:
            _unsupported()
        address = _text(settings.get("azure_openai_gpt_endpoint"), limit=8192)
        api_version = _text(settings.get("azure_openai_gpt_api_version"), limit=128)
        read.call(_model_metadata_operation, require_model_capability, model or deployment, provider=provider)
    protocol = infer_model_endpoint_protocol(provider, address, deployment, api_type)
    if protocol != MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI:
        _unsupported()
    if urlsplit(_endpoint(address)).scheme != "https":
        _unsupported()
    parameters = {"parallel_tool_calls": False, "tool_choice": "auto"}
    if planner:
        parameters = {}
        limit = model.get("responseLength")
        if type(limit) is int and limit > 0:
            parameters["response_length"] = limit
        if reasoning_effort:
            parameters["reasoning_effort"] = reasoning_effort
    return {
        "provider": provider, "protocol": protocol, "endpoint": address,
        "api_version": api_version, "deployment": deployment,
        "endpoint_id": endpoint_id or ("" if planner else None),
        "model_id": model_id or ("" if planner else None), "parameters": parameters,
    }


def _foundry_connection(local, settings):
    # Explicit configuration is required; never use an SDK/environment default.
    from foundry_agent_runtime import (
        _authority_from_cloud, _resolve_endpoint, _resolve_foundry_authentication_type,
    )

    endpoint = local.get("endpoint") or settings.get("azure_ai_foundry_endpoint")
    api_version = local.get("api_version") or settings.get("azure_ai_foundry_api_version")
    _text(endpoint, limit=8192)
    api_version = _text(api_version, limit=128)
    endpoint = _resolve_endpoint(local, settings)
    if urlsplit(_endpoint(endpoint)).scheme != "https":
        _unsupported()
    auth = local.get("authentication_type") or local.get("auth_type") or settings.get("azure_ai_foundry_authentication_type")
    if auth not in ("managed_identity", "service_principal"):
        _unsupported()
    if _resolve_foundry_authentication_type(local, settings) != auth:
        _unsupported()
    values = {
        name: local.get(name) or settings.get(f"azure_ai_foundry_{name}")
        for name in (
            "authority", "cloud", "managed_identity_type", "managed_identity_client_id",
            "tenant_id", "client_id", "client_secret",
        )
    }
    values["authority"] = values["authority"] or _authority_from_cloud(values["cloud"])
    return endpoint, api_version, auth, values


def _get_foundry_definition(read, local, settings):
    endpoint, api_version, auth, values = _foundry_connection(local, settings)
    agent_id = _text(local.get("agent_id"), limit=256)
    read.check()
    # Only an authorized classic metadata read constructs these short-lived SDK
    # resources. It cannot create agents, threads, runs or inference clients.
    from azure.ai.agents import AgentsClient
    from azure.core.pipeline.policies import RedirectPolicy
    from azure.identity import ClientSecretCredential, DefaultAzureCredential

    options = {
        "connection_timeout": _CONNECTION_TIMEOUT, "read_timeout": _READ_TIMEOUT,
        "retry_total": 0, "retry_connect": 0, "retry_read": 0, "retry_status": 0,
    }
    with ExitStack() as resources:
        if auth == "service_principal":
            secret = _text(values["client_secret"], limit=8192)
            _require_inline_configuration(secret)
            credential = read.own(
                resources, ClientSecretCredential,
                tenant_id=_text(values["tenant_id"], limit=128),
                client_id=_text(values["client_id"], limit=128), client_secret=secret,
                authority=values["authority"], **options,
            )
        else:
            identity_options = {}
            if values["managed_identity_type"] == "user_assigned":
                identity_options["managed_identity_client_id"] = _text(
                    values["managed_identity_client_id"], limit=128,
                )
            elif values["managed_identity_type"] not in (None, "", "system_assigned"):
                _unsupported()
            credential = read.own(
                resources, DefaultAzureCredential, authority=values["authority"], process_timeout=_CONNECTION_TIMEOUT,
                **identity_options, **options,
            )
        client = read.own(
            resources, AgentsClient, endpoint=endpoint, credential=credential, api_version=api_version,
            redirect_policy=RedirectPolicy(redirect_max=0), **options,
        )
        definition = read.call(
            _sdk_metadata_operation, client.get_agent, agent_id, connection_timeout=_CONNECTION_TIMEOUT,
            read_timeout=_READ_TIMEOUT, retry_total=0,
        )
        snapshot = read.call(foundry_definition_snapshot, definition)
    if snapshot.get("id") != agent_id:
        raise ResultUnavailableError("external_configuration_selection_mismatch")
    return endpoint, api_version, _copy_metadata(snapshot)


def _current_foundry(read, local, settings, *, max_completion_tokens=None):
    # Reuse the owning engine's normalization, not guessed provider defaults.
    from foundry_agent_runtime import _normalize_max_completion_tokens

    local = _copy_metadata(_mapping(local))
    endpoint, api_version, definition = _get_foundry_definition(read, local, settings)
    if (
        type(definition.get("model")) is not str or not definition["model"].strip()
        or type(definition.get("instructions")) is not str or not definition["instructions"].strip()
        or "{{" in definition["instructions"] or definition.get("tool_resources") not in (None, {})
    ):
        _unsupported()
    tools = definition.get("tools")
    if type(tools) is not list or len(tools) > 64:
        _invalid()
    if any(type(tool) is not dict or tool.get("type") != "bing_grounding" for tool in tools):
        _unsupported()
    _pinned_tools(tools)
    for name, upper in (("temperature", 2), ("top_p", 1)):
        value = definition.get(name)
        if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= upper:
            _unsupported()
    response_format = definition.get("response_format")
    if response_format != "auto" and not (
        type(response_format) is dict and response_format.get("type") in ("json_object", "json_schema")
    ):
        _unsupported()
    overrides = {
        key: deepcopy(definition[key])
        for key in ("model", "instructions", "temperature", "top_p", "response_format")
    }
    limit = _normalize_max_completion_tokens(max_completion_tokens)
    if limit is not None:
        overrides["max_completion_tokens"] = limit
    return _envelope(
        "foundry", binding=FOUNDRY_OBSERVED_RUN, endpoint=endpoint, api_version=api_version,
        foundry_settings=local, definition=definition, overrides=overrides,
    )


def _current_web(read, settings):
    web = _mapping(settings.get("web_search_agent"))
    other = _mapping(web.get("other_settings"))
    return _current_foundry(read, other.get("azure_ai_foundry"), settings)


def _current_action(read, producer, settings, source, selector):
    origin = get_action_origin(source)
    if origin is None or not isinstance(source, dict):
        raise ResultUnavailableError("external_configuration_action_origin_required")
    reference = {"id": origin.action_id, "scope_type": origin.scope_type, "scope_id": origin.scope_id}
    if (
        selector != _action_ref(origin.scope_type, origin.scope_id, origin.action_id)
        or any(source.get(key) != value for key, value in reference.items())
        or source.get("action_ref") != selector
    ):
        raise ResultUnavailableError("external_configuration_selection_mismatch")
    current = read.call(resolve_action_manifest, read.user_id, selector, settings=settings)
    if _record_configuration(current) != _record_configuration(source) or get_action_origin(current) != origin:
        raise ResultUnavailableError("external_configuration_changed")
    if resolve_action_type(current).lower() in ("agent", "mcp") or current.get("dependencies"):
        _unsupported()
    from functions_workspace_identities import get_action_identity_reference_id

    if get_action_identity_reference_id(current):
        _unsupported()
    _require_inline_configuration(current)
    model = _current_model(read, producer, settings, planner=False)
    # The normal execution preparation preserves the scoped origin and hydrates
    # the actual manifest; it does not load or invoke its plugin.
    from semantic_kernel_loader import prepare_action_plugin_manifest

    prepared = read.call(prepare_action_plugin_manifest, deepcopy(current), deepcopy(settings))
    if get_action_origin(prepared) != origin:
        raise ResultUnavailableError("external_configuration_action_origin_required")
    return _envelope(
        "action", reference=reference, manifest=deepcopy(current),
        prepared_manifest=_copy_metadata(prepared), model=model,
    )


def _current_agent(read, settings, source, selector):
    if type(source) is not dict:
        raise ResultUnavailableError("external_configuration_source_required")
    reference = agent_reference(source, read.user_id)
    if selector != f"{reference['scope_type']}:{reference['scope_id']}:{reference['id']}":
        raise ResultUnavailableError("external_configuration_selection_mismatch")
    current = read.call(resolve_delegation_agent, reference, user_id=read.user_id, settings=settings)
    if _record_configuration(current) != _record_configuration(source) or agent_reference(current, read.user_id) != reference:
        raise ResultUnavailableError("external_configuration_changed")
    if current.get("agent_type", "local") != "aifoundry" or current.get("actions_to_load"):
        _unsupported()
    # Resolve the full configuration, not a catalog description or display name.
    from functions_assigned_knowledge import build_assigned_knowledge_runtime_filters
    from semantic_kernel_loader import resolve_agent_config

    filters = read.call(build_assigned_knowledge_runtime_filters, current)
    if filters and (filters.get("has_workspace_knowledge") or filters.get("web_sources")):
        _unsupported()
    config = read.call(
        resolve_agent_config, deepcopy(current), deepcopy(settings),
        group_scope_id=reference["scope_id"] if reference["scope_type"] == "group" else None,
        execution_user_id=read.user_id,
    )
    config = _copy_metadata(_mapping(config))
    if config.get("id") != reference["id"] or config.get("agent_type") != "aifoundry":
        raise ResultUnavailableError("external_configuration_selection_mismatch")
    other = _mapping(config.get("other_settings"))
    foundry = _current_foundry(
        read, other.get("azure_ai_foundry"), settings,
        max_completion_tokens=config.get("max_completion_tokens"),
    )
    return _envelope("agent", reference=reference, resolved_config=config, foundry=foundry)


def build_external_metadata_reader(user_id, conversation_id, *, read_conversation, execution_check=None):
    """Build the attestor's fresh, private ``read_current_source`` callback.

    The initialized root supplies live conversation reads and, when executing,
    its cancellation/lease/budget check. Construction performs no resource I/O.
    Agent/action inputs must be the provider's currently authorized exact source.
    """
    identifier(user_id)
    identifier(conversation_id)
    if not callable(read_conversation) or execution_check is not None and not callable(execution_check):
        raise ResultContractError("external_configuration_reader_required")

    def read_current_source(source_type, *, producer, settings, source, selector):
        if (
            type(source_type) is not str or source_type not in _CAPABILITIES
            or type(producer) is not ProducerIdentity or producer.user_id != user_id
            or producer.conversation_id != conversation_id
            or producer.capability_id != _CAPABILITIES[source_type]
        ):
            raise ResultUnavailableError("external_configuration_producer_mismatch")
        if type(settings) is not dict:
            raise ResultContractError("external_configuration_invalid")
        if source_type in ("agent", "action"):
            _text(selector, limit=2048)
        elif source is not None or selector is not None:
            raise ResultContractError("external_configuration_source_invalid")
        read = _MetadataRead(user_id, conversation_id, read_conversation, execution_check)
        read.authorize()
        if source_type == "url":
            value = None
        elif source_type == "web":
            value = _current_web(read, settings)
        elif source_type == "action":
            value = _current_action(read, producer, settings, source, selector)
        elif source_type == "agent":
            value = _current_agent(read, settings, source, selector)
        else:
            model = _current_model(read, producer, settings, planner=True)
            web = _current_web(read, settings) if _flag(settings, "enable_web_search") else None
            value = _envelope("deep_research", model=model, web=web)
        read.authorize()
        return _copy_metadata(value)

    return read_current_source
