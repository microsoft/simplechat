# functions_embeddings.py
"""Shared text embedding inference with explicit operation and result contracts."""

import math
import random
import time
from copy import deepcopy
from collections.abc import Mapping

import httpx
from azure.core.exceptions import AzureError
from azure.identity import get_bearer_token_provider
from openai import APIError, OpenAI, RateLimitError

from functions_ai_connections import (
    AIConnectionError,
    EMBEDDINGS_CAPABILITY,
    create_capability_client,
    embedding_settings_use_connections,
    register_capability_client_factory,
)
from functions_appinsights import log_event
from functions_embedding_profile import resolve_embedding_profile
from functions_model_endpoint_identity_header import build_model_endpoint_identity_headers
from functions_model_endpoint_auth import resolve_client_certificate, resolve_custom_endpoint_credentials
from functions_model_endpoint_types import custom_endpoint_validation_view, get_model_endpoint_api_type
from functions_model_endpoint_validation import custom_endpoint_setting_enabled, validate_custom_model_endpoint


class EmbeddingVector(list):
    """A JSON-compatible vector carrying provenance even when usage is unavailable."""

    def __init__(self, values, profile):
        super().__init__(values)
        self.profile_id = profile.profile_id
        self.legacy = profile.legacy


class EmbeddingInferenceError(AIConnectionError):
    pass


class _EmbeddingOpenAIClient(OpenAI):
    """Refresh identity tokens per request with the pinned OpenAI SDK."""

    def __init__(self, *, auth_header, token_provider=None, **kwargs):
        self._embedding_auth_header = auth_header
        self._embedding_token_provider = token_provider
        super().__init__(**kwargs)

    @property
    def auth_headers(self):
        if self._embedding_token_provider:
            return {"Authorization": f"Bearer {self._embedding_token_provider()}"}
        if self._embedding_auth_header == "authorization":
            return super().auth_headers
        return {self._embedding_auth_header: self.api_key}


def _build_embedding_connection_client(binding, settings):
    profile = resolve_embedding_profile(settings, binding=binding)
    endpoint = deepcopy(binding.endpoint)
    if embedding_settings_use_connections(settings):
        # Secret hydration must happen at runtime, not in the pure profile resolver.
        from functions_keyvault import SecretReturnType, keyvault_model_endpoint_get_helper

        endpoint = keyvault_model_endpoint_get_helper(
            endpoint, binding.selection["endpoint_id"], scope="global",
            return_type=SecretReturnType.VALUE,
        )
    auth = endpoint.get("auth") or {}
    provider = str(endpoint.get("provider") or "aoai").strip().lower()
    auth_type = str(auth.get("type") or "managed_identity").strip().lower()
    operation = binding.operation_settings
    auth_header = operation.get("auth_header") or (
        "authorization" if profile.api == "openai" else "api-key"
    )
    if provider in ("custom", "openai_compatible"):
        # Use the same pinned transport and global network policy as Custom chat/images.
        from model_endpoint_clients import build_custom_openai_sync_http_client

        custom = custom_endpoint_validation_view(endpoint)
        connection = custom.get("connection") or {}
        if operation.get("endpoint"):
            connection["endpoint"] = operation["endpoint"]
        custom["connection"] = connection
        validate_custom_model_endpoint(custom, settings)
        transport_options = {
            "allow_private": custom_endpoint_setting_enabled(settings, "allow_private_custom_model_endpoints"),
            "allow_insecure": custom_endpoint_setting_enabled(settings, "allow_insecure_custom_model_endpoints"),
            "ca_bundle_path": str(settings.get("custom_model_endpoint_ca_bundle_path") or ""),
            "client_cert": resolve_client_certificate(connection),
        }
        custom_auth = dict(custom.get("auth") or {})
        default_header = "api-key" if get_model_endpoint_api_type(custom) == "azure_openai" else "Authorization"
        default_prefix = "" if default_header == "api-key" else "Bearer"
        if operation.get("auth_header"):
            default_header = "Authorization" if auth_header == "authorization" else auth_header
            default_prefix = "Bearer" if auth_header == "authorization" else ""
        sdk_key, auth_headers = resolve_custom_endpoint_credentials(
            custom_auth, default_api_key_header=default_header,
            default_api_key_prefix=default_prefix, **transport_options,
        )
        return OpenAI(
            api_key=sdk_key, base_url=profile.base_url,
            default_headers={
                **build_model_endpoint_identity_headers(settings, endpoint_config=endpoint),
                **auth_headers,
            },
            default_query={"api-version": profile.api_version} if profile.api == "azure_openai" else {},
            max_retries=0, timeout=httpx.Timeout(60.0, connect=10.0),
            http_client=build_custom_openai_sync_http_client(**transport_options),
        )
    token_provider = None
    api_key = ""
    if auth_type in ("key", "api_key"):
        api_key = auth.get("api_key")
        if not isinstance(api_key, str) or not api_key.strip():
            raise AIConnectionError("The embedding connection is missing its API key.")
    elif auth_type in ("managed_identity", "service_principal") and provider != "openai_compatible":
        # Application credential helpers depend on settings/config initialization.
        from config import cognitive_services_scope
        from functions_model_endpoint_runtime import (
            resolve_credential_for_model_endpoint_auth,
            resolve_foundry_scope_for_endpoint_auth,
        )

        credential = resolve_credential_for_model_endpoint_auth(auth)
        scope = (
            resolve_foundry_scope_for_endpoint_auth(auth, endpoint=profile.base_url)
            if provider in ("aifoundry", "new_foundry") else cognitive_services_scope
        )
        token_provider = get_bearer_token_provider(credential, scope)
    else:
        raise AIConnectionError("This embedding connection does not support that authentication method.")
    return _EmbeddingOpenAIClient(
        api_key=api_key,
        auth_header=auth_header,
        token_provider=token_provider,
        base_url=profile.base_url,
        default_headers=build_model_endpoint_identity_headers(settings, endpoint_config=endpoint),
        default_query={"api-version": profile.api_version} if profile.api == "azure_openai" else {},
        max_retries=0,
        timeout=httpx.Timeout(60.0, connect=10.0),
        http_client=httpx.Client(follow_redirects=False),
    )


def build_embedding_connection_client(binding, settings):
    try:
        return _build_embedding_connection_client(binding, settings)
    except AIConnectionError:
        raise
    except (AzureError, ValueError, RuntimeError) as exc:
        log_event("[EMBEDDING] Connection initialization failed", extra={"error_type": type(exc).__name__})
        raise EmbeddingInferenceError(
            "The embedding connection could not be initialized. Review its credentials and configuration.",
            "embedding_connection_unavailable",
        ) from exc


register_capability_client_factory(EMBEDDINGS_CAPABILITY, build_embedding_connection_client)


def _validate_vector(values, dimensions):
    if (
        not isinstance(values, list) or len(values) != dimensions
        or any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in values
        )
    ):
        raise EmbeddingInferenceError(
            "The embedding service returned an invalid vector or unexpected dimensions.",
            "embedding_response_invalid",
        )


def _usage_count(usage, key):
    value = usage.get(key) if isinstance(usage, Mapping) else getattr(usage, key, None)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EmbeddingInferenceError("The embedding service returned invalid usage.", "embedding_response_invalid")
    return value


def normalize_embedding_response(response, count, profile):
    data = response.get("data") if isinstance(response, Mapping) else getattr(response, "data", None)
    if not isinstance(data, list) or len(data) != count:
        raise EmbeddingInferenceError(
            "The embedding service did not return one vector per input.", "embedding_response_invalid",
        )
    ordered = [None] * count
    usage = response.get("usage") if isinstance(response, Mapping) else getattr(response, "usage", None)
    prompt_tokens = _usage_count(usage, "prompt_tokens")
    total_tokens = _usage_count(usage, "total_tokens")
    if usage is not None and (prompt_tokens is None or total_tokens is None or total_tokens < prompt_tokens):
        raise EmbeddingInferenceError("The embedding service returned incomplete usage.", "embedding_response_invalid")
    for item in data:
        index = item.get("index") if isinstance(item, Mapping) else getattr(item, "index", None)
        if (
            isinstance(index, bool) or not isinstance(index, int) or index < 0
            or index >= count or ordered[index] is not None
        ):
            raise EmbeddingInferenceError(
                "The embedding service returned invalid input indexes.", "embedding_response_invalid",
            )
        values = item.get("embedding") if isinstance(item, Mapping) else getattr(item, "embedding", None)
        _validate_vector(values, profile.dimensions)
        token_usage = None
        if prompt_tokens is not None and total_tokens is not None:
            # Keep the exact aggregate instead of dropping division remainders.
            token_usage = {
                "prompt_tokens": prompt_tokens // count + (index < prompt_tokens % count),
                "total_tokens": total_tokens // count + (index < total_tokens % count),
                "model_deployment_name": profile.deployment,
            }
        ordered[index] = (EmbeddingVector(values, profile), token_usage)
    return ordered


def _prepare_inputs(texts, profile, purpose):
    if purpose not in ("document", "query", "text"):
        raise AIConnectionError("The embedding input purpose is invalid.")
    if not isinstance(texts, (list, tuple)):
        raise AIConnectionError("Embedding inputs must be a list of text values.")
    prefix = profile.policy.get(f"{purpose}_prefix") or ""
    prepared = []
    for text in texts:
        if not isinstance(text, str) or not text.strip():
            raise AIConnectionError("Embedding inputs must contain nonempty text.")
        value = prefix + text
        # UTF-8 bytes conservatively bound BPE token counts without downloading a tokenizer.
        token_bound = len(value.encode("utf-8"))
        if token_bound > profile.policy["max_input_tokens"] and not profile.legacy:
            raise AIConnectionError(
                "Embedding input exceeds the configured conservative input budget. Split the text into smaller chunks.",
                "embedding_input_too_large",
            )
        prepared.append((value, token_bound))
    return prepared


def generate_embedding_batch(
    texts, *, settings, purpose="document", batch_size=16, max_retries=5,
    initial_delay=1.0, delay_multiplier=2.0, retry_delay=None, profile=None,
):
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        raise AIConnectionError("Embedding batch size must be a positive integer.")
    if isinstance(max_retries, bool) or not isinstance(max_retries, int) or not 0 <= max_retries <= 10:
        raise AIConnectionError("Embedding retry count must be between zero and ten.")
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not math.isfinite(value) or value <= 0
        for value in (initial_delay, delay_multiplier)
    ):
        raise AIConnectionError("Embedding retry delays must be positive finite numbers.")
    profile = profile or resolve_embedding_profile(settings)
    prepared = _prepare_inputs(texts, profile, purpose)
    if not prepared:
        return []
    batch_limit = min(batch_size, profile.policy["max_batch_size"])
    token_limit = profile.policy["max_batch_tokens"]
    results = []
    with create_capability_client(profile.binding, settings) as client:
        offset = 0
        while offset < len(prepared):
            batch = []
            batch_tokens = 0
            while offset < len(prepared) and len(batch) < batch_limit:
                text, tokens = prepared[offset]
                if batch and batch_tokens + tokens > token_limit:
                    break
                if tokens > token_limit and not profile.legacy:
                    raise AIConnectionError("Embedding input exceeds the configured batch budget.", "embedding_input_too_large")
                batch.append(text)
                batch_tokens += tokens
                offset += 1
            params = {
                "model": profile.deployment, "input": batch, "encoding_format": "float",
            }
            if profile.policy.get("request_dimensions") is not None:
                params["dimensions"] = profile.policy["request_dimensions"]
            delay = initial_delay
            for attempt in range(max_retries + 1):
                try:
                    # Validate wire values before SDK coercion turns booleans/strings into floats.
                    response = client.embeddings.with_raw_response.create(**params)
                    try:
                        payload = response.http_response.json()
                    except ValueError as exc:
                        raise EmbeddingInferenceError(
                            "The embedding service returned invalid JSON.", "embedding_response_invalid",
                        ) from exc
                    results.extend(normalize_embedding_response(payload, len(batch), profile))
                    break
                except RateLimitError as exc:
                    if attempt >= max_retries:
                        log_event("[EMBEDDING] Rate limit retries exhausted", extra={"attempts": attempt + 1})
                        raise EmbeddingInferenceError(
                            "The embedding service is rate limited. Try again later.", "embedding_rate_limited",
                        ) from exc
                    wait = retry_delay(exc, delay) if retry_delay else min(delay, 60.0) * random.uniform(1.0, 1.5)
                    log_event("[EMBEDDING] Waiting before retry", extra={"attempt": attempt + 1, "wait_seconds": wait})
                    time.sleep(wait)
                    delay *= delay_multiplier
                except APIError as exc:
                    log_event(
                        "[EMBEDDING] Inference failed",
                        extra={"error_type": type(exc).__name__, "status_code": getattr(exc, "status_code", None)},
                    )
                    raise EmbeddingInferenceError(
                        "Embedding inference failed. Review the connection, model, and provider access.",
                        "embedding_inference_failed",
                    ) from exc
                except AzureError as exc:
                    log_event("[EMBEDDING] Inference authentication failed", extra={"error_type": type(exc).__name__})
                    raise EmbeddingInferenceError(
                        "Embedding authentication failed. Review the connection identity and permissions.",
                        "embedding_authentication_failed",
                    ) from exc
    return results
