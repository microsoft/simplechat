# functions_model_endpoint_types.py
"""Canonical provider, API type, and model identifier helpers."""

from typing import Any, Dict


MODEL_ENDPOINT_PROVIDER_CUSTOM = "custom"
MODEL_ENDPOINT_API_TYPE_OPENAI = "openai"
MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI = "azure_openai"
MODEL_ENDPOINT_API_TYPE_ANTHROPIC = "anthropic"
MODEL_ENDPOINT_CUSTOM_API_TYPES = {
    MODEL_ENDPOINT_API_TYPE_OPENAI,
    MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI,
    MODEL_ENDPOINT_API_TYPE_ANTHROPIC,
}
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"


def normalize_model_endpoint_api_type(provider: Any, api_type: Any) -> str:
    """Return a supported explicit API type for Custom endpoints."""
    normalized_provider = str(provider or "").strip().lower()
    normalized_api_type = str(api_type or "").strip().lower().replace("-", "_")
    if normalized_provider != MODEL_ENDPOINT_PROVIDER_CUSTOM:
        return ""
    return normalized_api_type if normalized_api_type in MODEL_ENDPOINT_CUSTOM_API_TYPES else ""


def get_model_endpoint_api_type(endpoint: Any) -> str:
    """Return the canonical explicit API type from an endpoint record."""
    if not isinstance(endpoint, dict):
        return ""
    return normalize_model_endpoint_api_type(endpoint.get("provider"), endpoint.get("api_type"))


def resolve_model_endpoint_request_model(endpoint: Any, model: Any) -> str:
    """Resolve the model identifier that must be sent to the configured API."""
    endpoint_data: Dict[str, Any] = endpoint if isinstance(endpoint, dict) else {}
    model_data: Dict[str, Any] = model if isinstance(model, dict) else {}
    provider = str(endpoint_data.get("provider") or "aoai").strip().lower()
    api_type = get_model_endpoint_api_type(endpoint_data)

    if provider == MODEL_ENDPOINT_PROVIDER_CUSTOM:
        if api_type in {
            MODEL_ENDPOINT_API_TYPE_OPENAI,
            MODEL_ENDPOINT_API_TYPE_ANTHROPIC,
        }:
            return str(model_data.get("modelName") or model_data.get("name") or "").strip()
        if api_type == MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI:
            return str(
                model_data.get("deploymentName")
                or model_data.get("deployment")
                or ""
            ).strip()
        return ""

    return str(
        model_data.get("deploymentName")
        or model_data.get("deployment")
        or model_data.get("modelName")
        or model_data.get("name")
        or ""
    ).strip()
