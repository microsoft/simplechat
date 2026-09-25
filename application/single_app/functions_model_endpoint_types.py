# functions_model_endpoint_types.py
"""Canonical provider, API type, and model identifier helpers.

The supported API types and their per-type behaviour live in
functions_model_endpoint_providers. This module keeps the long-standing helper
names that the rest of the application imports, and delegates the decisions to
the registry so an API type is declared in exactly one place.
"""

from typing import Any, Dict
from functions_model_endpoint_urls import routing_schema_version

from functions_model_endpoint_providers import (
    DEFAULT_ANTHROPIC_VERSION,
    MODEL_ENDPOINT_API_TYPE_ANTHROPIC,
    MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI,
    MODEL_ENDPOINT_API_TYPE_OPENAI,
    MODEL_ENDPOINT_CUSTOM_API_TYPES,
    MODEL_ENDPOINT_PROVIDER_CUSTOM,
    get_model_endpoint_provider,
    normalize_api_type_value,
)


# Callers have long imported these constants from this module rather than from the
# registry that now owns them, so they are re-exported deliberately.
__all__ = [
    "DEFAULT_ANTHROPIC_VERSION",
    "MODEL_ENDPOINT_API_TYPE_ANTHROPIC",
    "MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI",
    "MODEL_ENDPOINT_API_TYPE_OPENAI",
    "MODEL_ENDPOINT_CUSTOM_API_TYPES",
    "MODEL_ENDPOINT_PROVIDER_CUSTOM",
    "get_model_endpoint_api_type",
    "normalize_model_endpoint_api_type",
    "resolve_model_endpoint_request_model",
]


def normalize_model_endpoint_api_type(provider: Any, api_type: Any) -> str:
    """Return a supported explicit API type for Custom endpoints."""
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider != MODEL_ENDPOINT_PROVIDER_CUSTOM:
        return ""
    normalized_api_type = normalize_api_type_value(api_type)
    return normalized_api_type if normalized_api_type in MODEL_ENDPOINT_CUSTOM_API_TYPES else ""


def get_model_endpoint_api_type(endpoint: Any, model: Any = None, *, use_model_routing: bool = False) -> str:
    """Return the canonical explicit API type from an endpoint record."""
    if not isinstance(endpoint, dict):
        return ""
    if routing_schema_version(endpoint) == 2:
        if not use_model_routing:
            raise ValueError("This consumer does not support explicit model routing.")
        if not isinstance(model, dict):
            raise ValueError("Explicit routing requires a selected model.")
        api_type = normalize_api_type_value(model.get("api_type"))
        if get_model_endpoint_provider(api_type) is None:
            raise ValueError("Unsupported model API type.")
        return api_type
    return normalize_model_endpoint_api_type(endpoint.get("provider"), endpoint.get("api_type"))


def resolve_model_endpoint_request_model(endpoint: Any, model: Any, *, use_model_routing: bool = False) -> str:
    """Resolve the model identifier that must be sent to the configured API."""
    endpoint_data: Dict[str, Any] = endpoint if isinstance(endpoint, dict) else {}
    model_data: Dict[str, Any] = model if isinstance(model, dict) else {}
    provider = str(endpoint_data.get("provider") or "aoai").strip().lower()

    if routing_schema_version(endpoint_data) == 2:
        api_type = get_model_endpoint_api_type(endpoint_data, model_data, use_model_routing=use_model_routing)
        descriptor = get_model_endpoint_provider(api_type)
        field = "modelName" if descriptor.uses_model_name else "deploymentName"
        identifier = model_data.get(field)
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("The selected model requires its protocol-specific identifier.")
        return identifier.strip()

    if provider == MODEL_ENDPOINT_PROVIDER_CUSTOM:
        registered_provider = get_model_endpoint_provider(get_model_endpoint_api_type(endpoint_data))
        if registered_provider is None:
            return ""
        if registered_provider.uses_model_name:
            return str(model_data.get("modelName") or model_data.get("name") or "").strip()
        return str(
            model_data.get("deploymentName")
            or model_data.get("deployment")
            or ""
        ).strip()

    return str(
        model_data.get("deploymentName")
        or model_data.get("deployment")
        or model_data.get("modelName")
        or model_data.get("name")
        or ""
    ).strip()
