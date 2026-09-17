# functions_model_endpoint_types.py
"""Canonical Custom provider, API type, and request model identifiers."""

import copy
import re
from typing import Any
from urllib.parse import quote, urlparse

from functions_model_endpoint_providers import (
    DEFAULT_ANTHROPIC_VERSION,
    MODEL_ENDPOINT_API_TYPE_ANTHROPIC,
    MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI,
    MODEL_ENDPOINT_API_TYPE_GEMINI,
    MODEL_ENDPOINT_API_TYPE_OPENAI,
    MODEL_ENDPOINT_CUSTOM_API_TYPES,
    MODEL_ENDPOINT_PROVIDER_CUSTOM,
    MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
    URL_POLICY_AS_GIVEN,
    get_model_endpoint_provider,
    normalize_api_type_value,
    normalize_custom_endpoint_url_mode,
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
    "custom_endpoint_validation_view",
    "normalize_custom_openai_base_url",
    "resolve_custom_openai_base_url",
    "resolve_custom_azure_openai_base_url",
    "ModelEndpointValidationError",
]


CUSTOM_OPENAI_OPERATION_SUFFIXES = (
    "/chat/completions", "/responses", "/models", "/images/generations", "/images/edits", "/embeddings",
)
CUSTOM_OPENAI_VERSION_SEGMENT_PATTERN = re.compile(r"^v\d+(?:[a-z][a-z0-9]*)?$", re.IGNORECASE)


class ModelEndpointValidationError(ValueError):
    """A stable, user-safe configuration or outbound-policy error."""

    def __init__(self, public_message):
        super().__init__(public_message)
        self.public_message = public_message


def custom_endpoint_validation_view(endpoint):
    """Apply the Custom foundation to retained embedding-only aliases without rewriting stored identities."""
    if not isinstance(endpoint, dict) or str(endpoint.get("provider") or "").strip().lower() != "openai_compatible":
        return endpoint
    result = copy.deepcopy(endpoint)
    result["provider"] = MODEL_ENDPOINT_PROVIDER_CUSTOM
    result["api_type"] = MODEL_ENDPOINT_API_TYPE_OPENAI
    result["name"] = result.get("name") or result.get("id") or "Embedding connection"
    result.setdefault("connection", {})["url_mode"] = "exact"
    for model in result.get("models") or []:
        if isinstance(model, dict):
            model["modelName"] = str(model.get("deploymentName") or model.get("deployment") or "").strip()
    return result


def normalize_custom_openai_base_url(raw_endpoint: Any) -> str:
    """Append v1 only when neither a version nor a full operation defines the base."""
    endpoint = str(raw_endpoint or "").strip().rstrip("/")
    if not endpoint:
        raise ModelEndpointValidationError("A Custom endpoint URL is required.")
    for suffix in CUSTOM_OPENAI_OPERATION_SUFFIXES:
        if endpoint.lower().endswith(suffix):
            return endpoint[:-len(suffix)].rstrip("/") + "/"
    last_segment = urlparse(endpoint).path.rstrip("/").rsplit("/", 1)[-1]
    if CUSTOM_OPENAI_VERSION_SEGMENT_PATTERN.fullmatch(last_segment):
        return endpoint + "/"
    return endpoint + "/v1/"


def resolve_custom_openai_base_url(raw_endpoint: Any, api_type: Any = "", url_mode: Any = "") -> str:
    descriptor = get_model_endpoint_provider(api_type or "openai")
    if descriptor is None or descriptor.protocol != MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE:
        raise ModelEndpointValidationError("This Custom API type does not use an OpenAI-compatible base URL.")
    if normalize_custom_endpoint_url_mode(url_mode) == "exact" or descriptor.url_policy == URL_POLICY_AS_GIVEN:
        endpoint = str(raw_endpoint or "").strip().rstrip("/")
        if not endpoint:
            raise ModelEndpointValidationError("A Custom endpoint URL is required.")
        return endpoint + "/"
    return normalize_custom_openai_base_url(raw_endpoint)


def resolve_custom_azure_openai_base_url(raw_endpoint: Any, deployment_name: Any, url_mode: Any = "") -> str:
    endpoint = str(raw_endpoint or "").strip().rstrip("/")
    deployment = str(deployment_name or "").strip()
    if not endpoint or not deployment:
        raise ModelEndpointValidationError("Custom Azure OpenAI requires an endpoint and deployment name.")
    if normalize_custom_endpoint_url_mode(url_mode) == "exact":
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
