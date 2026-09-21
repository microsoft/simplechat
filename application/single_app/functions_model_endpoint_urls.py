# functions_model_endpoint_urls.py
"""Pure Custom API URL contracts shared by profiles and runtime clients."""

import re
from typing import Any
from urllib.parse import quote, urlparse

from functions_model_endpoint_providers import (
    MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
    URL_POLICY_AS_GIVEN,
    get_model_endpoint_provider,
    normalize_custom_endpoint_url_mode,
)
from functions_model_endpoint_validation import ModelEndpointValidationError


CUSTOM_OPENAI_OPERATION_SUFFIXES = (
    "/chat/completions", "/responses", "/models", "/images/generations", "/images/edits", "/embeddings",
)
CUSTOM_OPENAI_VERSION_SEGMENT_PATTERN = re.compile(r"^v\d+(?:[a-z][a-z0-9]*)?$", re.IGNORECASE)


def normalize_endpoint_text(endpoint: Any) -> str:
    """Return a trimmed endpoint URL without a trailing slash."""
    return str(endpoint or "").strip().rstrip("/")


def normalize_custom_openai_base_url(raw_endpoint: Any) -> str:
    """Append v1 only when neither a version nor a full operation defines the base."""
    endpoint = normalize_endpoint_text(raw_endpoint)
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
    """Resolve an OpenAI-compatible base without adding Azure deployment semantics."""
    descriptor = get_model_endpoint_provider(api_type or "openai")
    if descriptor is None or descriptor.protocol != MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE:
        raise ModelEndpointValidationError("This Custom API type does not use an OpenAI-compatible base URL.")
    if normalize_custom_endpoint_url_mode(url_mode) == "exact" or descriptor.url_policy == URL_POLICY_AS_GIVEN:
        endpoint = normalize_endpoint_text(raw_endpoint)
        if not endpoint:
            raise ModelEndpointValidationError("A Custom endpoint URL is required.")
        return endpoint + "/"
    return normalize_custom_openai_base_url(raw_endpoint)


def resolve_custom_azure_openai_base_url(raw_endpoint: Any, deployment_name: Any, url_mode: Any = "") -> str:
    """Build the dated deployment API base, retaining gateway prefixes."""
    endpoint = normalize_endpoint_text(raw_endpoint)
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
