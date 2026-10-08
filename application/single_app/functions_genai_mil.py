# functions_genai_mil.py
"""Scoped GenAI.mil discovery using the existing protected Custom transport."""

import json

import httpx

from functions_model_endpoint_auth import resolve_custom_endpoint_credentials
from functions_model_endpoint_diagnostics import build_genai_mil_error
from functions_model_endpoint_validation import validate_custom_model_endpoint_url
from functions_model_endpoint_urls import resolve_custom_openai_base_url
from functions_settings import resolve_model_endpoint_ca_trust
from model_endpoint_clients import build_custom_openai_sync_http_client
from model_endpoint_profiles import ModelEndpointProfileError, validate_genai_profile


MAX_DISCOVERY_BYTES = 1024 * 1024
MAX_DISCOVERED_MODELS = 1000


def fetch_genai_mil_models(endpoint, settings):
    validate_genai_profile(endpoint)
    auth = endpoint.get("auth") or {}
    allow_private = bool(settings.get("allow_private_custom_model_endpoints"))
    base = validate_custom_model_endpoint_url(
        (endpoint.get("connection") or {}).get("endpoint"),
        allow_private=allow_private,
    )
    base = resolve_custom_openai_base_url(base, "openai", "auto")
    trust = resolve_model_endpoint_ca_trust(
        endpoint, settings, str(settings.get("custom_model_endpoint_ca_bundle_path") or ""),
    )
    key, additional_headers = resolve_custom_endpoint_credentials(
        auth, default_api_key_header="Authorization", default_api_key_prefix="Bearer",
        allow_private=allow_private, ca_bundle_path=trust,
    )
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json", **additional_headers}
    try:
        with build_custom_openai_sync_http_client(allow_private=allow_private, ca_bundle_path=trust) as client:
            with client.stream("GET", base.rstrip("/") + "/models", headers=headers, timeout=httpx.Timeout(30, connect=10)) as response:
                if response.status_code >= 400:
                    raise build_genai_mil_error(status_code=response.status_code, headers=response.headers)
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_DISCOVERY_BYTES:
                        raise ModelEndpointProfileError("The GenAI.mil model inventory exceeds the supported size.")
        payload = json.loads(data)
    except httpx.HTTPError as error:
        raise build_genai_mil_error(error) from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ModelEndpointProfileError("GenAI.mil returned an invalid model inventory.") from None
    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list) or len(models) > MAX_DISCOVERED_MODELS:
        raise ModelEndpointProfileError("GenAI.mil returned an invalid or oversized model inventory.")
    result = []
    identifiers = set()
    for model in models:
        identifier = model.get("id") if isinstance(model, dict) else None
        if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 256 or any(ord(character) < 32 for character in identifier):
            raise ModelEndpointProfileError("GenAI.mil returned an invalid model identifier.")
        if identifier not in identifiers:
            identifiers.add(identifier)
            result.append({"modelName": identifier, "displayName": identifier, "api_type": "openai", "url_mode": "auto"})
    return result
