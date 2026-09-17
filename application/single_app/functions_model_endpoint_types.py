# functions_model_endpoint_types.py
"""Canonical Custom provider, API type, and request model identifiers."""

from typing import Any

from functions_model_endpoint_providers import (
    DEFAULT_ANTHROPIC_VERSION,
    MODEL_ENDPOINT_API_TYPE_ANTHROPIC,
    MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI,
    MODEL_ENDPOINT_API_TYPE_GEMINI,
    MODEL_ENDPOINT_API_TYPE_OPENAI,
    MODEL_ENDPOINT_CUSTOM_API_TYPES,
    MODEL_ENDPOINT_PROVIDER_CUSTOM,
    get_model_endpoint_provider,
    normalize_api_type_value,
)


__all__ = [
    "DEFAULT_ANTHROPIC_VERSION",
    "MODEL_ENDPOINT_API_TYPE_ANTHROPIC",
    "MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI",
    "MODEL_ENDPOINT_API_TYPE_GEMINI",
    "MODEL_ENDPOINT_API_TYPE_OPENAI",
    "MODEL_ENDPOINT_CUSTOM_API_TYPES",
    "MODEL_ENDPOINT_PROVIDER_CUSTOM",
    "get_model_endpoint_api_type",
    "normalize_model_endpoint_api_type",
    "resolve_model_endpoint_request_model",
]


def normalize_model_endpoint_api_type(provider: Any, api_type: Any) -> str:
    if str(provider or "").strip().lower() != MODEL_ENDPOINT_PROVIDER_CUSTOM:
        return ""
    normalized = normalize_api_type_value(api_type)
    return normalized if normalized in MODEL_ENDPOINT_CUSTOM_API_TYPES else ""


def get_model_endpoint_api_type(endpoint: Any) -> str:
    if not isinstance(endpoint, dict):
        return ""
    return normalize_model_endpoint_api_type(endpoint.get("provider"), endpoint.get("api_type"))


def resolve_model_endpoint_request_model(endpoint: Any, model: Any) -> str:
    """Resolve a wire identifier, never the registry ID used for saved selections."""
    endpoint_data = endpoint if isinstance(endpoint, dict) else {}
    model_data = model if isinstance(model, dict) else {}
    if str(endpoint_data.get("provider") or "").strip().lower() == MODEL_ENDPOINT_PROVIDER_CUSTOM:
        provider = get_model_endpoint_provider(get_model_endpoint_api_type(endpoint_data))
        if provider is None:
            return ""
        if provider.uses_model_name:
            return str(model_data.get("modelName") or model_data.get("name") or "").strip()
        return str(model_data.get("deploymentName") or model_data.get("deployment") or "").strip()
    return str(
        model_data.get("deploymentName")
        or model_data.get("deployment")
        or model_data.get("modelName")
        or model_data.get("name")
        or ""
    ).strip()
