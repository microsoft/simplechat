# functions_ai_connections.py
"""Capability-aware projections and bindings over the shared connection registry.

This module deliberately has no Flask, settings-store, Azure, or SDK imports.
Technical support, publication policy, and an operation's client factory are
separate: accepting image input does not establish image generation support.
"""

import copy
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from functions_embedding_policy import (
    EmbeddingPolicyError,
    normalize_embedding_config,
    resolve_embedding_policy,
)
from functions_model_capabilities import (
    get_model_catalog_capabilities,
    resolve_model_vision_support,
)


CHAT_CAPABILITY = "chat"
IMAGE_GENERATION_CAPABILITY = "image_generation"
EMBEDDINGS_CAPABILITY = "embeddings"
IMAGE_SELECTION_KEY = "image_generation_model_selection"
IMAGE_MIGRATION_VERSION_KEY = "ai_connections_image_migration_version"
IMAGE_MIGRATION_VERSION = 1
EMBEDDING_SELECTION_KEY = "embedding_model_selection"
EMBEDDING_MIGRATION_VERSION_KEY = "ai_connections_embedding_migration_version"
EMBEDDING_MIGRATION_VERSION = 1
EMPTY_MODEL_SELECTION = {"endpoint_id": "", "model_id": "", "provider": ""}
IMAGE_PROVIDERS = ("aoai", "aifoundry", "new_foundry")
EMBEDDING_PROVIDERS = (*IMAGE_PROVIDERS, "openai_compatible")
_EMBEDDING_OVERRIDE_FIELDS = ("supportsEmbeddings", "supports_embeddings")
_PUBLIC_EMBEDDING_POLICY_FIELDS = (
    "default_dimensions", "dimensions", "supports_dimensions", "request_dimensions",
    "min_dimensions", "max_dimensions", "allowed_dimensions", "max_input_tokens",
    "max_batch_size", "max_batch_tokens", "tokenizer", "api", "requires_input_type",
)
_DIRECT_IMAGE_PATTERN = re.compile(r"^(?:gpt-image(?:-|$)|dall-e(?:-|$)|dalle(?:-|$))")
_NON_CHAT_PATTERN = re.compile(
    r"embedding|^whisper|(?:^|-)(?:tts|transcribe|realtime)(?:-|$)"
)


@dataclass(frozen=True)
class CapabilityDefinition:
    """An implemented operation; future integrations register their own definition."""

    key: str
    label: str
    selection_key: str
    catalog_flag: str
    supported_providers: tuple = ()
    feature_flag: str = ""
    api_routes: tuple = ()
    support_resolver: Callable | None = field(default=None, repr=False, compare=False)


CAPABILITY_DEFINITIONS = {
    CHAT_CAPABILITY: CapabilityDefinition(
        CHAT_CAPABILITY, "Chat", "default_model_selection", "generatesText",
        feature_flag="enable_multi_model_endpoints", api_routes=("chat",),
    ),
    IMAGE_GENERATION_CAPABILITY: CapabilityDefinition(
        IMAGE_GENERATION_CAPABILITY,
        "Image generation",
        IMAGE_SELECTION_KEY,
        "generatesImages",
        IMAGE_PROVIDERS,
        feature_flag="enable_image_generation", api_routes=("images", "responses"),
    ),
    EMBEDDINGS_CAPABILITY: CapabilityDefinition(
        EMBEDDINGS_CAPABILITY,
        "Embeddings",
        EMBEDDING_SELECTION_KEY,
        "generatesEmbeddings",
        EMBEDDING_PROVIDERS,
        api_routes=("azure_openai", "openai"),
    ),
}
_CLIENT_FACTORIES = {}


class AIConnectionError(ValueError):
    """A stable, user-safe connection or capability validation error."""

    def __init__(self, message, code="invalid_model_selection"):
        super().__init__(message)
        self.public_message = message
        self.code = code


@dataclass(frozen=True)
class ModelBinding:
    """Server-only resolved configuration. Never serialize this into a browser payload."""

    capability: str
    selection: dict
    endpoint: dict = field(repr=False)
    model: dict

    @property
    def operation_settings(self):
        return get_connection_operation_settings(self.endpoint, self.capability)


def register_capability(definition, client_factory=None):
    """Register a code-defined operation, not a provider supplied by request data."""
    if not isinstance(definition, CapabilityDefinition) or not definition.key:
        raise ValueError("A capability definition with a key is required.")
    if definition.key in CAPABILITY_DEFINITIONS:
        raise ValueError(f"Capability '{definition.key}' is already registered.")
    if client_factory is not None and not callable(client_factory):
        raise TypeError("A capability client factory must be callable.")
    if definition.support_resolver is not None and not callable(definition.support_resolver):
        raise TypeError("A capability support resolver must be callable.")
    CAPABILITY_DEFINITIONS[definition.key] = definition
    if client_factory is not None:
        register_capability_client_factory(definition.key, client_factory)


def get_capability_definition(capability):
    definition = CAPABILITY_DEFINITIONS.get(capability)
    if definition is None:
        raise AIConnectionError("This AI capability is not implemented.", "unsupported_capability")
    return definition


def register_capability_client_factory(capability, factory):
    """Connect an operation to a concrete, server-side client adapter."""
    get_capability_definition(capability)
    if not callable(factory):
        raise TypeError("A capability client factory must be callable.")
    _CLIENT_FACTORIES[capability] = factory


def create_capability_client(binding, settings):
    """Build an operation-specific client without pretending its payload is universal."""
    if not is_capability_enabled(settings, binding.capability):
        raise AIConnectionError("This AI capability is not enabled.", "capability_disabled")
    factory = _CLIENT_FACTORIES.get(binding.capability)
    if factory is None:
        raise AIConnectionError(
            "The selected AI capability has no configured runtime adapter.",
            "unsupported_capability",
        )
    return factory(binding, settings)


def is_capability_enabled(settings, capability):
    definition = get_capability_definition(capability)
    return not definition.feature_flag or bool(settings.get(definition.feature_flag))


def normalize_capability_selection(selection):
    source = selection if isinstance(selection, Mapping) else {}
    return {
        "endpoint_id": str(source.get("endpoint_id") or "").strip(),
        "model_id": str(source.get("model_id") or "").strip(),
        "provider": str(source.get("provider") or "").strip().lower(),
    }


def _model_name(model):
    if isinstance(model, str):
        return model.strip().lower().replace("_", "-")
    if not isinstance(model, Mapping):
        return ""
    for field_name in ("modelName", "behavior_name", "deploymentName", "deployment", "name"):
        value = model.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip().lower().replace("_", "-")
    return str(model.get("id") or "").strip().lower().replace("_", "-")


def _declared_flag(model, *names):
    if not isinstance(model, Mapping):
        return None
    for name in names:
        value = model.get(name)
        if isinstance(value, bool):
            return value
    return None


def _declared_embedding_flag(model):
    if not isinstance(model, Mapping):
        return None
    values = [model[field] for field in _EMBEDDING_OVERRIDE_FIELDS if field in model]
    if any(value is False for value in values):
        return False
    if any(not isinstance(value, bool) for value in values):
        raise EmbeddingPolicyError("Embedding support must be true or false.")
    return True if values else None


def _support(supported, source, reason="", api=""):
    return {
        "supported": supported,
        "source": source,
        "reason": reason,
        "api": api,
    }


def resolve_model_capability(model, capability, provider="aoai"):
    """Describe technical support; availability and transient service health are separate."""
    definition = get_capability_definition(capability)
    provider = str(provider or "aoai").strip().lower()
    if definition.supported_providers and provider not in definition.supported_providers:
        return _support(False, "provider", "This connection type has no supported adapter for this capability.")
    if capability == CHAT_CAPABILITY and provider == "openai_compatible":
        return _support(False, "provider", "Custom OpenAI-compatible connections support embeddings only.")

    if definition.support_resolver is not None:
        result = definition.support_resolver(model, provider)
        if isinstance(result, bool):
            return _support(result, "provider", "" if result else "This model does not support the requested capability.")
        if not isinstance(result, Mapping) or not isinstance(result.get("supported"), bool):
            raise AIConnectionError("The capability adapter returned an invalid support description.")
        return _support(
            result["supported"], str(result.get("source") or "provider"),
            str(result.get("reason") or ""), str(result.get("api") or ""),
        )

    name = _model_name(model)
    catalog = get_model_catalog_capabilities(model, strict_identity=capability == EMBEDDINGS_CAPABILITY)
    direct_image = bool(_DIRECT_IMAGE_PATTERN.search(name))
    if capability == CHAT_CAPABILITY:
        underlying_is_named = isinstance(model, str) or (
            isinstance(model, Mapping) and any(
                isinstance(model.get(field_name), str) and model[field_name].strip()
                for field_name in ("modelName", "behavior_name")
            )
        )
        embedding_only = catalog and catalog.get("generatesEmbeddings") is True and catalog.get("generatesText") is False
        if direct_image or embedding_only or (underlying_is_named and _NON_CHAT_PATTERN.search(name)):
            return _support(False, "model", "This model is not supported by the text-chat adapter.")
        declared = _declared_flag(model, "supportsChat", "supports_chat")
        if declared is not None:
            return _support(declared, "declared", "" if declared else "Chat is not supported by this model.", "chat")
        if catalog is not None and "generatesText" in catalog:
            supported = bool(catalog.get("generatesText"))
            return _support(supported, "catalog", "" if supported else "This model does not produce text.", "chat")
        if _declared_flag(model, "supportsEmbeddings", "supports_embeddings") is True:
            return _support(False, "declared", "This embedding deployment has not been declared as a chat model.")
        # Existing manually named chat deployments must not disappear on upgrade.
        return _support(bool(name), "legacy", "" if name else "A deployment name is required.", "chat")

    if capability == IMAGE_GENERATION_CAPABILITY:
        if catalog and catalog.get("generatesEmbeddings") is True and catalog.get("generatesImages") is False:
            return _support(False, "model", "This embedding model does not generate images.")
        declared = _declared_flag(model, "supportsImageGeneration", "supports_image_generation")
        route = str(model.get("image_generation_api") or "") if isinstance(model, Mapping) else ""
        if declared is False:
            return _support(False, "declared", "Image generation is not supported by this model.")
        if direct_image:
            return _support(True, "model", api="images")
        if declared is True:
            return _support(True, "declared", api=route if route in ("images", "responses") else "responses")
        if catalog and catalog.get("imageGenerationTool") is True:
            return _support(True, "catalog", api="responses")
        if catalog and catalog.get("generatesImages") is True:
            return _support(
                False,
                "provider",
                "This image model requires a provider-specific image adapter or an explicitly declared compatible image API.",
            )
        return _support(False, "unknown", "Image generation support has not been established for this model.")

    if capability == EMBEDDINGS_CAPABILITY:
        try:
            declared = _declared_embedding_flag(model)
        except EmbeddingPolicyError as error:
            return _support(False, "declared", error.public_message)
        if declared is False:
            return _support(False, "declared", "Embeddings are not supported by this model.")
        if declared is not True and not (catalog and catalog.get("generatesEmbeddings") is True):
            return _support(
                False, "unknown",
                "Embedding support is not established. Select a catalog model or declare supportsEmbeddings with verified embedding limits.",
            )
        try:
            policy = resolve_embedding_policy(model)
        except EmbeddingPolicyError as error:
            return _support(False, "policy", error.public_message)
        if policy["api"] != "openai":
            return _support(
                False, "provider",
                "This model requires an explicitly declared OpenAI-compatible gateway that handles its embedding semantics. Native and deprecated APIs are not supported.",
                "unsupported",
            )
        return _support(True, "declared" if declared is True else "catalog", api=policy["api"])

    supported = bool(catalog and catalog.get(definition.catalog_flag))
    return _support(
        supported,
        "catalog" if catalog is not None else "unknown",
        "" if supported else "This model does not support the requested capability.",
    )


def supports_model_capability(model, capability=CHAT_CAPABILITY, provider="aoai"):
    """Return whether a model is technically suitable and published for this operation."""
    if isinstance(model, Mapping):
        if model.get("enabled") is False:
            return False
        enabled_capabilities = model.get("enabled_capabilities")
        if isinstance(enabled_capabilities, list) and capability not in enabled_capabilities:
            return False
    return resolve_model_capability(model, capability, provider)["supported"]


def require_model_capability(model, capability=CHAT_CAPABILITY, provider="aoai"):
    """Reject incompatible saved/free-form bindings at an inference boundary."""
    if not supports_model_capability(model, capability, provider):
        definition = get_capability_definition(capability)
        raise AIConnectionError(
            f"The selected model is not available for {definition.label.lower()}. Choose a compatible model.",
            "model_capability_unavailable",
        )
    return model


def normalize_model_capability_fields(model):
    """Validate new metadata without discarding unrelated, existing model properties."""
    normalized = dict(model)
    normalized.pop("capability_status", None)
    for field in ("supportsChat", "supportsImageGeneration", "supportsEmbeddings", "supports_embeddings"):
        if field in normalized and not isinstance(normalized[field], bool):
            raise AIConnectionError(f"{field} must be true or false.")
    if "enabled_capabilities" in normalized:
        values = normalized["enabled_capabilities"]
        if not isinstance(values, list) or any(
            not isinstance(value, str) or value not in CAPABILITY_DEFINITIONS for value in values
        ):
            raise AIConnectionError("Model availability must name implemented AI capabilities.")
        normalized["enabled_capabilities"] = list(dict.fromkeys(values))
    if normalized.get("image_generation_api") not in (None, "", "images", "responses"):
        raise AIConnectionError("The image-generation API must be Images or Responses.")
    try:
        if "embedding_config" in normalized:
            normalized["embedding_config"] = normalize_embedding_config(normalized["embedding_config"])
        catalog = get_model_catalog_capabilities(normalized, strict_identity=True)
        if (
            normalized.get("embedding_config")
            or _declared_embedding_flag(normalized) is True
            or (catalog and catalog.get("generatesEmbeddings") is True)
        ):
            resolve_embedding_policy(normalized)
    except EmbeddingPolicyError as error:
        raise AIConnectionError(error.public_message) from None
    return normalized


def filter_model_endpoints_by_capability(endpoints, capability=CHAT_CAPABILITY, *, preserve_empty=False):
    """Project a consumer's catalog without mutating the underlying connection registry."""
    get_capability_definition(capability)
    result = []
    for endpoint in endpoints or []:
        if not isinstance(endpoint, Mapping):
            continue
        models = [
            copy.deepcopy(model)
            for model in endpoint.get("models") or []
            if isinstance(model, Mapping)
            and endpoint.get("enabled") is not False
            and supports_model_capability(model, capability, endpoint.get("provider"))
        ]
        if models or preserve_empty:
            projected = copy.deepcopy(endpoint)
            projected["models"] = models
            result.append(projected)
    return result


def get_connection_operation_settings(endpoint, capability):
    get_capability_definition(capability)
    connection = endpoint.get("connection") or {}
    if not isinstance(connection, Mapping):
        raise AIConnectionError("The selected connection configuration is invalid.")
    profiles = connection.get("operation_settings") or {}
    if not isinstance(profiles, Mapping):
        raise AIConnectionError("The selected connection's operation settings are invalid.")
    profile = profiles.get(capability) or {}
    if not isinstance(profile, Mapping):
        raise AIConnectionError("The selected capability's operation settings are invalid.")
    return dict(profile)


def resolve_capability_model_selection(selection, endpoints, capability=CHAT_CAPABILITY):
    """Return a valid reference or an empty reference plus a safe invalidation reason."""
    definition = get_capability_definition(capability)
    normalized = normalize_capability_selection(selection)
    if not normalized["endpoint_id"] or not normalized["model_id"]:
        return dict(EMPTY_MODEL_SELECTION), None
    endpoint = next(
        (item for item in endpoints or [] if isinstance(item, Mapping) and str(item.get("id")) == normalized["endpoint_id"]),
        None,
    )
    if endpoint is None or endpoint.get("enabled") is False:
        return dict(EMPTY_MODEL_SELECTION), f"{definition.label} connection is unavailable. Select another connection."
    model = next(
        (
            item for item in endpoint.get("models") or []
            if isinstance(item, Mapping)
            and str(item.get("id") or item.get("deploymentName") or "") == normalized["model_id"]
        ),
        None,
    )
    if model is None or not supports_model_capability(model, capability, endpoint.get("provider")):
        return dict(EMPTY_MODEL_SELECTION), f"{definition.label} model is unavailable or incompatible. Select a compatible model."
    normalized["provider"] = str(endpoint.get("provider") or "aoai").lower()
    return normalized, None


def resolve_capability_binding(settings, capability, selection=None):
    """Resolve a global default to server-only credentials and a concrete model."""
    definition = get_capability_definition(capability)
    selected = settings.get(definition.selection_key) if selection is None else selection
    endpoints = settings.get("model_endpoints") or []
    normalized, reason = resolve_capability_model_selection(selected, endpoints, capability)
    if not normalized["endpoint_id"]:
        raise AIConnectionError(
            reason or f"No default {definition.label.lower()} model is selected. Ask an administrator to configure AI Connections.",
            "model_configuration_unavailable",
        )
    endpoint = next(item for item in endpoints if str(item.get("id")) == normalized["endpoint_id"])
    model = next(
        item for item in endpoint.get("models") or []
        if str(item.get("id") or item.get("deploymentName") or "") == normalized["model_id"]
    )
    return ModelBinding(capability, normalized, copy.deepcopy(endpoint), copy.deepcopy(model))


def image_connection_import_is_complete(settings):
    version = settings.get(IMAGE_MIGRATION_VERSION_KEY) if isinstance(settings, Mapping) else None
    return isinstance(version, int) and not isinstance(version, bool) and version >= IMAGE_MIGRATION_VERSION


def image_settings_use_connections(settings):
    """An explicitly cleared shared default must never reactivate legacy settings."""
    return isinstance(settings, Mapping) and (
        IMAGE_SELECTION_KEY in settings
        or image_connection_import_is_complete(settings)
    )


def embedding_connection_import_is_complete(settings):
    version = settings.get(EMBEDDING_MIGRATION_VERSION_KEY) if isinstance(settings, Mapping) else None
    return isinstance(version, int) and not isinstance(version, bool) and version >= EMBEDDING_MIGRATION_VERSION


def embedding_settings_use_connections(settings):
    """Embedding handoff is independent of image import and never resurrects a cleared default."""
    return isinstance(settings, Mapping) and (
        EMBEDDING_SELECTION_KEY in settings
        or embedding_connection_import_is_complete(settings)
    )


def build_capability_model_catalog(endpoints, capability=CHAT_CAPABILITY):
    """Return non-secret, ID-qualified picker entries from enabled global connections."""
    choices = []
    for endpoint in filter_model_endpoints_by_capability(endpoints, capability):
        endpoint_id = str(endpoint.get("id") or "")
        if not endpoint_id:
            continue
        for model in endpoint["models"]:
            model_id = str(model.get("id") or model.get("deploymentName") or "")
            if not model_id:
                continue
            choice = {
                "endpoint_id": endpoint_id,
                "model_id": model_id,
                "provider": str(endpoint.get("provider") or "aoai"),
                "connection_name": str(endpoint.get("name") or "Connection"),
                "label": str(model.get("displayName") or model.get("modelName") or model.get("deploymentName") or model_id),
                "deployment_name": str(model.get("deploymentName") or model.get("deployment") or model_id),
                "capability": resolve_model_capability(model, capability, endpoint.get("provider")),
            }
            if capability == EMBEDDINGS_CAPABILITY:
                policy = resolve_embedding_policy(model)
                choice["embedding_policy"] = {
                    field: copy.deepcopy(policy[field])
                    for field in _PUBLIC_EMBEDDING_POLICY_FIELDS if field in policy
                }
            choices.append(choice)
    return sorted(choices, key=lambda item: (item["connection_name"].lower(), item["label"].lower(), item["endpoint_id"], item["model_id"]))


def describe_model_capabilities(model, provider="aoai"):
    """Public technical support and publication metadata, never connection secrets."""
    result = {}
    for key in CAPABILITY_DEFINITIONS:
        result[key] = {
            **resolve_model_capability(model, key, provider),
            "available": supports_model_capability(model, key, provider),
        }
    supports_vision, source = resolve_model_vision_support(model)
    result["vision"] = {
        "supported": supports_vision and resolve_model_capability(model, CHAT_CAPABILITY, provider)["supported"],
        "source": source,
    }
    return result
