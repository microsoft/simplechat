# functions_model_endpoint_urls.py
"""Pure endpoint URL contracts; route resolution performs no I/O.

Schema-v2 routes use one explicit, validated segment-composition path for both
preview and runtime dispatch. Legacy base normalization remains available for
existing records, native providers, and callers that predate schema-v2.
"""

import hashlib
import json
import re
from copy import deepcopy
from typing import Any
from urllib.parse import quote, unquote, urlencode, urlparse, urlsplit, urlunsplit

from functions_model_endpoint_providers import (
    CUSTOM_ENDPOINT_URL_MODE_API_BASE,
    CUSTOM_ENDPOINT_URL_MODE_AUTO,
    CUSTOM_ENDPOINT_URL_MODE_EXACT,
    CUSTOM_ENDPOINT_URL_MODE_FULL,
    MODEL_ENDPOINT_INFERENCE_API_CHAT_COMPLETIONS,
    MODEL_ENDPOINT_INFERENCE_API_MESSAGES,
    MODEL_ENDPOINT_INFERENCE_API_RESPONSES,
    MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
    URL_POLICY_AS_GIVEN,
    get_model_endpoint_provider,
    normalize_api_type_value,
    normalize_custom_endpoint_url_mode,
)
from functions_model_capabilities import resolve_model_capabilities
from functions_model_endpoint_types import routing_schema_version
from model_endpoint_profiles import (
    GENAI_MIL_CAPABILITIES,
    GENAI_MIL_PROFILE,
    get_custom_endpoint_profile,
)


VERSION_SEGMENT = re.compile(r"v\d+(?:[a-z][a-z0-9]*)?", re.IGNORECASE)
PATH_SEGMENT = re.compile(r"[A-Za-z0-9._~-]+")
APIM_REVISION_SEGMENT = re.compile(r"[A-Za-z0-9._~-]+;rev=[1-9][0-9]*")
DECODED_SEGMENT = re.compile(r"[A-Za-z0-9._~ -]+")
VERSION_VALUE = re.compile(r"[A-Za-z0-9._-]{1,64}")
DEFERRED_FIELDS = frozenset({
    "request_template", "url_template", "body_template", "response_template",
    "custom_call", "custom_calls", "response_id", "previous_response_id",
})
OPERATIONS = (("chat", "completions"), ("messages",), ("responses",), ("models",),
              ("embeddings",), ("images", "generations"), ("images", "edits"))
CUSTOM_OPENAI_OPERATION_SUFFIXES = (
    "/chat/completions", "/responses", "/models",
    "/images/generations", "/images/edits", "/embeddings",
)
CUSTOM_OPENAI_VERSION_SEGMENT_PATTERN = re.compile(
    r"^v\d+(?:[a-z][a-z0-9]*)?$", re.IGNORECASE
)
ROUTING_PATH_ORDER_MODEL_FIRST = "model_first"
ROUTING_PATH_ORDER_CONNECTION_FIRST = "connection_first"


def _validation_error(message: str):
    # The validation layer imports the pure routing helpers, so defer this
    # exception-class lookup until a helper is actually executed.
    from functions_model_endpoint_validation import ModelEndpointValidationError

    return ModelEndpointValidationError(message)


def normalize_endpoint_text(endpoint: Any) -> str:
    """Return a trimmed endpoint URL without a trailing slash."""
    return str(endpoint or "").strip().rstrip("/")


def get_endpoint_path(endpoint) -> str:
    """Return the legacy lower-case parsed path."""
    endpoint_value = normalize_endpoint_text(endpoint)
    if not endpoint_value:
        return ""
    try:
        return urlparse(endpoint_value).path.lower()
    except ValueError:
        return endpoint_value.lower()


def get_endpoint_origin(endpoint) -> str:
    endpoint_value = normalize_endpoint_text(endpoint)
    parsed = urlparse(endpoint_value)
    if not parsed.scheme or not parsed.netloc:
        return endpoint_value
    return f"{parsed.scheme}://{parsed.netloc}"


def is_anthropic_model(deployment_name) -> bool:
    return "claude" in str(deployment_name or "").strip().lower()


def endpoint_uses_openai_style_protocol(endpoint) -> bool:
    endpoint_value = normalize_endpoint_text(endpoint).lower()
    path = get_endpoint_path(endpoint_value)
    return "/openai/v1" in path or "/api/projects/" in path or "services.ai.azure.com" in endpoint_value


def infer_model_endpoint_protocol(provider, endpoint, deployment_name="", api_type="") -> str:
    """Retain legacy inference for consumers that have not opted into schema v2."""
    profile = str(provider or "aoai").strip().lower()
    if profile == "custom":
        descriptor = get_model_endpoint_provider(api_type)
        if descriptor is None:
            raise ValueError("Custom model endpoints require a supported API type.")
        return descriptor.protocol
    if profile in ("anthropic", "claude"):
        return "anthropic"
    if "/anthropic/" in get_endpoint_path(endpoint) or is_anthropic_model(deployment_name):
        return "anthropic"
    if profile in ("aifoundry", "new_foundry") and endpoint_uses_openai_style_protocol(endpoint):
        return "openai_style"
    return "azure_openai"


def normalize_openai_style_base_url(raw_endpoint) -> str:
    """Preserve the legacy Foundry URL reader for non-opted-in consumers."""
    endpoint = normalize_endpoint_text(raw_endpoint)
    if not endpoint:
        raise ValueError("A Foundry endpoint is required for OpenAI-compatible inference.")
    lowered = endpoint.lower()
    for suffix in CUSTOM_OPENAI_OPERATION_SUFFIXES:
        position = lowered.find(suffix)
        if position >= 0:
            endpoint = endpoint[:position]
            lowered = endpoint.lower()
            break
    position = lowered.find("/openai/v1")
    if position >= 0:
        return endpoint[:position + len("/openai/v1")].rstrip("/") + "/"
    position = lowered.find("/openai")
    if position >= 0:
        return endpoint[:position].rstrip("/") + "/openai/v1/"
    return endpoint.rstrip("/") + "/openai/v1/"


def _endpoint_path_names_a_version(endpoint: str) -> bool:
    try:
        path = urlparse(endpoint).path
    except ValueError:
        return False
    segments = [segment for segment in path.split("/") if segment]
    return bool(segments and VERSION_SEGMENT.fullmatch(segments[-1]))


def normalize_custom_openai_base_url(raw_endpoint) -> str:
    """Retain legacy terminal version/operation normalization."""
    endpoint = normalize_endpoint_text(raw_endpoint)
    if not endpoint:
        raise ValueError("A Custom endpoint is required for OpenAI-compatible inference.")
    for suffix in CUSTOM_OPENAI_OPERATION_SUFFIXES:
        if endpoint.lower().endswith(suffix):
            return endpoint[:-len(suffix)].rstrip("/") + "/"
    if _endpoint_path_names_a_version(endpoint):
        return endpoint.rstrip("/") + "/"
    return endpoint.rstrip("/") + "/v1/"


def resolve_custom_openai_base_url(raw_endpoint, api_type="", url_mode="") -> str:
    """Retain the legacy Custom API-base entry point and its default behavior."""
    descriptor = get_model_endpoint_provider(api_type or "openai")
    if descriptor is None or descriptor.protocol != MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE:
        raise _validation_error(
            "This Custom API type does not use an OpenAI-compatible base URL."
        )
    normalized_mode = normalize_custom_endpoint_url_mode(url_mode)
    if normalized_mode in (
        CUSTOM_ENDPOINT_URL_MODE_EXACT,
        CUSTOM_ENDPOINT_URL_MODE_API_BASE,
        CUSTOM_ENDPOINT_URL_MODE_FULL,
    ) or descriptor.url_policy == URL_POLICY_AS_GIVEN:
        endpoint = normalize_endpoint_text(raw_endpoint)
        if not endpoint:
            raise _validation_error(
                "A Custom endpoint is required for OpenAI-compatible inference."
            )
        return endpoint.rstrip("/") + "/"
    return normalize_custom_openai_base_url(raw_endpoint)


def normalize_anthropic_messages_url(
    raw_endpoint, *, direct_custom=False, url_mode=CUSTOM_ENDPOINT_URL_MODE_AUTO
) -> str:
    """Retain legacy operation URLs; new routing uses the explicit resolver."""
    endpoint = normalize_endpoint_text(raw_endpoint)
    if not endpoint:
        raise ValueError("An endpoint is required for Anthropic inference.")
    lowered = endpoint.lower()
    if direct_custom:
        mode = normalize_custom_endpoint_url_mode(url_mode)
        if mode == CUSTOM_ENDPOINT_URL_MODE_FULL or lowered.endswith("/v1/messages"):
            return endpoint
        if lowered.endswith("/v1"):
            return endpoint.rstrip("/") + "/messages"
        if lowered.endswith("/messages"):
            return endpoint
        return endpoint.rstrip("/") + "/v1/messages"
    position = lowered.find("/anthropic/v1/messages")
    if position >= 0:
        return endpoint[:position + len("/anthropic/v1/messages")]
    position = lowered.find("/anthropic/v1")
    if position >= 0:
        return endpoint[:position + len("/anthropic/v1")].rstrip("/") + "/messages"
    return get_endpoint_origin(endpoint).rstrip("/") + "/anthropic/v1/messages"
def _text(value, label: str, *, required: bool = False, limit: int = 2048) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or len(value) > limit or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"Invalid {label}.")
    text = value.strip()
    if required and not text:
        raise ValueError(f"{label} is required.")
    return text


def normalize_model_api_path(value) -> str:
    """Normalize one surrounding slash; reject ambiguous or unsafe segments."""
    path = _text(value, "model API path")
    if path.startswith("//") or path.endswith("//"):
        raise ValueError("Model API path has empty segments.")
    path = path.removeprefix("/").removesuffix("/")
    if not path:
        return ""
    normalized = []
    for segment in path.split("/"):
        if re.search(r"%(?![0-9A-Fa-f]{2})", segment):
            raise ValueError("Invalid model API path escape.")
        if APIM_REVISION_SEGMENT.fullmatch(segment):
            normalized.append(segment)
            continue
        decoded = unquote(segment, errors="strict")
        if decoded in (".", "..") or not DECODED_SEGMENT.fullmatch(decoded):
            raise ValueError("Model API path contains an unsupported segment.")
        if "%" not in segment and not PATH_SEGMENT.fullmatch(segment):
            raise ValueError("Model API path contains an unsupported segment.")
        normalized.append(quote(decoded, safe="-._~"))
    return "/".join(normalized)


def _base_parts(value):
    text = _text(value, "endpoint URL", required=True)
    if "\\" in text or any(char.isspace() for char in text) or "?" in text or "#" in text:
        raise ValueError("Invalid endpoint URL.")
    try:
        parsed = urlsplit(text)
        port = parsed.port
        hostname = parsed.hostname
    except ValueError as exc:
        raise ValueError("Invalid endpoint URL.") from exc
    if parsed.scheme not in ("https", "http") or not hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("Endpoint URL must have an HTTP(S) origin without credentials.")
    if "%" in parsed.netloc or not re.fullmatch(r"[A-Za-z0-9.\-:\[\]]+", parsed.netloc) or port == 0:
        raise ValueError("Invalid endpoint origin.")
    path = normalize_model_api_path(parsed.path)
    return parsed, path.split("/") if path else []


def _ends_with(segments, suffix) -> bool:
    return len(segments) >= len(suffix) and tuple(segments[-len(suffix):]) == tuple(suffix)


def _identifier(model: dict, descriptor) -> str:
    field = "modelName" if descriptor.uses_model_name else "deploymentName"
    value = _text(model.get(field), field, required=True, limit=256)
    if not descriptor.uses_model_name and (value in (".", "..") or not DECODED_SEGMENT.fullmatch(value)):
        raise ValueError("Deployment name must be a single safe path segment.")
    return value


def _version(endpoint, model, api_type, descriptor) -> str:
    field = descriptor.version_field
    if not field:
        return ""
    value = model.get(field)
    if value is None and (endpoint.get("api_type") == api_type or endpoint.get("provider") != "custom"):
        connection = endpoint.get("connection") or {}
        value = connection.get(field)
        if field == "api_version" and value is None:
            value = connection.get("openai_api_version")
    if value is None:
        value = descriptor.default_version
    version = _text(value, "protocol version", required=True, limit=64)
    if not VERSION_VALUE.fullmatch(version):
        raise ValueError("Invalid protocol version.")
    return version


def _credential_policy(endpoint, descriptor) -> dict:
    auth = endpoint.get("auth") or {}
    if not isinstance(auth, dict):
        raise ValueError("Invalid endpoint authentication policy.")
    auth_type = auth.get("type", "api_key" if endpoint.get("provider") == "custom" else "managed_identity")
    if auth_type in ("bearer", "oauth2_client_credentials", "managed_identity", "service_principal"):
        return {"type": auth_type, "header": "Authorization", "prefix": "Bearer"}
    if auth_type not in ("key", "api_key"):
        raise ValueError("Unsupported endpoint authentication policy.")
    header = auth.get("api_key_header") or descriptor.default_api_key_header
    prefix = auth.get("api_key_prefix", "" if auth.get("api_key_header") else descriptor.default_api_key_prefix)
    header = _text(header, "credential header", required=True, limit=128)
    prefix = _text(prefix, "credential prefix", limit=128)
    if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", header) or header.lower() in {"host", "content-length", "transfer-encoding", "connection", "cookie", "set-cookie"}:
        raise ValueError("Unsupported credential header.")
    return {"type": "api_key", "header": header, "prefix": prefix}


def _resolve_inference_api(endpoint: dict, model: dict, descriptor) -> str:
    value = model.get("inference_api")
    if value is None:
        if "use_responses_api" in model:
            value = (
                MODEL_ENDPOINT_INFERENCE_API_RESPONSES
                if model.get("use_responses_api") is True
                else MODEL_ENDPOINT_INFERENCE_API_CHAT_COMPLETIONS
            )
        else:
            connection = endpoint.get("connection") or {}
            if isinstance(connection.get("use_responses_api"), bool):
                value = (
                    MODEL_ENDPOINT_INFERENCE_API_RESPONSES
                    if connection["use_responses_api"]
                    else MODEL_ENDPOINT_INFERENCE_API_CHAT_COMPLETIONS
                )
            elif str((connection.get("endpoint") or "")).rstrip("/").endswith("/responses"):
                value = MODEL_ENDPOINT_INFERENCE_API_RESPONSES
            else:
                value = descriptor.default_inference_api
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized not in descriptor.supported_inference_apis:
        raise ValueError(
            f"The selected model API does not support {normalized or 'the requested'} inference operation."
        )
    return normalized


def _resolve_url_mode(endpoint: dict, model: dict) -> str:
    value = model.get("url_mode")
    if "url_mode" not in model:
        value = (endpoint.get("connection") or {}).get("url_mode")
    elif value in (None, ""):
        raise ValueError("Model URL handling is required for explicit routing.")
    value = str(value or CUSTOM_ENDPOINT_URL_MODE_AUTO).strip().lower()
    if value == CUSTOM_ENDPOINT_URL_MODE_EXACT:
        return CUSTOM_ENDPOINT_URL_MODE_API_BASE
    if value not in (
        CUSTOM_ENDPOINT_URL_MODE_AUTO,
        CUSTOM_ENDPOINT_URL_MODE_API_BASE,
        CUSTOM_ENDPOINT_URL_MODE_FULL,
    ):
        raise ValueError(
            "Model URL handling must be automatic, API base, or full request URL."
        )
    return value


def _resolve_path_order(endpoint: dict, model: dict) -> str:
    value = (
        model.get("api_path_order")
        or endpoint.get("routing_path_order")
        or ROUTING_PATH_ORDER_MODEL_FIRST
    )
    if value not in (
        ROUTING_PATH_ORDER_MODEL_FIRST,
        ROUTING_PATH_ORDER_CONNECTION_FIRST,
    ):
        raise ValueError("Unsupported model API path order.")
    return value


def _operation_segments(inference_api: str) -> tuple[str, ...]:
    return {
        MODEL_ENDPOINT_INFERENCE_API_MESSAGES: ("messages",),
        MODEL_ENDPOINT_INFERENCE_API_RESPONSES: ("responses",),
        MODEL_ENDPOINT_INFERENCE_API_CHAT_COMPLETIONS: ("chat", "completions"),
    }[inference_api]


def resolve_model_endpoint_route(endpoint: dict, model: dict) -> dict:
    """Resolve an explicit saved model without fetching secrets or opening sockets.

The caller must authorize the saved record and validate the resulting API base
against outbound policy. This function is not permission to execute a request.
"""
    if not isinstance(endpoint, dict) or not isinstance(model, dict):
        raise ValueError("Invalid endpoint or model record.")
    if routing_schema_version(endpoint) != 2:
        raise ValueError("Explicit routing requires schema v2.")
    for record in (endpoint, model, endpoint.get("connection") or {}):
        if not isinstance(record, dict) or DEFERRED_FIELDS.intersection(record):
            raise ValueError("Unsupported model routing configuration.")
    profile = _text(endpoint.get("provider", "aoai"), "endpoint provider", required=True).lower()
    if profile not in ("custom", "aoai", "aifoundry", "new_foundry", "anthropic", "claude"):
        raise ValueError("Unsupported endpoint provider.")
    model = dict(model)
    if (
        profile == "custom"
        and (
            not isinstance(model.get("api_type"), str)
            or not model["api_type"].strip()
        )
    ):
        raise ValueError("Model API type is required for explicit routing.")
    api_type = normalize_api_type_value(
        model.get("api_type") or endpoint.get("api_type")
    )
    custom_profile = get_custom_endpoint_profile(endpoint)
    if custom_profile == GENAI_MIL_PROFILE and api_type != "openai":
        raise ValueError("GenAI.mil supports OpenAI-compatible Chat Completions only.")
    if profile != "custom":
        legacy_identifier = model.get("deploymentName") or model.get("deployment") or model.get("modelName") or model.get("name") or ""
        protocol = infer_model_endpoint_protocol(profile, (endpoint.get("connection") or {}).get("endpoint"), legacy_identifier)
        api_type = api_type or {"azure_openai": "azure_openai", "openai_style": "azure_openai_v1", "anthropic": "anthropic"}[protocol]
        descriptor = get_model_endpoint_provider(api_type)
        if descriptor is None or descriptor.protocol != protocol:
            raise ValueError("Non-Custom model routing must preserve the provider protocol.")
        model.setdefault("modelName" if descriptor.uses_model_name else "deploymentName", legacy_identifier)
        model.setdefault("url_mode", "auto")
    model["api_type"] = api_type
    descriptor = get_model_endpoint_provider(api_type)
    if descriptor is None:
        raise ValueError("Model API type is required and must be supported.")
    inference_api = _resolve_inference_api(endpoint, model, descriptor)
    if (
        custom_profile == GENAI_MIL_PROFILE
        and inference_api != MODEL_ENDPOINT_INFERENCE_API_CHAT_COMPLETIONS
    ):
        raise ValueError("GenAI.mil supports Chat Completions only.")
    mode = _resolve_url_mode(endpoint, model)
    path_order = _resolve_path_order(endpoint, model)
    parsed, endpoint_segments = _base_parts((endpoint.get("connection") or {}).get("endpoint"))
    api_path = normalize_model_api_path(model.get("api_path", ""))
    api_path_segments = api_path.split("/") if api_path else []
    native_foundry_messages = (
        profile in ("aifoundry", "new_foundry")
        and api_type == "anthropic"
        and mode == CUSTOM_ENDPOINT_URL_MODE_AUTO
    )
    if native_foundry_messages:
        endpoint_segments = []
    segments = (
        api_path_segments + endpoint_segments
        if path_order == ROUTING_PATH_ORDER_MODEL_FIRST
        else endpoint_segments + api_path_segments
    )
    if native_foundry_messages and (
        not segments or segments[-1] != "anthropic"
    ):
        segments.append("anthropic")
    if sum(bool(APIM_REVISION_SEGMENT.fullmatch(segment)) for segment in segments) > 1:
        raise ValueError("Schema-v2 URLs may contain only one APIM revision selector.")
    operation_segments = _operation_segments(inference_api)
    if mode != CUSTOM_ENDPOINT_URL_MODE_FULL and any(
        _ends_with(segments, operation) for operation in OPERATIONS
    ):
        raise ValueError("Schema-v2 URLs must name an API base, not an operation.")
    request_model = _identifier(model, descriptor)
    version = _version(endpoint, model, api_type, descriptor)
    if mode == CUSTOM_ENDPOINT_URL_MODE_FULL:
        if not _ends_with(segments, operation_segments):
            raise ValueError(
                "Full request URL mode must include the selected operation path."
            )
        operation_segments_in_url = operation_segments
    elif api_type == "azure_openai":
        encoded = quote(request_model, safe="-._~")
        deployment_base = len(segments) >= 3 and segments[-3:-1] == ["openai", "deployments"]
        deployment_positions = [index for index in range(len(segments)) if segments[index:index + 2] == ["openai", "deployments"]]
        if deployment_positions and deployment_positions != [len(segments) - 3]:
            raise ValueError("Deployment API bases must contain one terminal deployment route.")
        if _ends_with(segments, ("openai", "v1")):
            raise ValueError("Deployment APIs cannot use an OpenAI v1 base.")
        if deployment_base:
            if segments[-1] != encoded:
                raise ValueError("The API base names a different deployment.")
        elif mode == CUSTOM_ENDPOINT_URL_MODE_API_BASE:
            raise ValueError(
                "API-base mode for deployment APIs must name the selected deployment."
            )
        elif _ends_with(segments, ("openai",)):
            segments += ["deployments", encoded]
        else:
            if "deployments" in segments[-2:]:
                raise ValueError("Incomplete deployment API base.")
            segments += ["openai", "deployments", encoded]
    elif api_type == "azure_openai_v1":
        if any(segments[index:index + 2] == ["openai", "deployments"] for index in range(len(segments))):
            raise ValueError("Chat Completions v1 cannot use a deployment API base.")
        if (
            mode == CUSTOM_ENDPOINT_URL_MODE_AUTO
            and not _ends_with(segments, ("openai", "v1"))
        ):
            segments += ["v1"] if _ends_with(segments, ("openai",)) else ["openai", "v1"]
    elif (
        mode == CUSTOM_ENDPOINT_URL_MODE_AUTO
        and descriptor.url_policy != URL_POLICY_AS_GIVEN
    ):
        if not segments or not VERSION_SEGMENT.fullmatch(segments[-1]):
            segments += ["v1"]
    if mode == CUSTOM_ENDPOINT_URL_MODE_FULL:
        base_segments = segments[:-len(operation_segments_in_url)]
        base = urlunsplit(
            (parsed.scheme, parsed.netloc, "/" + "/".join(base_segments), "", "")
        ).rstrip("/") + "/"
        operation_url = urlunsplit(
            (parsed.scheme, parsed.netloc, "/" + "/".join(segments), "", "")
        )
    else:
        base = urlunsplit(
            (parsed.scheme, parsed.netloc, "/" + "/".join(segments), "", "")
        ).rstrip("/") + "/"
        operation_url = base + "/".join(operation_segments)
    if api_type == "azure_openai":
        operation_url += "?" + urlencode({"api-version": version})
    if len(operation_url) > 2048:
        raise ValueError("Resolved endpoint URL is too long.")
    return {
        "routing_schema_version": 2,
        "endpoint_id": _text(endpoint.get("id"), "endpoint ID", required=True, limit=256),
        "model_id": _text(model.get("id"), "model ID", required=True, limit=256),
        "profile": profile, "api_type": api_type, "protocol": descriptor.protocol,
        **({"custom_profile": custom_profile} if custom_profile else {}),
        "request_model": request_model, "api_path": api_path, "url_mode": mode,
        "api_path_order": path_order, "inference_api": inference_api,
        "api_base": base, "operation_url": operation_url,
        "api_version": version if api_type == "azure_openai" else "",
        "anthropic_version": version if api_type == "anthropic" else "",
        "credential_policy": _credential_policy(endpoint, descriptor),
        "capabilities": dict(GENAI_MIL_CAPABILITIES) if custom_profile == GENAI_MIL_PROFILE else resolve_model_capabilities(model, endpoint, use_model_routing=True),
    }


def model_endpoint_route_cache_key(route: dict, *, scope_type: str, scope_id: str, configuration_revision: str) -> str:
    """Bind a secret-free route identity to scope and an authoritative revision."""
    if scope_type not in ("global", "user", "group"):
        raise ValueError("Invalid model endpoint scope.")
    identity = {
        "scope_type": scope_type,
        "scope_id": _text(scope_id, "scope ID", required=True, limit=256),
        "revision": _text(configuration_revision, "configuration revision", required=True, limit=256),
        "route": route,
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def build_model_endpoint_routing_context(*, endpoint_id, model_id, scope_type, scope_id) -> dict:
    """Persist only stable selection identity, never a trusted URL or credential."""
    if scope_type not in ("global", "user", "group"):
        raise ValueError("Invalid model endpoint scope.")
    return {
        "routing_schema_version": 2,
        "scope_type": scope_type,
        "scope_id": _text(scope_id, "scope ID", required=True, limit=256),
        "endpoint_id": _text(endpoint_id, "endpoint ID", required=True, limit=256),
        "model_id": _text(model_id, "model ID", required=True, limit=256),
    }


def normalize_model_endpoint_routing(endpoint: dict) -> dict:
    """Copy and normalize explicit routing without pruning other models' fields."""
    normalized = deepcopy(endpoint)
    if routing_schema_version(normalized) != 2:
        return normalized
    models = normalized.get("models")
    if not isinstance(models, list) or not models:
        raise _validation_error("Add at least one model to the connection.")
    seen_ids = set()
    for model in models:
        if not isinstance(model, dict) or any(field in model for field in ("auth", "api_key", "bearer_token", "headers")):
            raise _validation_error("Each model must be an object. Configure credentials on the connection, not the model.")
        try:
            route = resolve_model_endpoint_route(normalized, model)
        except ValueError as exc:
            raise _validation_error(
                "Invalid model routing. Check API Type, API Path, URL Handling, model identifier, and version."
            ) from exc
        if route["model_id"] in seen_ids:
            raise _validation_error("Model IDs must be unique within a connection.")
        seen_ids.add(route["model_id"])
        for field in ("api_type", "api_path", "url_mode", "inference_api"):
            model[field] = route[field]
        descriptor = get_model_endpoint_provider(route["api_type"])
        field = "modelName" if descriptor.uses_model_name else "deploymentName"
        model[field] = route["request_model"]
        if descriptor.version_field:
            model[descriptor.version_field] = route[descriptor.version_field]
    return normalized


def resolve_model_inference_endpoint(
    endpoint, *, use_responses_api=None, provider="aoai", api_type="", url_mode="", model=None,
):
    """Resolve the selected model's native operation without changing the saved connection."""
    from functions_model_endpoint_validation import (
        model_endpoint_inference_api,
        resolve_native_foundry_chat_api,
    )

    endpoint = normalize_endpoint_text(endpoint)
    selected_api = model_endpoint_inference_api(
        endpoint, use_responses_api, provider=provider, model=model,
    )
    native_api = resolve_native_foundry_chat_api(provider, endpoint, model)
    if native_api is not None:
        parsed = urlparse(endpoint)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if native_api == "mai":
            return f"{origin}/mai/v1"
        if native_api == "anthropic":
            return f"{origin}/anthropic/v1/messages"
        project = re.match(r"^(/api/projects/[^/]+)(?:/|$)", parsed.path, re.IGNORECASE)
        project_path = project.group(1) if project else ""
        endpoint = f"{origin}{project_path}/openai/v1"
    normalized_url_mode = normalize_custom_endpoint_url_mode(url_mode)
    if normalized_url_mode == CUSTOM_ENDPOINT_URL_MODE_FULL:
        return endpoint
    if selected_api != MODEL_ENDPOINT_INFERENCE_API_RESPONSES:
        return endpoint
    if not endpoint:
        raise _validation_error("A model inference endpoint URL is required.")
    parsed = urlparse(endpoint)
    if parsed.scheme not in ("https", "http") or not parsed.netloc or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise _validation_error("Use an HTTP(S) inference API base without credentials, query parameters, or a fragment.")
    if endpoint.lower().endswith("/responses"):
        return endpoint
    if str(provider).lower() == "custom":
        return resolve_custom_openai_base_url(endpoint, api_type, url_mode) + "responses"
    if endpoint.lower().endswith("/chat/completions"):
        endpoint = endpoint[:-len("/chat/completions")]
    path = parsed.path.rstrip("/")
    if not path:
        endpoint += "/openai/v1"
    elif path.lower().endswith("/openai"):
        endpoint += "/v1"
    return endpoint.rstrip("/") + "/responses"


def resolve_custom_azure_openai_base_url(raw_endpoint: Any, deployment_name: Any, url_mode: Any = "") -> str:
    """Build the dated deployment API base, retaining gateway prefixes."""
    endpoint = normalize_endpoint_text(raw_endpoint)
    deployment = str(deployment_name or "").strip()
    if not endpoint or not deployment:
        raise _validation_error("Custom Azure OpenAI requires an endpoint and deployment name.")
    if normalize_custom_endpoint_url_mode(url_mode) in (
        CUSTOM_ENDPOINT_URL_MODE_EXACT,
        CUSTOM_ENDPOINT_URL_MODE_API_BASE,
        CUSTOM_ENDPOINT_URL_MODE_FULL,
    ):
        return endpoint + "/"
    for suffix in CUSTOM_OPENAI_OPERATION_SUFFIXES:
        if endpoint.lower().endswith(suffix):
            endpoint = endpoint[:-len(suffix)].rstrip("/")
            break
    deployment_index = endpoint.lower().find("/openai/deployments/")
    if deployment_index >= 0:
        endpoint = endpoint[:deployment_index]
    elif endpoint.lower().endswith("/openai"):
        endpoint = endpoint[:-len("/openai")]
    return f"{endpoint}/openai/deployments/{quote(deployment, safe='')}/"
