# functions_embedding_profile.py
"""Pure embedding binding, transport and vector-space identity contracts."""

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit, urlunsplit

from functions_ai_connections import (
    AIConnectionError,
    EMBEDDINGS_CAPABILITY,
    ModelBinding,
    embedding_settings_use_connections,
    resolve_capability_binding,
)
from functions_embedding_policy import (
    get_legacy_embedding_context_tokens,
    normalize_embedding_config,
    resolve_embedding_policy,
)


EMBEDDING_VECTOR_PROFILE_KEY = "embedding_vector_profile"
EMBEDDING_PROFILE_FIELD = "embedding_profile_id"
EMBEDDING_VECTOR_FIELDS = ("embedding", "video_ocr_embedding")
EMBEDDING_SEARCH_INDEXES = (
    "simplechat-user-index", "simplechat-group-index", "simplechat-public-index",
)
EMBEDDING_OPERATION_FIELDS = {"api", "endpoint", "api_version", "is_apim", "auth_header"}


@dataclass(frozen=True)
class EmbeddingProfile:
    binding: ModelBinding = field(repr=False)
    policy: dict
    profile_id: str
    dimensions: int
    deployment: str
    api: str
    base_url: str = field(repr=False)
    api_version: str
    legacy: bool = False

    def as_state(self):
        return {"id": self.profile_id, "dimensions": self.dimensions, "legacy": self.legacy}


def normalize_embedding_operation(value):
    if not isinstance(value, dict) or set(value) - EMBEDDING_OPERATION_FIELDS:
        raise AIConnectionError("Embedding operation settings contain unsupported fields.")
    result = dict(value)
    for key in ("api", "endpoint", "api_version", "auth_header"):
        if key in result:
            if not isinstance(result[key], str):
                raise AIConnectionError(f"The embedding {key} must be text.")
            result[key] = result[key].strip()
    if result.get("api") not in (None, "", "azure_openai", "openai"):
        raise AIConnectionError("Choose Azure OpenAI or OpenAI-compatible embedding inference.")
    if "is_apim" in result and not isinstance(result["is_apim"], bool):
        raise AIConnectionError("The embedding gateway setting must be true or false.")
    if result.get("auth_header") not in (
        None, "", "api-key", "authorization", "Ocp-Apim-Subscription-Key",
    ):
        raise AIConnectionError("The embedding authentication header is unsupported.")
    return result


def _validated_endpoint(value, *, custom=False):
    if not isinstance(value, str) or not value.strip():
        raise AIConnectionError("Configure an embedding inference endpoint.")
    try:
        parsed = urlsplit(value.strip())
        if (
            parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
        ):
            raise ValueError
        if custom and parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError
        _ = parsed.port
    except ValueError as exc:
        raise AIConnectionError(
            "Use a valid embedding API base URL without credentials, query, or fragment; custom remote endpoints require HTTPS."
        ) from exc
    if "/api/projects/" in parsed.path.lower():
        raise AIConnectionError(
            "Foundry project endpoints do not route embeddings. Configure the embedding inference endpoint.",
            "embedding_inference_endpoint_required",
        )
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))


def embedding_transport(binding):
    operation = normalize_embedding_operation(binding.operation_settings)
    connection = binding.endpoint.get("connection") or {}
    provider = str(binding.endpoint.get("provider") or "aoai").strip().lower()
    endpoint = _validated_endpoint(
        operation.get("endpoint") or connection.get("endpoint"),
        custom=provider == "openai_compatible",
    )
    api = operation.get("api") or (
        "openai" if provider != "aoai" or urlsplit(endpoint).path.lower().endswith("/openai/v1")
        else "azure_openai"
    )
    if provider == "openai_compatible" and api != "openai":
        raise AIConnectionError("Custom connections require the OpenAI-compatible embeddings API.")
    deployment = str(
        binding.model.get("deploymentName") or binding.model.get("deployment") or ""
    ).strip()
    if not deployment:
        raise AIConnectionError("The embedding model must name a deployment.")
    if api == "azure_openai":
        version = operation.get("api_version") or "2024-05-01-preview"
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:-preview)?", version):
            raise AIConnectionError("The Azure embedding API version must be a dated version.")
        # Preserve the legacy Azure SDK's endpoint-relative deployment routing.
        base_url = f"{endpoint}/openai/deployments/{quote(deployment, safe='')}/"
    else:
        version = operation.get("api_version") or ""
        if version not in ("", "v1"):
            raise AIConnectionError("OpenAI-compatible embedding inference does not use a dated API version.")
        if provider != "openai_compatible" and not urlsplit(endpoint).path.lower().endswith("/openai/v1"):
            raise AIConnectionError(
                "Supply the Azure resource's embedding API base URL ending in /openai/v1/.",
                "embedding_inference_endpoint_required",
            )
        base_url = f"{endpoint}/"
    return api, base_url, version, deployment


def legacy_embedding_context_override(settings):
    """The old chunk budget used selected-model metadata even when APIM was active."""
    catalog = settings.get("embedding_model") or {}
    selected = catalog.get("selected") or [] if isinstance(catalog, dict) else []
    if not isinstance(selected, list):
        raise AIConnectionError("The legacy embedding model selection is invalid.")
    for model in selected:
        try:
            config = model.get("embedding_config") if isinstance(model, dict) else None
            if isinstance(config, dict) and "max_input_tokens" in config:
                return normalize_embedding_config({
                    "max_input_tokens": config["max_input_tokens"],
                })["max_input_tokens"]
            limit = get_legacy_embedding_context_tokens(model)
        except ValueError as exc:
            raise AIConnectionError(str(exc), "embedding_policy_invalid") from exc
        if limit is not None:
            return limit
    return None


def legacy_embedding_binding(settings):
    """Represent legacy configuration without changing its transport or publication."""
    apim = bool(settings.get("enable_embedding_apim"))
    prefix = "azure_apim_embedding" if apim else "azure_openai_embedding"
    catalog = settings.get("embedding_model") or {}
    selected = catalog.get("selected") or [] if isinstance(catalog, dict) else []
    if apim:
        model = {"deploymentName": str(settings.get("azure_apim_embedding_deployment") or "").strip()}
        context_limit = legacy_embedding_context_override(settings)
        if context_limit is not None:
            model["context_window"] = context_limit
    else:
        model = copy.deepcopy(selected[0]) if selected and isinstance(selected[0], dict) else {}
    if not settings.get(f"{prefix}_endpoint") or not model.get("deploymentName"):
        raise AIConnectionError("No embedding model is configured.", "model_configuration_unavailable")
    model.update(supportsEmbeddings=True, enabled_capabilities=[EMBEDDINGS_CAPABILITY])
    auth_type = "api_key" if apim else settings.get("azure_openai_embedding_authentication_type") or "key"
    auth = {
        "type": "api_key" if auth_type == "key" else auth_type,
        "api_key": settings.get("azure_apim_embedding_subscription_key" if apim else "azure_openai_embedding_key"),
    }
    endpoint = {
        "id": f"legacy-embedding-{'apim' if apim else 'direct'}",
        "provider": "aoai",
        "migration_source": f"legacy_embedding_{'apim' if apim else 'direct'}",
        "connection": {
            "endpoint": settings[f"{prefix}_endpoint"],
            "operation_settings": {EMBEDDINGS_CAPABILITY: {
                "api": "azure_openai",
                "api_version": settings.get(f"{prefix}_api_version") or "2024-05-01-preview",
                "is_apim": apim,
                "auth_header": "api-key",
            }},
        },
        "auth": auth,
        "identity_header": {"mode": "disabled"},
    }
    return ModelBinding(
        EMBEDDINGS_CAPABILITY,
        {"endpoint_id": endpoint["id"], "model_id": model["deploymentName"], "provider": "aoai"},
        endpoint, model,
    )


def resolve_embedding_profile(settings, binding=None):
    shared = embedding_settings_use_connections(settings)
    binding = binding or (
        resolve_capability_binding(settings, EMBEDDINGS_CAPABILITY)
        if shared else legacy_embedding_binding(settings)
    )
    provider = str(binding.endpoint.get("provider") or "aoai").strip().lower()
    if binding.capability != EMBEDDINGS_CAPABILITY or provider not in (
        "aoai", "aifoundry", "new_foundry", "openai_compatible",
    ):
        raise AIConnectionError("This connection has no supported embedding adapter.", "embedding_api_unsupported")
    if binding.endpoint.get("enabled") is False or binding.model.get("enabled") is False:
        raise AIConnectionError("The embedding connection or model is disabled.", "model_configuration_unavailable")
    legacy = str(binding.endpoint.get("migration_source") or "").startswith("legacy_embedding_")
    try:
        policy = resolve_embedding_policy(binding.model, legacy=legacy)
    except ValueError as exc:
        raise AIConnectionError(str(exc), "embedding_policy_invalid") from exc
    if policy.get("api") == "unsupported":
        raise AIConnectionError(
            "This embedding model requires an unsupported operation. Configure a verified OpenAI-compatible deployment.",
            "embedding_api_unsupported",
        )
    api, base_url, version, deployment = embedding_transport(binding)
    identity = {
        "endpoint": base_url,
        "api": api,
        "api_version": version if api == "azure_openai" else "",
        "deployment": deployment,
        "model": binding.model.get("modelName") or deployment,
        "revision": policy.get("model_revision") or binding.model.get("modelVersion") or "",
        "dimensions": policy["dimensions"],
        "document_prefix": policy.get("document_prefix") or "",
        "query_prefix": policy.get("query_prefix") or "",
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if shared:
        baseline = settings.get(EMBEDDING_VECTOR_PROFILE_KEY) or {}
        retained_legacy = baseline.get("legacy") is True and baseline.get("id") == digest
        if retained_legacy != legacy:
            try:
                policy = resolve_embedding_policy(binding.model, legacy=retained_legacy)
            except ValueError as exc:
                raise AIConnectionError(str(exc), "embedding_policy_invalid") from exc
        legacy = retained_legacy
    return EmbeddingProfile(
        binding, policy, digest, policy["dimensions"], deployment, api, base_url, version, legacy,
    )


def effective_embedding_profile_id(settings):
    return resolve_embedding_profile(settings).profile_id
