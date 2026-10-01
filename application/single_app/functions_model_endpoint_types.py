# functions_model_endpoint_types.py
"""Canonical provider, API type, and model identifier helpers.

The supported API types and their per-type behaviour live in
functions_model_endpoint_providers. This module keeps the long-standing helper
names that the rest of the application imports, and delegates the decisions to
the registry so an API type is declared in exactly one place.
"""

from typing import Any, Dict, Optional, Tuple

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
    "find_enabled_model_endpoint_for_model_name",
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


def _get_model_name_match_rank(endpoint: Dict[str, Any], model: Dict[str, Any], model_name: str) -> Optional[int]:
    """Return how strongly a model matches a stored name, lower being stronger, or None."""
    deployment_name = str(model.get("deploymentName") or "").strip()
    if model_name in (deployment_name, resolve_model_endpoint_request_model(endpoint, model)):
        return 0
    if str(model.get("modelName") or "").strip() == model_name:
        return 1
    if str(model.get("id") or "").strip() == model_name:
        return 2
    return None


def find_enabled_model_endpoint_for_model_name(
    endpoints: Any,
    model_name: Any,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Return the enabled endpoint and enabled model that serve a stored model name.

    Some settings, such as the multi-modal vision model, store only a model name rather than
    an endpoint and model id. This resolves that name against the given endpoint records
    without reading settings or secrets, so callers pass already-normalized endpoints.

    A deployment name or the resolved request model wins over a friendly model name, which
    wins over a model id. Within the same precedence, the first match in endpoint order wins,
    so a name that is a deployment on one connection and only a model family name on another
    resolves to the connection that actually deploys it. Records without an ``enabled`` flag
    count as enabled, matching ``normalize_model_endpoints``.

    Returns ``(endpoint, model)``, or ``(None, None)`` when nothing matches.
    """
    requested_name = str(model_name or "").strip()
    if not requested_name or not isinstance(endpoints, (list, tuple)):
        return None, None

    best_match = (None, None)
    best_rank = None
    for endpoint in endpoints:
        if not isinstance(endpoint, dict) or not endpoint.get("enabled", True):
            continue
        models = endpoint.get("models")
        if not isinstance(models, (list, tuple)):
            continue
        for model in models:
            if not isinstance(model, dict) or not model.get("enabled", True):
                continue
            rank = _get_model_name_match_rank(endpoint, model, requested_name)
            if rank is None or (best_rank is not None and rank >= best_rank):
                continue
            best_match = (endpoint, model)
            best_rank = rank
            if rank == 0:
                return best_match

    return best_match
