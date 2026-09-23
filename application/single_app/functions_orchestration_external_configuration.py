# functions_orchestration_external_configuration.py
"""Opaque invocation-configuration proof and capture-independent current reads.

Version: 0.261.127

The owning engines supply actual acquisition evidence. The application root
supplies current metadata reads; this module discovers no settings or clients,
invokes no model/tool, and never fetches source content.
"""

from dataclasses import dataclass
import math
import re
from threading import Lock
from urllib.parse import urlsplit, urlunsplit

from azure.core.exceptions import AzureError, ClientAuthenticationError, HttpResponseError, ResourceNotFoundError
from requests.exceptions import HTTPError, RequestException, Timeout

from functions_agent_delegation import agent_reference
from functions_action_catalog import _action_ref
from functions_action_manifest import get_action_origin
from functions_orchestration_external_sources import ExternalSourceConfiguration
from functions_orchestration_invocation_capture import (
    OrchestrationInvocationCancelledError, OrchestrationInvocationServiceError,
)
from functions_orchestration_result_contracts import (
    ProducerIdentity, ResultContractError, canonical_bytes, canonical_digest, identifier,
)
from functions_orchestration_results import ResultUnavailableError
from functions_source_review import (
    URL_ACCESS_CONTEXT_CHAT, get_source_review_config, get_url_access_max_urls,
)


EXTERNAL_CONFIGURATION_VERSION = "orchestration-external-configuration-v1"
EXTERNAL_ACQUISITION_VERSION = "orchestration-external-acquisition-v1"
FOUNDRY_OBSERVED_RUN = "observed-run-v1"
FOUNDRY_PINNED_REQUEST = "pinned-request-v1"
MAX_CONFIGURATION_BYTES = 1048576
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE_CAPABILITIES = {
    "web": "web_search", "url": "url_fetch", "deep_research": "deep_research",
    "agent": "agent_invoke", "action": "action_invoke",
}
_FETCH_POLICY_KEYS = (
    "source_review_allow_internal_hosts", "source_review_max_pages_per_turn",
    "source_review_max_seed_pages_per_turn", "source_review_timeout_seconds",
    "source_review_max_redirects", "source_review_max_bytes_per_page",
    "source_review_allow_js_rendering", "source_review_js_load_more_clicks",
    "source_review_respect_robots_txt",
)
_SERVICE_CODES = {
    "external_configuration_service_unavailable": True,
    "external_configuration_timeout": True,
    "external_configuration_throttled": True,
    "external_configuration_metadata_invalid": False,
    "external_configuration_limit_exceeded": False,
}
_RECORD_METADATA = frozenset({
    "_rid", "_self", "_etag", "_attachments", "_ts", "created_at", "updated_at",
    "created_date", "last_updated", "lastUpdated", "last_used", "last_used_at",
    "created_by", "updated_by", "usage_count", "display_name", "group_name", "default_agent",
})
_FOUNDRY_FIELDS = (
    "model", "instructions", "tools", "tool_resources", "response_format", "temperature", "top_p",
)
_RUN_OPTION_FIELDS = frozenset({
    "max_completion_tokens", "max_prompt_tokens", "truncation_strategy", "parallel_tool_calls", "tool_choice",
})
_MODEL_PARAMETER_FIELDS = frozenset({
    "temperature", "top_p", "max_tokens", "max_completion_tokens", "max_prompt_tokens",
    "response_length", "reasoning_effort", "response_format", "parallel_tool_calls",
    "presence_penalty", "frequency_penalty", "seed", "tool_choice",
})


class ExternalConfigurationServiceError(OrchestrationInvocationServiceError):
    """Safe inability to verify metadata, distinct from revoked configuration."""

    def __init__(self, code="external_configuration_service_unavailable"):
        if type(code) is not str or code not in _SERVICE_CODES:
            raise ValueError("Invalid external configuration error code.")
        self.code = code
        self.retryable = _SERVICE_CODES[code]
        super().__init__("Current source configuration could not be verified.")


class ExternalConfigurationCancelledError(OrchestrationInvocationCancelledError):
    """Execution stopped; this is not a source authorization decision."""

    def __init__(self):
        self.code = "external_configuration_cancelled"
        super().__init__("Current source configuration verification was cancelled.")


def _http_failure(status):
    if type(status) is int and status in (401, 403, 404, 410):
        return ResultUnavailableError("external_configuration_unavailable")
    if type(status) is int and status == 429:
        return ExternalConfigurationServiceError("external_configuration_throttled")
    if type(status) is int and 500 <= status < 600:
        return ExternalConfigurationServiceError()
    return ExternalConfigurationServiceError("external_configuration_metadata_invalid")


def _read_metadata(callback, *args, **kwargs):
    try:
        return callback(*args, **kwargs)
    except InterruptedError:
        raise
    except ExternalConfigurationServiceError as error:
        failure = ExternalConfigurationServiceError(error.code)
    except (ResultUnavailableError, ClientAuthenticationError, ResourceNotFoundError, PermissionError):
        failure = ResultUnavailableError("external_configuration_unavailable")
    except HttpResponseError as error:
        failure = _http_failure(error.status_code)
    except HTTPError as error:
        failure = _http_failure(error.response.status_code if error.response is not None else None)
    except (Timeout, TimeoutError):
        failure = ExternalConfigurationServiceError("external_configuration_timeout")
    except (RequestException, AzureError, OSError):
        failure = ExternalConfigurationServiceError()
    except (TypeError, ValueError, LookupError):
        failure = ExternalConfigurationServiceError("external_configuration_metadata_invalid")
    raise failure


def _configuration(source_type, identity, revision, *, private_digest=None, private=False):
    identity_value = {"version": EXTERNAL_CONFIGURATION_VERSION, "source_type": source_type, "identity": identity}
    revision_value = {"identity": identity_value, "configuration": revision}
    for value in (identity_value, revision_value):
        if len(canonical_bytes(value)) > MAX_CONFIGURATION_BYTES:
            raise ExternalConfigurationServiceError("external_configuration_limit_exceeded")
    if private:
        if private_digest is None:
            raise ResultUnavailableError("external_configuration_private_digest_required")
        try:
            revision_digest = private_digest(canonical_bytes(revision_value))
        except (TypeError, ValueError, RuntimeError):
            revision_digest = None
        if type(revision_digest) is not str or _SHA256.fullmatch(revision_digest) is None:
            raise ResultContractError("external_configuration_digest_invalid")
        revision_token = f"hmac-sha256:{revision_digest}"
    else:
        revision_token = f"sha256:{canonical_digest(revision_value)}"
    return ExternalSourceConfiguration(
        f"source:{source_type}:{canonical_digest(identity_value)}",
        revision_token,
    )


def _invalid_metadata():
    raise ExternalConfigurationServiceError("external_configuration_metadata_invalid")


def _text(value, *, optional=False, limit=2048):
    if optional and value in (None, ""):
        return value
    if type(value) is not str:
        _invalid_metadata()
    identifier(value, limit=limit)
    return value


def _endpoint(value):
    _text(value, limit=8192)
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        parsed = None
    if (
        parsed is None or parsed.scheme not in {"http", "https"} or not parsed.hostname
        or parsed.username is not None or parsed.password is not None
        or parsed.query or parsed.fragment or "\\" in value
        or (port is not None and not 1 <= port <= 65535)
    ):
        _invalid_metadata()
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    default_port = 443 if parsed.scheme == "https" else 80
    if port is not None and port != default_port:
        host = f"{host}:{port}"
    return urlunsplit((parsed.scheme, host, parsed.path.rstrip("/"), "", ""))


def _json_object(value):
    if not isinstance(value, dict):
        _invalid_metadata()
    result = dict(value)
    if len(canonical_bytes(result)) > MAX_CONFIGURATION_BYTES:
        raise ExternalConfigurationServiceError("external_configuration_limit_exceeded")
    return result


def _record_configuration(value):
    record = _json_object(value)
    return {key: item for key, item in record.items() if key not in _RECORD_METADATA}


def _envelope(source):
    if (
        type(source) is not dict or source.get("version") != EXTERNAL_ACQUISITION_VERSION
        or source.get("phase") not in ("resolved", "definition", "run", "pinned", "current")
        or source.get("kind") not in ("action", "agent", "foundry", "planner", "deep_research")
    ):
        _invalid_metadata()
    if "dependencies" in source and type(source["dependencies"]) is not list:
        _invalid_metadata()
    if source.get("dependencies"):
        # Arbitrary invoked child sets cannot be reconstructed from the root
        # reference after restart. Do not turn a root proof into child authority.
        raise ResultUnavailableError("external_configuration_dependencies_unsupported")
    return source


def _selector(source_type, selector):
    if source_type in ("agent", "action"):
        _text(selector, limit=2048)
    elif selector is not None:
        raise ResultContractError("external_configuration_source_invalid")


def _reference(source, selector, *, action=False):
    reference = source.get("reference")
    if (
        type(reference) is not dict or set(reference) != {"id", "scope_type", "scope_id"}
        or any(type(value) is not str or not value for value in reference.values())
        or reference["scope_type"] not in {"personal", "group", "global"}
    ):
        _invalid_metadata()
    normalized = agent_reference(reference)
    if normalized != reference:
        _invalid_metadata()
    expected = (
        _action_ref(reference["scope_type"], reference["scope_id"], reference["id"]) if action else
        f"{reference['scope_type']}:{reference['scope_id']}:{reference['id']}"
    )
    if type(selector) is not str or selector != expected:
        raise ResultUnavailableError("external_configuration_selection_mismatch")
    return reference


def _model_configuration(model):
    model = _json_object(model)
    required = {"provider", "protocol", "endpoint", "api_version", "deployment", "endpoint_id", "model_id", "parameters"}
    if not required <= set(model):
        _invalid_metadata()
    parameters = _json_object(model["parameters"])
    if set(parameters) - _MODEL_PARAMETER_FIELDS:
        raise ResultUnavailableError("external_configuration_model_parameters_unsupported")
    return {
        "provider": _text(model["provider"], limit=128),
        "protocol": _text(model["protocol"], limit=128),
        "endpoint": _endpoint(model["endpoint"]),
        "api_version": _text(model["api_version"], optional=True, limit=128),
        "deployment": _text(model["deployment"], limit=256),
        "endpoint_id": _text(model["endpoint_id"], optional=True, limit=256),
        "model_id": _text(model["model_id"], optional=True, limit=256),
        "parameters": parameters,
    }


def _foundry_binding(value):
    if type(value) is not str or value not in (FOUNDRY_OBSERVED_RUN, FOUNDRY_PINNED_REQUEST):
        raise ResultUnavailableError("external_configuration_foundry_binding_unsupported")
    return value


def _pinned_tools(tools):
    for tool in tools:
        if set(tool) != {"type", "bing_grounding"} or tool["type"] != "bing_grounding":
            raise ResultUnavailableError("external_configuration_foundry_unpinned")
        options = tool["bing_grounding"]
        if type(options) is not dict or set(options) != {"search_configurations"}:
            raise ResultUnavailableError("external_configuration_foundry_unpinned")
        searches = options["search_configurations"]
        if type(searches) is not list or not searches or len(searches) > 128:
            raise ResultUnavailableError("external_configuration_foundry_unpinned")
        for search in searches:
            if type(search) is not dict or set(search) - {"connection_id", "market", "set_lang", "count", "freshness"}:
                raise ResultUnavailableError("external_configuration_foundry_unpinned")
            _text(search.get("connection_id"))
            if "count" in search and (type(search["count"]) is not int or search["count"] <= 0):
                _invalid_metadata()
            if any(name in search and type(search[name]) is not str for name in ("market", "set_lang", "freshness")):
                _invalid_metadata()


def _foundry_values(value, *, binding=FOUNDRY_OBSERVED_RUN, definition=False):
    value = _json_object(value)
    pinned = _foundry_binding(binding) == FOUNDRY_PINNED_REQUEST
    names = tuple(name for name in _FOUNDRY_FIELDS if not pinned or name != "tool_resources")
    required = {"model", "tools"} if pinned and definition else set(names)
    if not required <= set(value):
        raise ResultUnavailableError("external_configuration_foundry_snapshot_incomplete")
    fields = {key: value[key] for key in names if key in value}
    _text(fields["model"], limit=256)
    if fields.get("instructions") is not None and type(fields["instructions"]) is not str:
        _invalid_metadata()
    if (
        type(fields["tools"]) is not list or len(fields["tools"]) > 128
        or any(type(tool) is not dict or type(tool.get("type")) is not str for tool in fields["tools"])
        or (value.get("tool_resources") is not None and type(value["tool_resources"]) is not dict)
        or (fields.get("response_format") is not None and type(fields["response_format"]) not in (dict, str))
    ):
        _invalid_metadata()
    for key, maximum in (("temperature", 2), ("top_p", 1)):
        number = fields.get(key)
        if number is not None and (
            type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= maximum
        ):
            _invalid_metadata()
        if number is not None:
            fields[key] = float(number)
    if pinned:
        _pinned_tools(fields["tools"])
        if value.get("tool_resources") not in (None, {}) or not definition and (
            not fields["instructions"] or not fields["tools"] or not fields["response_format"]
            or fields["temperature"] is None or fields["top_p"] is None
        ):
            # Empty/omitted request fields can inherit mutable remote state.
            # Only fully specified Bing tools without assistant resources qualify.
            raise ResultUnavailableError("external_configuration_foundry_unpinned")
    return fields


def foundry_definition_snapshot(definition, *, binding=FOUNDRY_OBSERVED_RUN):
    """Normalize a real SDK definition without filling absent response fields."""
    # SDK model types are needed only at this explicit engine/metadata boundary.
    from azure.ai.agents.models import Agent

    if not isinstance(definition, Agent):
        raise ResultUnavailableError("external_configuration_foundry_snapshot_required")
    raw = definition.as_dict()
    if "id" not in raw:
        raise ResultUnavailableError("external_configuration_foundry_snapshot_incomplete")
    return {"id": _text(raw["id"], limit=256), **_foundry_values(raw, binding=binding, definition=True)}


def foundry_run_snapshot(run):
    """Use the actual SDK run configuration, not generated message metadata."""
    # SDK model types are needed only at this explicit engine/metadata boundary.
    from azure.ai.agents.models import ThreadRun

    if not isinstance(run, ThreadRun):
        raise ResultUnavailableError("external_configuration_foundry_snapshot_required")
    raw = run.as_dict()
    if not {"id", "thread_id", "assistant_id"} <= set(raw):
        raise ResultUnavailableError("external_configuration_foundry_snapshot_incomplete")
    value = {
        "id": _text(raw["id"], limit=256), "thread_id": _text(raw["thread_id"], limit=256),
        "agent_id": _text(raw["assistant_id"], limit=256), **_foundry_values(raw),
    }
    value.update({key: raw[key] for key in _RUN_OPTION_FIELDS if key in raw})
    return value


def _foundry_application_settings(settings, local):
    values = {"agent_id": _text(local.get("agent_id"), limit=256)}
    for key in (
        "endpoint", "api_version", "authentication_type", "managed_identity_type",
        "managed_identity_client_id", "authority", "cloud", "tenant_id",
        "client_id", "client_secret", "foundry_scope",
    ):
        global_key = "azure_ai_foundry_scope" if key == "foundry_scope" else f"azure_ai_foundry_{key}"
        override = local.get("auth_type") if key == "authentication_type" else None
        values[key] = local.get(key) or override or settings.get(global_key)
    for key in ("project_name", "include_document_context"):
        values[key] = local.get(key)
    return values


def _web_settings(settings):
    agent = settings.get("web_search_agent")
    if type(agent) is not dict or type(agent.get("other_settings")) is not dict:
        raise ResultUnavailableError("external_configuration_web_source_required")
    local = agent["other_settings"].get("azure_ai_foundry")
    if type(local) is not dict:
        raise ResultUnavailableError("external_configuration_web_source_required")
    return _foundry_application_settings(settings, local)


def _foundry_projection(source, settings, *, require_run=False):
    source = _envelope(source)
    if source["kind"] != "foundry":
        _invalid_metadata()
    binding = _foundry_binding(source.get("binding", FOUNDRY_OBSERVED_RUN))
    pinned = binding == FOUNDRY_PINNED_REQUEST
    if source["phase"] not in (("definition", "pinned", "current") if pinned else ("definition", "run", "current")):
        raise ResultUnavailableError("external_configuration_invocation_proof_required")
    definition = _json_object(source.get("definition"))
    local = _json_object(source.get("foundry_settings"))
    agent_id = _text(local.get("agent_id"), limit=256)
    if definition.get("id") != agent_id:
        raise ResultUnavailableError("external_configuration_selection_mismatch")
    values = _foundry_values(definition, binding=binding, definition=True)
    overrides = _json_object(source.get("overrides"))
    supported = set(_FOUNDRY_FIELDS) | _RUN_OPTION_FIELDS | {"instructions_override", "additional_instructions"}
    if set(overrides) - supported or overrides.get("additional_instructions") not in (None, ""):
        raise ResultUnavailableError("external_configuration_foundry_overrides_unsupported")
    effective = dict(values)
    for key in _FOUNDRY_FIELDS:
        if pinned and key == "tool_resources":
            continue
        if key in overrides and overrides[key] is not None:
            effective[key] = overrides[key]
    if overrides.get("instructions_override") is not None:
        effective["instructions"] = overrides["instructions_override"]
    effective = _foundry_values(effective, binding=binding)
    if pinned and "tool_resources" in overrides:
        raise ResultUnavailableError("external_configuration_foundry_unpinned")
    if require_run and pinned:
        if source["phase"] != "pinned":
            raise ResultUnavailableError("external_configuration_foundry_pinned_request_required")
        request = _json_object(source.get("request"))
        if set(request) - (set(_FOUNDRY_FIELDS) | _RUN_OPTION_FIELDS | {"agent_id"}):
            raise ResultUnavailableError("external_configuration_foundry_overrides_unsupported")
        if (
            request.get("agent_id") != agent_id
            or canonical_bytes(_foundry_values(request, binding=binding)) != canonical_bytes(effective)
        ):
            raise ResultUnavailableError("external_configuration_foundry_request_changed")
        request_options = {key: request[key] for key in _RUN_OPTION_FIELDS if key in request}
        expected_options = {key: overrides[key] for key in _RUN_OPTION_FIELDS if key in overrides}
        if canonical_bytes(request_options) != canonical_bytes(expected_options):
            raise ResultUnavailableError("external_configuration_foundry_request_changed")
    elif require_run:
        if source["phase"] != "run":
            raise ResultUnavailableError("external_configuration_foundry_run_required")
        run = _json_object(source.get("run"))
        _text(run.get("id"), limit=256)
        _text(run.get("thread_id"), limit=256)
        if run.get("agent_id") != agent_id or canonical_bytes(_foundry_values(run)) != canonical_bytes(effective):
            raise ResultUnavailableError("external_configuration_foundry_run_changed")
        for key in _RUN_OPTION_FIELDS:
            if key in overrides and (key not in run or canonical_bytes(run[key]) != canonical_bytes(overrides[key])):
                raise ResultUnavailableError("external_configuration_foundry_run_changed")
    application = _foundry_application_settings(settings, local)
    observed_endpoint = _endpoint(source.get("endpoint"))
    configured_endpoint = application.get("endpoint")
    if configured_endpoint:
        configured_endpoint = _endpoint(configured_endpoint)
        project_name = local.get("project_name")
        if project_name and "/api/projects/" not in configured_endpoint:
            configured_endpoint = f"{configured_endpoint}/api/projects/{_text(project_name, limit=256)}"
        if observed_endpoint != configured_endpoint:
            raise ResultUnavailableError("external_configuration_selection_mismatch")
    observed_api_version = _text(source.get("api_version"), optional=True, limit=128)
    if application.get("api_version") and observed_api_version != application["api_version"]:
        raise ResultUnavailableError("external_configuration_selection_mismatch")
    identity = {
        "provider": "foundry-agent",
        "endpoint": observed_endpoint,
        "api_version": observed_api_version,
        "agent_id": agent_id,
    }
    if pinned:
        identity["binding"] = binding
    revision = {
        "foundry_settings": _record_configuration(local),
        "application_settings": application,
        "definition": values, "overrides": overrides,
    }
    return identity, revision


def _action_projection(source, selector):
    reference = _reference(source, selector, action=True)
    manifest = source.get("manifest")
    origin = get_action_origin(manifest)
    if origin is None or (
        origin.action_id, origin.scope_type, origin.scope_id
    ) != (reference["id"], reference["scope_type"], reference["scope_id"]):
        raise ResultUnavailableError("external_configuration_action_origin_required")
    if manifest.get("id") != reference["id"] or manifest.get("action_ref") != selector:
        raise ResultUnavailableError("external_configuration_selection_mismatch")
    prepared = _record_configuration(source.get("prepared_manifest"))
    if prepared.get("id") != reference["id"] or prepared.get("action_ref") != selector:
        raise ResultUnavailableError("external_configuration_selection_mismatch")
    return {"reference": reference}, {
        "manifest": _record_configuration(manifest),
        "prepared_manifest": prepared,
        "model": _model_configuration(source.get("model")),
    }


def _agent_projection(source, settings, selector, *, require_run=False):
    reference = _reference(source, selector)
    config = _record_configuration(source.get("resolved_config"))
    if config.get("id") != reference["id"]:
        raise ResultUnavailableError("external_configuration_selection_mismatch")
    kind = config.get("agent_type")
    revision = {"resolved_config": config}
    if kind == "local":
        plugins = source.get("prepared_plugins")
        if type(plugins) is not list or len(plugins) > 64:
            _invalid_metadata()
        revision.update(
            model=_model_configuration(source.get("model")),
            prepared_plugins=[_record_configuration(plugin) for plugin in plugins],
        )
    elif kind == "aifoundry":
        identity, foundry = _foundry_projection(source.get("foundry"), settings, require_run=require_run)
        revision.update(foundry_identity=identity, foundry_configuration=foundry)
    else:
        raise ResultUnavailableError("external_configuration_agent_runtime_unsupported")
    return {"reference": reference}, revision


def _fetch_policy(settings, *, direct):
    effective = get_source_review_config(settings)
    policy = {key: effective[key] for key in _FETCH_POLICY_KEYS}
    for key in ("url_access_allowed_domains", "url_access_blocked_domains"):
        policy[key] = sorted({value.casefold() for value in effective[key]})
    if direct:
        limit = get_url_access_max_urls(URL_ACCESS_CONTEXT_CHAT, settings)
        policy["url_access_max_chat_urls_per_turn"] = limit
        policy["source_review_max_seed_pages_per_turn"] = min(
            policy["source_review_max_seed_pages_per_turn"], limit,
        )
    else:
        for key in (
            "enable_deep_source_review", "source_review_max_depth", "source_review_enable_llm_planning",
            "deep_research_max_user_urls_per_turn", "deep_research_max_search_queries_per_turn",
            "deep_research_enable_query_planning", "url_access_max_chat_urls_per_turn",
        ):
            policy[key] = effective[key]
    return policy


def is_research_acquisition_profile_supported(settings):
    """Return whether normalized research settings avoid unattested planner calls."""
    if type(settings) is not dict:
        raise ResultContractError("external_configuration_invalid")
    web_enabled = settings.get("enable_web_search", False)
    if type(web_enabled) is not bool:
        _invalid_metadata()
    effective = get_source_review_config(settings)
    return not (
        web_enabled
        and effective["deep_research_max_search_queries_per_turn"] > 1
        and effective["deep_research_enable_query_planning"]
        or effective["enable_deep_source_review"]
        and effective["source_review_enable_llm_planning"]
    )


def _components(source_type, *, settings, source, selector, private_digest, require_run=False):
    source = _envelope(source)
    if source_type == "web":
        expected = _web_settings(settings)
        identity, revision = _foundry_projection(source, settings, require_run=require_run)
        if revision["application_settings"] != expected:
            raise ResultUnavailableError("external_configuration_selection_mismatch")
        return {"foundry": _configuration("web", identity, revision, private_digest=private_digest, private=True)}
    if source_type == "action":
        if source["kind"] != "action":
            _invalid_metadata()
        identity, revision = _action_projection(source, selector)
        return {"action": _configuration("action", identity, revision, private_digest=private_digest, private=True)}
    if source_type == "agent":
        if source["kind"] != "agent":
            _invalid_metadata()
        config = source.get("resolved_config")
        if type(config) is not dict:
            _invalid_metadata()
        if config.get("agent_type") == "aifoundry":
            reference = _reference(source, selector)
            if config.get("id") != reference["id"]:
                raise ResultUnavailableError("external_configuration_selection_mismatch")
            identity, revision = _foundry_projection(source.get("foundry"), settings, require_run=require_run)
            return {
                "agent": _configuration(
                    "agent", {"reference": reference}, {"resolved_config": _record_configuration(config)},
                    private_digest=private_digest, private=True,
                ),
                "foundry": _configuration(
                    "agent-foundry", identity, revision, private_digest=private_digest, private=True,
                ),
            }
        identity, revision = _agent_projection(source, settings, selector, require_run=require_run)
        return {"agent": _configuration("agent", identity, revision, private_digest=private_digest, private=True)}
    if source_type == "deep_research":
        if source["kind"] != "deep_research" or selector is not None:
            _invalid_metadata()
        web_enabled = settings.get("enable_web_search", False)
        if type(web_enabled) is not bool:
            _invalid_metadata()
        model = _model_configuration(source.get("model"))
        components = {
            "policy": _configuration(
                "deep_research", {"implementation": "simplechat-source-review-v1"},
                {**_fetch_policy(settings, direct=False), "web_enabled": web_enabled},
            ),
            "planner": _configuration(
                "deep_research", {"model": {key: value for key, value in model.items() if key != "parameters"}},
                model, private_digest=private_digest, private=True,
            ),
        }
        if web_enabled:
            web_source = source.get("web")
            components.update({
                "web": _components(
                    "web", settings=settings, source=web_source, selector=None,
                    private_digest=private_digest, require_run=require_run,
                )["foundry"],
            })
        elif source.get("web") is not None:
            raise ResultUnavailableError("external_configuration_selection_mismatch")
        return components
    raise ResultUnavailableError("external_configuration_proof_unsupported")


def _combine(source_type, components):
    return _configuration(
        source_type, {name: value.identity for name, value in sorted(components.items())},
        {name: value.revision for name, value in sorted(components.items())},
    )


def project_external_configuration(
    source_type, *, settings, source=None, selector=None, private_digest=None,
):
    """Project execution-relevant fields only, never an entire settings document."""
    if type(source_type) is not str or source_type not in _SOURCE_CAPABILITIES or type(settings) is not dict:
        raise ResultContractError("external_configuration_invalid")
    if source_type == "url":
        if source is not None or selector is not None:
            raise ResultContractError("external_configuration_source_invalid")
        return _configuration(
            source_type, {"implementation": "simplechat-url-access-chat-v1"},
            _fetch_policy(settings, direct=True),
        )
    if source_type not in ("agent", "action") and selector is not None:
        raise ResultContractError("external_configuration_source_invalid")
    return _combine(source_type, _components(
        source_type, settings=settings, source=source, selector=selector,
        private_digest=private_digest,
    ))


@dataclass(frozen=True)
class _Capture:
    source_type: str
    selector: str | None
    configuration: ExternalSourceConfiguration | None
    seed: ExternalSourceConfiguration | None = None
    components: tuple = ()
    completed: tuple = ()
    required: tuple = ()


class OrchestrationExternalConfigurationAttestor:
    """Actor-bound private capture map plus independent current metadata reads.

    read_current_source(source_type, *, producer, settings, source, selector)
    must return actual current metadata, not a saved capture or a model/tool
    result. The owning callback supplies bounded metadata-only I/O. URL policy
    needs no metadata callback. Permission/capability/scope checks stay in the
    external-source provider. private_digest(canonical_bytes) returns a lowercase
    SHA-256 HMAC hex digest using an owner-supplied stable backend key. It is
    required for non-URL configurations; no key is discovered or persisted here.
    """

    def __init__(
        self, *, user_id, conversation_id, read_current_source=None,
        execution_check=None, max_captures=64, private_digest=None,
    ):
        identifier(user_id)
        identifier(conversation_id)
        if type(max_captures) is not int or not 1 <= max_captures <= 64:
            raise ResultContractError("external_configuration_limit_invalid")
        if any(callback is not None and not callable(callback) for callback in (
            read_current_source, execution_check, private_digest,
        )):
            raise ResultContractError("external_configuration_reader_required")
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.read_current_source = read_current_source
        self.execution_check = execution_check
        self.private_digest = private_digest
        self.max_captures = max_captures
        self._captures = {}
        self._conflicts = set()
        self._lock = Lock()

    def _check(self, source_type, producer):
        if (
            type(source_type) is not str or source_type not in _SOURCE_CAPABILITIES
            or type(producer) is not ProducerIdentity or producer.user_id != self.user_id
            or producer.conversation_id != self.conversation_id
            or producer.capability_id != _SOURCE_CAPABILITIES[source_type]
        ):
            raise ResultUnavailableError("external_configuration_producer_mismatch")
        if self.execution_check is not None:
            allowed = self.execution_check()
            if allowed is False:
                raise ExternalConfigurationCancelledError()
            if allowed is not None and allowed is not True:
                raise ResultContractError("external_configuration_check_invalid")

    @staticmethod
    def _current_selector(source_type, producer, source):
        if source_type == "agent":
            if type(source) is not dict:
                raise ResultUnavailableError("external_configuration_source_required")
            reference = agent_reference(source, producer.user_id)
            return f"{reference['scope_type']}:{reference['scope_id']}:{reference['id']}"
        if source_type == "action":
            if not isinstance(source, dict) or type(source.get("action_ref")) is not str:
                raise ResultUnavailableError("external_configuration_source_required")
            return source["action_ref"]
        return None

    def capture(self, source_type, *, producer, settings, source=None, selector=None):
        """Capture only engine-supplied configuration at its actual acquisition boundary."""
        self._check(source_type, producer)
        if type(settings) is not dict:
            raise ResultContractError("external_configuration_invalid")
        try:
            _selector(source_type, selector)
            seed = self._seed(source_type, settings)
            parts, completed, required, invalidate = self._capture_parts(
                source_type, settings, source, selector,
            )
        except (ResultContractError, ResultUnavailableError, ExternalConfigurationServiceError):
            with self._lock:
                if producer in self._captures:
                    self._conflicts.add(producer)
            raise
        with self._lock:
            previous = self._captures.get(producer)
            known = dict(previous.components) if previous is not None else {}
            changed = previous is not None and (
                previous.source_type != source_type or previous.selector != selector
                or previous.seed != seed or (required and previous.required != tuple(sorted(required)))
                or any(name in known and known[name] != value for name, value in parts.items())
            )
            if producer in self._conflicts or changed:
                self._conflicts.add(producer)
                raise ResultUnavailableError("external_configuration_invocation_changed")
            if previous is None and len(self._captures) >= self.max_captures:
                raise ExternalConfigurationServiceError("external_configuration_limit_exceeded")
            if not required:
                if previous is None:
                    raise ResultUnavailableError("external_configuration_root_capture_required")
                required = set(previous.required)
            known.update(parts)
            ready = set(previous.completed) if previous is not None else set()
            ready.difference_update(invalidate)
            ready.update(completed)
            configuration = None
            if required <= ready and required <= known.keys():
                configuration = known["url"] if source_type == "url" else _combine(
                    source_type, {name: known[name] for name in required},
                )
                if previous is not None and previous.configuration == configuration:
                    configuration = previous.configuration
            self._captures[producer] = _Capture(
                source_type, selector, configuration, seed,
                tuple(sorted(known.items())), tuple(sorted(ready)), tuple(sorted(required)),
            )
        self._check(source_type, producer)

    def _capture_parts(self, source_type, settings, source, selector):
        if source_type == "url":
            value = project_external_configuration("url", settings=settings, source=source, selector=selector)
            return {"url": value}, {"url"}, {"url"}, set()
        if source_type == "web" and source is None:
            return {}, set(), {"foundry"}, {"foundry"}
        if source_type == "deep_research":
            enabled = settings.get("enable_web_search", False)
            required = {"policy", "planner"} | ({"web"} if enabled else set())
            policy = _configuration(
                "deep_research", {"implementation": "simplechat-source-review-v1"},
                {**_fetch_policy(settings, direct=False), "web_enabled": enabled},
            )
            if source is None:
                return {"policy": policy}, {"policy"}, required, required - {"policy"}
        source = _envelope(source)
        if source["phase"] == "current":
            raise ResultUnavailableError("external_configuration_invocation_proof_required")
        if source_type == "deep_research" and source["kind"] == "planner":
            if source["phase"] != "resolved":
                raise ResultUnavailableError("external_configuration_planner_construction_required")
            model = _model_configuration(source.get("model"))
            planner = _configuration(
                "deep_research", {"model": {key: value for key, value in model.items() if key != "parameters"}},
                model, private_digest=self.private_digest, private=True,
            )
            return {"policy": policy, "planner": planner}, {"policy", "planner"}, required, set()
        if source["kind"] == "foundry" and source_type in ("web", "agent", "deep_research"):
            verified = source["phase"] in ("run", "pinned")
            if source["phase"] not in ("definition", "run", "pinned"):
                raise ResultUnavailableError("external_configuration_foundry_run_required")
            identity, revision = _foundry_projection(source, settings, require_run=verified)
            if source_type in ("web", "deep_research") and revision["application_settings"] != _web_settings(settings):
                raise ResultUnavailableError("external_configuration_selection_mismatch")
            if source_type == "deep_research" and not settings.get("enable_web_search", False):
                raise ResultUnavailableError("external_configuration_selection_mismatch")
            name = "web" if source_type == "deep_research" else "foundry"
            component_type = "agent-foundry" if source_type == "agent" else "web"
            value = _configuration(component_type, identity, revision, private_digest=self.private_digest, private=True)
            required = {"foundry"} if source_type == "web" else (required if source_type == "deep_research" else set())
            return {name: value}, {name} if verified else set(), required, set() if verified else {name}
        if source_type == "agent" and source["kind"] == "agent":
            config = source.get("resolved_config")
            if type(config) is not dict:
                _invalid_metadata()
            if config.get("agent_type") == "aifoundry" and source.get("foundry") is None:
                if source["phase"] != "resolved":
                    raise ResultUnavailableError("external_configuration_invocation_proof_required")
                reference = _reference(source, selector)
                if config.get("id") != reference["id"]:
                    raise ResultUnavailableError("external_configuration_selection_mismatch")
                value = _configuration(
                    "agent", {"reference": reference}, {"resolved_config": _record_configuration(config)},
                    private_digest=self.private_digest, private=True,
                )
                return {"agent": value}, {"agent"}, {"agent", "foundry"}, {"foundry"}
        if source["phase"] != "resolved":
            raise ResultUnavailableError("external_configuration_invocation_proof_required")
        parts = _components(
            source_type, settings=settings, source=source, selector=selector,
            private_digest=self.private_digest, require_run=True,
        )
        return parts, set(parts), set(parts), set()

    def _seed(self, source_type, settings):
        if source_type == "web":
            values = _web_settings(settings)
        elif source_type == "deep_research":
            enabled = settings.get("enable_web_search", False)
            if type(enabled) is not bool:
                _invalid_metadata()
            values = {"policy": _fetch_policy(settings, direct=False), "web_enabled": enabled}
            if enabled:
                values["web"] = _web_settings(settings)
        else:
            return None
        return _configuration(
            source_type, {"preparation": True}, values,
            private_digest=self.private_digest, private=True,
        )

    def _current_components(self, source_type, *, producer, settings, source=None):
        self._check(source_type, producer)
        if type(settings) is not dict:
            raise ResultContractError("external_configuration_invalid")
        selector = self._current_selector(source_type, producer, source)
        if source_type != "url":
            if self.read_current_source is None:
                raise ResultUnavailableError("external_configuration_reader_required")
            source = _read_metadata(
                self.read_current_source, source_type, producer=producer,
                settings=settings, source=source, selector=selector,
            )
            if type(source) is not dict:
                raise ExternalConfigurationServiceError("external_configuration_metadata_invalid")
            if _envelope(source)["phase"] != "current":
                raise ExternalConfigurationServiceError("external_configuration_metadata_invalid")
            for name in ("web", "foundry"):
                if source.get(name) is not None and _envelope(source[name])["phase"] != "current":
                    raise ExternalConfigurationServiceError("external_configuration_metadata_invalid")
            if {"run", "request"}.intersection(source) or any(
                isinstance(source.get(name), dict) and {"run", "request"}.intersection(source[name])
                for name in ("web", "foundry")
            ):
                raise ExternalConfigurationServiceError("external_configuration_metadata_invalid")
        if source_type == "url":
            parts = {"url": project_external_configuration(
                source_type, settings=settings, source=source, selector=selector,
            )}
        else:
            parts = _components(
                source_type, settings=settings, source=source, selector=selector,
                private_digest=self.private_digest,
            )
        self._check(source_type, producer)
        return selector, parts

    def current(self, source_type, *, producer, settings, source=None):
        """Reconstruct current configuration without consulting live invocation captures."""
        _, parts = self._current_components(source_type, producer=producer, settings=settings, source=source)
        return parts["url"] if source_type == "url" else _combine(source_type, parts)

    def validate_acquisition(
        self, source_type, *, producer, settings, current_settings,
        source=None, selector=None, current_source=None,
    ):
        """Validate supported current metadata against actual pre-effect evidence.

        Partial definition/planner/agent events compare their existing component
        projections without pretending a run happened. This check creates no
        captures; current authority always comes from the independent reader.
        """
        self._check(source_type, producer)
        if type(settings) is not dict or type(current_settings) is not dict:
            raise ResultContractError("external_configuration_invalid")
        _selector(source_type, selector)
        if source_type == "deep_research" and (
            not is_research_acquisition_profile_supported(current_settings)
            or not is_research_acquisition_profile_supported(settings)
        ):
            raise ResultUnavailableError("external_configuration_research_profile_unsupported")
        current_selector, current_parts = self._current_components(
            source_type, producer=producer, settings=current_settings, source=current_source,
        )
        if current_selector != selector:
            raise ResultUnavailableError("external_configuration_selection_mismatch")
        seed = self._seed(source_type, settings)
        if seed != self._seed(source_type, current_settings):
            raise ResultUnavailableError("external_configuration_changed")
        if source is None and source_type in ("agent", "action"):
            actual_parts = {}
        else:
            actual_parts, _, _, _ = self._capture_parts(source_type, settings, source, selector)
        if any(current_parts.get(name) != value for name, value in actual_parts.items()):
            raise ResultUnavailableError("external_configuration_changed")
        with self._lock:
            captured = self._captures.get(producer)
            if producer in self._conflicts or captured is not None and (
                captured.source_type != source_type or captured.selector != selector
                or captured.seed != seed
                or any(current_parts.get(name) != value for name, value in captured.components)
            ):
                if captured is not None:
                    self._conflicts.add(producer)
                raise ResultUnavailableError("external_configuration_invocation_changed")
        self._check(source_type, producer)

    def _captured(self, producer):
        with self._lock:
            if producer in self._conflicts:
                raise ResultUnavailableError("external_configuration_invocation_changed")
            captured = self._captures.get(producer)
            if captured is None or captured.configuration is None:
                raise ResultUnavailableError("external_configuration_capture_required")
            return captured

    def selector_for(self, producer):
        """Return the original selector only when a trusted capture exists."""
        if type(producer) is not ProducerIdentity:
            raise ResultUnavailableError("external_configuration_producer_mismatch")
        captured = self._captured(producer)
        self._check(captured.source_type, producer)
        return captured.selector

    def for_admission(self, source_type, *, producer, settings, source=None, selector=None):
        """Return the captured configuration, refusing replacement by later configuration."""
        self._check(source_type, producer)
        captured = self._captured(producer)
        if captured.source_type != source_type or captured.selector != selector:
            raise ResultUnavailableError("external_configuration_selection_mismatch")
        current = self.current(source_type, producer=producer, settings=settings, source=source)
        if current != captured.configuration or self._captured(producer) != captured:
            raise ResultUnavailableError("external_configuration_changed")
        return captured.configuration
