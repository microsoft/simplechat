# functions_model_endpoint_runtime.py
"""Runtime helpers for configured model endpoint clients and Semantic Kernel services."""

from openai import AsyncAzureOpenAI, AsyncOpenAI, AzureOpenAI
from azure.identity import ClientSecretCredential, DefaultAzureCredential, get_bearer_token_provider
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion, OpenAIChatCompletion
import copy
import hashlib
import json
from urllib.parse import quote

from config import cognitive_services_scope
from foundry_agent_runtime import resolve_authority
from functions_model_endpoint_identity_header import build_model_endpoint_identity_headers
from functions_model_endpoint_auth import (
    normalize_custom_endpoint_auth_type,
    resolve_client_certificate,
    resolve_custom_endpoint_credentials,
)
from functions_model_endpoint_providers import (
    get_model_endpoint_provider,
    normalize_custom_endpoint_url_mode,
)
from functions_model_endpoint_types import (
    DEFAULT_ANTHROPIC_VERSION,
    MODEL_ENDPOINT_PROVIDER_CUSTOM,
    get_model_endpoint_api_type,
    resolve_model_endpoint_request_model,
)
from functions_model_endpoint_validation import validate_custom_model_endpoint_url, validate_model_endpoint_routing
from functions_model_endpoint_urls import (
    build_model_endpoint_routing_context,
    model_endpoint_route_cache_key,
    routing_schema_version,
)
from functions_settings import resolve_model_endpoint_foundry_scope
from model_endpoint_clients import (
    MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
    MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
    MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
    AnthropicSemanticKernelChatCompletion,
    build_anthropic_chat_client,
    build_custom_openai_async_http_client,
    build_custom_openai_sync_http_client,
    build_openai_style_chat_client,
    infer_model_endpoint_protocol,
    normalize_custom_openai_base_url,
    resolve_custom_openai_base_url,
    normalize_openai_style_base_url,
    resolve_openai_style_request_api_version,
    SanitizedCustomChatCompletionClient,
    sanitize_custom_async_openai_client,
    bind_model_endpoint_request_policy,
)


MODEL_ENDPOINT_PROVIDER_ALLOWLIST = {
    'aoai',
    'aifoundry',
    'new_foundry',
    'anthropic',
    'claude',
    MODEL_ENDPOINT_PROVIDER_CUSTOM,
}
MODEL_CONTEXT_AUTH_FIELDS = (
    'type',
    'tenant_id',
    'client_id',
    'managed_identity_client_id',
    'management_cloud',
    'foundry_scope',
    'authority',
)


def _build_azure_chat_completion(default_headers=None, **kwargs):
    if not default_headers:
        return AzureChatCompletion(**kwargs)
    try:
        return AzureChatCompletion(default_headers=default_headers, **kwargs)
    except TypeError:
        return AzureChatCompletion(**kwargs)


def sanitize_model_endpoint_auth_for_context(auth_settings):
    """Return non-secret auth metadata that can be persisted with background work."""
    if not isinstance(auth_settings, dict):
        return {}

    sanitized_auth = {}
    for field_name in MODEL_CONTEXT_AUTH_FIELDS:
        field_value = auth_settings.get(field_name)
        if field_value not in (None, ''):
            sanitized_auth[field_name] = field_value
    return sanitized_auth


def build_model_endpoint_context(
    *,
    provider=None,
    endpoint=None,
    auth=None,
    api_version=None,
    api_type=None,
    anthropic_version=None,
    endpoint_id=None,
    model_id=None,
    model_deployment=None,
    request_model=None,
    user_id=None,
    active_group_ids=None,
    routing_schema_version=None,
    scope_type=None,
    scope_id=None,
):
    """Build non-secret model endpoint metadata for downstream helper calls."""
    normalized_user_id = str(user_id or '').strip()
    if routing_schema_version == 2:
        context = build_model_endpoint_routing_context(
            endpoint_id=endpoint_id,
            model_id=model_id,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        if normalized_user_id:
            context['user_id'] = normalized_user_id
        return context

    context = {
        'provider': str(provider or '').strip().lower(),
        'endpoint': str(endpoint or '').strip(),
        'api_version': str(api_version or '').strip(),
        'api_type': str(api_type or '').strip().lower(),
        'anthropic_version': str(anthropic_version or '').strip(),
        'endpoint_id': str(endpoint_id or '').strip(),
        'model_id': str(model_id or '').strip(),
        'model_deployment': str(model_deployment or '').strip(),
        'request_model': str(request_model or model_deployment or '').strip(),
    }

    if normalized_user_id:
        context['user_id'] = normalized_user_id

    normalized_group_ids = [
        str(group_id or '').strip()
        for group_id in (active_group_ids or [])
        if str(group_id or '').strip()
    ]
    if normalized_group_ids:
        context['active_group_ids'] = normalized_group_ids

    sanitized_auth = sanitize_model_endpoint_auth_for_context(auth)
    if sanitized_auth:
        context['auth'] = sanitized_auth

    return {key: value for key, value in context.items() if value not in (None, '', [], {})}


def resolve_foundry_scope_for_endpoint_auth(auth_settings, endpoint=None):
    """Resolve the correct scope for Foundry-backed inference authentication."""
    return resolve_model_endpoint_foundry_scope(auth_settings, endpoint=endpoint)


def resolve_credential_for_model_endpoint_auth(auth_settings):
    """Build an Azure credential for managed-identity or service-principal endpoint auth."""
    auth_settings = auth_settings or {}
    auth_type = str(auth_settings.get('type') or 'managed_identity').lower()
    if auth_type == 'service_principal':
        return ClientSecretCredential(
            tenant_id=auth_settings.get('tenant_id'),
            client_id=auth_settings.get('client_id'),
            client_secret=auth_settings.get('client_secret'),
            authority=resolve_authority(auth_settings),
        )

    managed_identity_client_id = auth_settings.get('managed_identity_client_id') or None
    return DefaultAzureCredential(managed_identity_client_id=managed_identity_client_id)


def _azure_endpoint_from_resolved_route(route):
    """Return the Azure endpoint prefix consumed by AzureOpenAI's deployment URL builder."""
    if not isinstance(route, dict):
        raise ValueError("A resolved Azure deployment route is required.")
    request_model = str(route.get("request_model") or "").strip()
    api_base = str(route.get("api_base") or "").rstrip("/")
    if not request_model or not api_base:
        raise ValueError("Resolved Azure deployment route is incomplete.")
    deployment_suffix = f"/openai/deployments/{quote(request_model, safe='-._~')}"
    if not api_base.endswith(deployment_suffix):
        raise ValueError("Resolved Azure deployment route is invalid.")
    return api_base[:-len(deployment_suffix)]


def build_model_endpoint_sync_chat_client(
    auth_settings,
    provider,
    endpoint,
    api_version,
    deployment_name='',
    *,
    api_type='',
    url_mode='',
    anthropic_version=DEFAULT_ANTHROPIC_VERSION,
    allow_private_custom_endpoints=False,
    allow_insecure_custom_endpoints=False,
    custom_endpoint_ca_bundle_path='',
    settings=None,
    endpoint_config=None,
    identity_context=None,
    resolved_route=None,
):
    """Create a protocol-aware synchronous chat client for a configured model endpoint."""
    if resolved_route is not None:
        if not isinstance(resolved_route, dict) or resolved_route.get("routing_schema_version") != 2:
            raise ValueError("A resolved schema-v2 route is required.")
        api_type = resolved_route.get("api_type") or ""
        deployment_name = resolved_route.get("request_model") or ""
        api_version = resolved_route.get("api_version") or ""
        anthropic_version = resolved_route.get("anthropic_version") or anthropic_version
    auth_settings = auth_settings or {}
    extra_headers = build_model_endpoint_identity_headers(
        settings,
        endpoint_config=endpoint_config,
        identity_context=identity_context,
    )
    normalized_provider = str(provider or 'aoai').strip().lower()
    direct_custom = normalized_provider == MODEL_ENDPOINT_PROVIDER_CUSTOM
    if direct_custom:
        endpoint = validate_custom_model_endpoint_url(
            endpoint,
            allow_private=allow_private_custom_endpoints,
            allow_insecure=allow_insecure_custom_endpoints,
        )
    runtime_protocol = (
        resolved_route.get("protocol")
        if resolved_route is not None
        else infer_model_endpoint_protocol(
            normalized_provider,
            endpoint,
            deployment_name,
            api_type,
        )
    )
    def resolved_client(client):
        return bind_model_endpoint_request_policy(client, resolved_route), runtime_protocol

    client_certificate = resolve_client_certificate(
        (endpoint_config or {}).get("connection", {}) or {}
    ) if direct_custom else None
    operation_url = resolved_route.get("operation_url", "") if resolved_route is not None else ""
    resolved_base_url = resolved_route.get("api_base", "") if resolved_route is not None else ""
    resolved_azure_endpoint = endpoint
    if resolved_route is not None and runtime_protocol == MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI:
        resolved_azure_endpoint = _azure_endpoint_from_resolved_route(resolved_route)
    auth_type = str(auth_settings.get('type') or 'managed_identity').strip().lower()
    credential_is_bearer = False
    if direct_custom:
        normalized_custom_auth = normalize_custom_endpoint_auth_type(auth_type)
        if not normalized_custom_auth:
            raise ValueError(
                'Custom model endpoints support API key, bearer token, or OAuth2 '
                'client credentials authentication.'
            )
        registered_provider = get_model_endpoint_provider(api_type)
        credential, credential_headers = resolve_custom_endpoint_credentials(
            auth_settings,
            default_api_key_header=(
                registered_provider.default_api_key_header if registered_provider else ''
            ),
            default_api_key_prefix=(
                registered_provider.default_api_key_prefix if registered_provider else ''
            ),
            allow_private=allow_private_custom_endpoints,
            allow_insecure=allow_insecure_custom_endpoints,
            ca_bundle_path=custom_endpoint_ca_bundle_path,
        )
        if credential_headers:
            extra_headers = {**(extra_headers or {}), **credential_headers}
        credential_is_bearer = normalized_custom_auth in (
            "bearer",
            "oauth2_client_credentials",
        )
        auth_type = 'api_key'
        auth_settings = {**auth_settings, 'type': 'api_key', 'api_key': credential}

    if auth_type in ('api_key', 'key'):
        api_key = auth_settings.get('api_key')
        if not api_key:
            raise ValueError('Selected model endpoint is missing an API key.')
        if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC:
            return resolved_client(build_anthropic_chat_client(
                endpoint=endpoint,
                api_key="" if credential_is_bearer else api_key,
                bearer_token=api_key if credential_is_bearer else "",
                anthropic_version=anthropic_version,
                direct_custom=direct_custom,
                allow_private_custom_endpoints=allow_private_custom_endpoints,
                custom_endpoint_ca_bundle_path=custom_endpoint_ca_bundle_path,
                extra_headers=extra_headers,
                operation_url=operation_url,
                client_cert=client_certificate,
            ))
        if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE:
            return resolved_client(build_openai_style_chat_client(
                api_key,
                endpoint,
                api_version,
                direct_custom=direct_custom,
                allow_private_custom_endpoints=allow_private_custom_endpoints,
                default_headers=extra_headers,
                api_type=api_type,
                url_mode="exact" if resolved_route is not None else url_mode,
                ca_bundle_path=custom_endpoint_ca_bundle_path,
                resolved_base_url=resolved_base_url,
                request_url=operation_url,
                client_cert=client_certificate,
            ))
        client_kwargs = {
            'api_version': api_version,
            'azure_endpoint': resolved_azure_endpoint,
        }
        if direct_custom and credential_is_bearer:
            client_kwargs['azure_ad_token'] = api_key
        else:
            client_kwargs['api_key'] = api_key
        if extra_headers:
            client_kwargs['default_headers'] = extra_headers
        if direct_custom:
            client_kwargs['http_client'] = build_custom_openai_sync_http_client(
                allow_private=allow_private_custom_endpoints,
                ca_bundle_path=custom_endpoint_ca_bundle_path,
                client_cert=client_certificate,
            )
        client = AzureOpenAI(**client_kwargs)
        if direct_custom:
            client = SanitizedCustomChatCompletionClient(
                client,
                api_type=api_type,
                request_url=operation_url or endpoint,
            )
        return resolved_client(client)

    credential = resolve_credential_for_model_endpoint_auth(auth_settings)
    scope = cognitive_services_scope
    if normalized_provider in ('aifoundry', 'new_foundry', 'anthropic', 'claude') or runtime_protocol != MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI:
        scope = resolve_foundry_scope_for_endpoint_auth(auth_settings, endpoint=endpoint)

    if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC:
        token = credential.get_token(scope).token
        return resolved_client(build_anthropic_chat_client(
            endpoint=endpoint,
            bearer_token=token,
            extra_headers=extra_headers,
            operation_url=operation_url,
            client_cert=client_certificate,
        ))

    if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE:
        token = credential.get_token(scope).token
        return resolved_client(build_openai_style_chat_client(
            token,
            endpoint,
            api_version,
            default_headers=extra_headers,
            resolved_base_url=resolved_base_url,
            request_url=operation_url,
            client_cert=client_certificate,
        ))

    token_provider = get_bearer_token_provider(credential, scope)
    return resolved_client(AzureOpenAI(
        api_version=api_version,
        azure_endpoint=resolved_azure_endpoint,
        azure_ad_token_provider=token_provider,
        default_headers=extra_headers or None,
    ))


def _append_model_endpoint_candidate(endpoints, scope, endpoint):
    if isinstance(endpoint, dict):
        endpoints.append({**endpoint, '_endpoint_scope': scope})


def resolve_authorized_model_endpoint_route(model_context, *, authorize_scope, load_endpoint, settings):
    """Resolve a fresh, authorized selection for opt-in non-agent consumers.

Callbacks must be server-owned and bound to the authenticated actor, never to
identity claims from model_context. authorize_scope must recheck current access
(including group membership) and return True before load_endpoint reads data.
The loader returns (saved endpoint, authoritative configuration revision).
The revision must cover credential, identity-header, transport and routing policy.
Neither callback should resolve secret values; credentials remain a later step.
"""
    if not isinstance(model_context, dict) or routing_schema_version(model_context) != 2:
        raise ValueError("Explicit model routing context is required.")
    context = build_model_endpoint_routing_context(**{
        field: model_context.get(field)
        for field in ("endpoint_id", "model_id", "scope_type", "scope_id")
    })
    scope_type = context["scope_type"]
    policy = settings or {}
    allowed = policy.get("enable_multi_model_endpoints") is True
    if scope_type == "user":
        allowed = allowed and policy.get("allow_user_custom_endpoints") is True
    elif scope_type == "group":
        allowed = allowed and policy.get("allow_group_custom_endpoints") is True
    if not allowed or authorize_scope(scope_type, context["scope_id"]) is not True:
        raise PermissionError("Model endpoint access is not permitted.")
    endpoint, revision = load_endpoint(scope_type, context["scope_id"], context["endpoint_id"])
    if not isinstance(endpoint, dict) or endpoint.get("id") != context["endpoint_id"] or endpoint.get("enabled", True) is not True:
        raise ValueError("The selected endpoint is unavailable.")
    if routing_schema_version(endpoint) != 2:
        raise ValueError("The selected endpoint no longer uses explicit routing.")
    matches = [model for model in endpoint.get("models", []) if isinstance(model, dict) and model.get("id") == context["model_id"]]
    if len(matches) != 1 or matches[0].get("enabled", True) is not True:
        raise ValueError("The selected model is unavailable.")
    routes = validate_model_endpoint_routing(endpoint, policy, require_resolvable=True)
    route = next(route for route in routes if route["model_id"] == context["model_id"])
    cache_key = model_endpoint_route_cache_key(
        route, scope_type=scope_type, scope_id=context["scope_id"], configuration_revision=revision,
    )
    return {"context": context, "route": route, "cache_key": cache_key}


def resolve_model_endpoint_from_context(settings, model_context):
    """Resolve selected endpoint metadata, including secrets, from non-secret model context."""
    from functions_group import assert_group_role, get_group_model_endpoints
    from functions_keyvault import SecretReturnType, keyvault_model_endpoint_get_helper
    from functions_settings import get_user_settings, normalize_model_endpoints

    settings = settings or {}
    model_context = model_context if isinstance(model_context, dict) else {}
    if model_context.get('routing_schema_version') is not None:
        if routing_schema_version(model_context) != 2:
            raise ValueError('Unsupported model endpoint context version.')
        return _resolve_schema_v2_model_endpoint_context(settings, model_context)

    requested_endpoint_id = str(model_context.get('endpoint_id') or '').strip()
    requested_model_id = str(model_context.get('model_id') or '').strip()
    requested_model_name = str(
        model_context.get('request_model')
        or model_context.get('model_deployment')
        or ''
    ).strip()
    requested_provider = str(model_context.get('provider') or '').strip().lower()
    if not settings.get('enable_multi_model_endpoints', False):
        return None
    if not (requested_endpoint_id or requested_model_id or requested_model_name):
        return None

    endpoints = []
    user_id = str(model_context.get('user_id') or '').strip()
    if user_id and settings.get('allow_user_custom_endpoints', False):
        user_settings_doc = get_user_settings(user_id)
        user_settings = user_settings_doc.get('settings', {}) if isinstance(user_settings_doc, dict) else {}
        personal_endpoints, _ = normalize_model_endpoints(user_settings.get('personal_model_endpoints', []) or [])
        for endpoint in personal_endpoints:
            _append_model_endpoint_candidate(endpoints, 'user', endpoint)

    if settings.get('allow_group_custom_endpoints', False):
        seen_group_ids = set()
        for group_id in model_context.get('active_group_ids') or []:
            group_key = str(group_id or '').strip()
            if not group_key or group_key in seen_group_ids:
                continue
            seen_group_ids.add(group_key)
            try:
                assert_group_role(
                    user_id,
                    group_key,
                    allowed_roles=('Owner', 'Admin', 'DocumentManager', 'User'),
                )
                group_endpoints, _ = normalize_model_endpoints(get_group_model_endpoints(group_key) or [])
            except PermissionError:
                continue
            for endpoint in group_endpoints:
                _append_model_endpoint_candidate(endpoints, 'group', endpoint)

    global_endpoints, _ = normalize_model_endpoints(settings.get('model_endpoints', []) or [])
    for endpoint in global_endpoints:
        _append_model_endpoint_candidate(endpoints, 'global', endpoint)

    for endpoint_cfg in endpoints:
        if routing_schema_version(endpoint_cfg) == 2:
            endpoint_matches = (
                requested_endpoint_id
                and str(endpoint_cfg.get('id') or '').strip() == requested_endpoint_id
            )
            models = endpoint_cfg.get('models', []) or []
            model_matches = any(
                isinstance(model, dict)
                and (
                    (requested_model_id and str(model.get('id') or '').strip() == requested_model_id)
                    or (
                        requested_model_name
                        and requested_model_name in {
                            str(model.get(field) or '').strip()
                            for field in ('modelName', 'deploymentName', 'deployment', 'name')
                        }
                    )
                )
                for model in models
            )
            if endpoint_matches or model_matches:
                raise ValueError('An explicit schema-v2 model endpoint context is required.')
            continue
        if not endpoint_cfg.get('enabled', True):
            continue
        if requested_endpoint_id and str(endpoint_cfg.get('id') or '').strip() != requested_endpoint_id:
            continue
        if requested_provider and str(endpoint_cfg.get('provider') or '').strip().lower() not in ('', requested_provider):
            continue

        models = endpoint_cfg.get('models', []) or []
        matched_model = None
        for model_cfg in models:
            if requested_model_id and str(model_cfg.get('id') or '').strip() == requested_model_id:
                matched_model = model_cfg
                break
            request_model = resolve_model_endpoint_request_model(endpoint_cfg, model_cfg)
            if requested_model_name and request_model == requested_model_name:
                matched_model = model_cfg
                break
        if not matched_model or not matched_model.get('enabled', True):
            continue

        endpoint_scope = endpoint_cfg.get('_endpoint_scope', 'global')
        resolved_endpoint_cfg = dict(endpoint_cfg)
        resolved_endpoint_cfg.pop('_endpoint_scope', None)
        return keyvault_model_endpoint_get_helper(
            resolved_endpoint_cfg,
            resolved_endpoint_cfg.get('id') or requested_endpoint_id,
            scope=endpoint_scope,
            return_type=SecretReturnType.VALUE,
        )

    return None


def _resolve_schema_v2_model_endpoint_context(settings, model_context):
    """Reload and authorize a schema-v2 selection before hydrating its secrets."""
    from functions_group import assert_group_role, get_group_model_endpoints
    from functions_governance import ensure_governance_access
    from functions_keyvault import SecretReturnType, keyvault_model_endpoint_get_helper
    from functions_settings import get_user_settings, normalize_model_endpoints

    settings = settings if isinstance(settings, dict) else {}
    user_id = str(model_context.get('user_id') or '').strip()
    if not user_id:
        raise PermissionError('The endpoint owner could not be authorized.')
    context = build_model_endpoint_routing_context(**{
        field: model_context.get(field)
        for field in ('endpoint_id', 'model_id', 'scope_type', 'scope_id')
    })
    scope_type = context['scope_type']
    scope_id = context['scope_id']
    if scope_type == 'user' and scope_id != user_id:
        raise PermissionError('The user endpoint scope is not authorized.')
    if scope_type == 'global' and scope_id != 'global':
        raise ValueError('Invalid global model endpoint scope.')
    scope_flag = {
        'user': 'allow_user_custom_endpoints',
        'group': 'allow_group_custom_endpoints',
    }.get(scope_type)
    if settings.get('enable_multi_model_endpoints') is not True or (
        scope_flag and settings.get(scope_flag) is not True
    ):
        raise PermissionError('Model endpoints are disabled for this scope.')

    loaded_endpoint = {}

    def authorize_scope(requested_scope, requested_scope_id):
        if requested_scope != scope_type or requested_scope_id != scope_id:
            return False
        if requested_scope == 'group':
            assert_group_role(
                user_id,
                requested_scope_id,
                allowed_roles=('Owner', 'Admin', 'DocumentManager', 'User'),
            )
        feature_key = f'governance_{requested_scope}_endpoints'
        ensure_governance_access(feature_key, user_id)
        return True

    def load_endpoint(requested_scope, requested_scope_id, endpoint_id):
        ensure_governance_access(
            f'governance_{requested_scope}_endpoints',
            user_id,
            item_entity_type='global_endpoint',
            item_id=endpoint_id,
        )
        source_revision = ''
        if requested_scope == 'global':
            candidates = settings.get('model_endpoints', []) or []
            source_revision = str(settings.get('_etag') or '')
        elif requested_scope == 'user':
            user_settings_doc = get_user_settings(user_id)
            user_settings = user_settings_doc.get('settings', {}) if isinstance(user_settings_doc, dict) else {}
            candidates = user_settings.get('personal_model_endpoints', []) or []
            source_revision = str(user_settings_doc.get('_etag') or '') if isinstance(user_settings_doc, dict) else ''
        else:
            assert_group_role(
                user_id,
                requested_scope_id,
                allowed_roles=('Owner', 'Admin', 'DocumentManager', 'User'),
            )
            candidates = get_group_model_endpoints(requested_scope_id) or []

        normalized, _ = normalize_model_endpoints(candidates)
        matches = [
            endpoint for endpoint in normalized
            if isinstance(endpoint, dict) and str(endpoint.get('id') or '').strip() == endpoint_id
        ]
        if len(matches) != 1:
            return None, source_revision or 'missing'
        endpoint = matches[0]
        if not source_revision:
            revision_payload = copy.deepcopy(endpoint)
            auth = revision_payload.get('auth')
            if isinstance(auth, dict):
                for secret_field in ('api_key', 'bearer_token', 'client_secret', 'access_token', 'refresh_token'):
                    auth.pop(secret_field, None)
            source_revision = hashlib.sha256(
                json.dumps(revision_payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
            ).hexdigest()
        loaded_endpoint['value'] = copy.deepcopy(endpoint)
        return endpoint, source_revision

    resolved = resolve_authorized_model_endpoint_route(
        context,
        authorize_scope=authorize_scope,
        load_endpoint=load_endpoint,
        settings=settings,
    )
    endpoint = loaded_endpoint.get('value')
    if not isinstance(endpoint, dict):
        raise LookupError('The selected model endpoint could not be found.')
    endpoint = keyvault_model_endpoint_get_helper(
        endpoint,
        context['endpoint_id'],
        scope=scope_type,
        return_type=SecretReturnType.VALUE,
    )
    endpoint['_resolved_route'] = resolved['route']
    endpoint['_route_cache_key'] = resolved['cache_key']
    return endpoint


def build_semantic_kernel_chat_service_for_model(
    gpt_model,
    settings,
    *,
    service_id='chat-model',
    model_context=None,
    resolved_model_endpoint=None,
):
    """Create a Semantic Kernel chat service for the selected model endpoint."""
    settings = settings or {}
    model_context = model_context if isinstance(model_context, dict) else {}
    resolved_model_endpoint = resolved_model_endpoint if isinstance(resolved_model_endpoint, dict) else None
    resolved_route = None

    if resolved_model_endpoint is None and (
        model_context.get('endpoint_id') or model_context.get('model_id')
    ):
        resolved_model_endpoint = resolve_model_endpoint_from_context(settings, model_context)
    if resolved_model_endpoint:
        resolved_route = resolved_model_endpoint.get('_resolved_route')
        if routing_schema_version(resolved_model_endpoint) == 2 and not isinstance(resolved_route, dict):
            raise ValueError('Explicit model routing must be re-resolved before dispatch.')

    def resolved_service(service):
        if resolved_route is not None:
            if isinstance(service, AnthropicSemanticKernelChatCompletion):
                service.resolved_route = copy.deepcopy(resolved_route)
            else:
                bind_model_endpoint_request_policy(service.client, resolved_route)
        return service, runtime_protocol

    provider = str(model_context.get('provider') or '').strip().lower()
    endpoint = str(model_context.get('endpoint') or '').strip()
    api_version = str(model_context.get('api_version') or '').strip()
    api_type = str(model_context.get('api_type') or '').strip().lower()
    url_mode = normalize_custom_endpoint_url_mode(model_context.get('url_mode'))
    anthropic_version = str(
        model_context.get('anthropic_version')
        or DEFAULT_ANTHROPIC_VERSION
    ).strip()
    auth_settings = model_context.get('auth') if isinstance(model_context.get('auth'), dict) else {}
    request_model = str(
        model_context.get('request_model')
        or model_context.get('model_deployment')
        or gpt_model
        or ''
    ).strip()

    if resolved_model_endpoint:
        provider = str(resolved_model_endpoint.get('provider') or provider or 'aoai').strip().lower()
        connection = resolved_model_endpoint.get('connection', {}) or {}
        endpoint = str(connection.get('endpoint') or endpoint).strip()
        api_type = (
            resolved_route.get('api_type')
            if resolved_route
            else get_model_endpoint_api_type(resolved_model_endpoint) or api_type
        )
        url_mode = normalize_custom_endpoint_url_mode(
            (resolved_route.get('url_mode') if resolved_route else connection.get('url_mode') or url_mode)
        )
        api_version = str(
            resolved_route.get('api_version') if resolved_route else (
                connection.get('openai_api_version')
                or connection.get('api_version')
                or api_version
            )
        ).strip()
        anthropic_version = str(
            resolved_route.get('anthropic_version') if resolved_route else (
                connection.get('anthropic_version')
                or anthropic_version
                or DEFAULT_ANTHROPIC_VERSION
            )
        ).strip()
        auth_settings = resolved_model_endpoint.get('auth', {}) or auth_settings
        resolved_models = resolved_model_endpoint.get('models', []) or []
        requested_model_id = str(model_context.get('model_id') or '').strip()
        matched_model = None
        if requested_model_id:
            matched_model = next(
                (model for model in resolved_models if str(model.get('id') or '').strip() == requested_model_id),
                None,
            )
        if matched_model is None and request_model:
            matched_model = next(
                (
                    model for model in resolved_models
                    if resolve_model_endpoint_request_model(
                        resolved_model_endpoint,
                        model,
                    ) == request_model
                ),
                None,
            )
        if matched_model and not resolved_route:
            request_model = resolve_model_endpoint_request_model(
                resolved_model_endpoint,
                matched_model,
            )
        if resolved_route:
            request_model = str(resolved_route.get('request_model') or '').strip()

    if provider and endpoint and request_model:
        direct_custom = provider == MODEL_ENDPOINT_PROVIDER_CUSTOM
        allow_private_custom_endpoints = bool(
            settings.get('allow_private_custom_model_endpoints', False)
        )
        allow_insecure_custom_endpoints = bool(
            settings.get('allow_insecure_custom_model_endpoints', False)
        )
        custom_endpoint_ca_bundle_path = str(
            settings.get('custom_model_endpoint_ca_bundle_path') or ''
        ).strip()
        if direct_custom:
            endpoint = validate_custom_model_endpoint_url(
                endpoint,
                allow_private=allow_private_custom_endpoints,
                allow_insecure=allow_insecure_custom_endpoints,
            )
        runtime_protocol = (
            resolved_route.get('protocol')
            if resolved_route
            else infer_model_endpoint_protocol(
                provider,
                endpoint,
                request_model,
                api_type,
            )
        )
        operation_url = resolved_route.get('operation_url', '') if resolved_route else ''
        resolved_base_url = resolved_route.get('api_base', '') if resolved_route else ''
        resolved_azure_endpoint = (
            _azure_endpoint_from_resolved_route(resolved_route)
            if resolved_route and runtime_protocol == MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI
            else endpoint
        )
        client_certificate = resolve_client_certificate(
            (resolved_model_endpoint or {}).get('connection', {}) or {}
        ) if direct_custom else None
        auth_type = str(auth_settings.get('type') or 'managed_identity').lower()
        extra_headers = build_model_endpoint_identity_headers(
            settings,
            endpoint_config=resolved_model_endpoint,
            identity_context=model_context,
        )
        credential_is_bearer = False
        if direct_custom:
            normalized_custom_auth = normalize_custom_endpoint_auth_type(auth_type)
            if not normalized_custom_auth:
                raise ValueError(
                    'Custom model endpoints support API key, bearer token, or OAuth2 '
                    'client credentials authentication.'
                )
            registered_provider = get_model_endpoint_provider(api_type)
            credential, credential_headers = resolve_custom_endpoint_credentials(
                auth_settings,
                default_api_key_header=(
                    registered_provider.default_api_key_header if registered_provider else ''
                ),
                default_api_key_prefix=(
                    registered_provider.default_api_key_prefix if registered_provider else ''
                ),
                allow_private=allow_private_custom_endpoints,
                allow_insecure=allow_insecure_custom_endpoints,
                ca_bundle_path=custom_endpoint_ca_bundle_path,
            )
            if credential_headers:
                extra_headers = {**(extra_headers or {}), **credential_headers}
            credential_is_bearer = normalized_custom_auth in (
                'bearer',
                'oauth2_client_credentials',
            )
            auth_type = 'api_key'
            auth_settings = {**auth_settings, 'type': 'api_key', 'api_key': credential}

        if auth_type in ('api_key', 'key'):
            api_key = auth_settings.get('api_key')
            if not api_key:
                raise ValueError('Selected model endpoint is missing an API key.')
            if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC:
                return resolved_service(AnthropicSemanticKernelChatCompletion(
                    service_id=service_id,
                    deployment_name=request_model,
                    endpoint=endpoint,
                    operation_url=operation_url,
                    api_key='' if credential_is_bearer else api_key,
                    bearer_token=api_key if credential_is_bearer else '',
                    anthropic_version=anthropic_version,
                    direct_custom=direct_custom,
                    allow_private_custom_endpoints=allow_private_custom_endpoints,
                    custom_endpoint_ca_bundle_path=custom_endpoint_ca_bundle_path,
                    extra_headers=extra_headers,
                    client_cert=client_certificate,
                ))
            if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE:
                request_api_version = resolve_openai_style_request_api_version(api_version)
                client_kwargs = {
                    'api_key': api_key,
                    'base_url': resolved_base_url or (
                        resolve_custom_openai_base_url(endpoint, api_type, url_mode)
                        if direct_custom
                        else normalize_openai_style_base_url(endpoint)
                    ),
                }
                if direct_custom:
                    client_kwargs['http_client'] = build_custom_openai_async_http_client(
                        allow_private=allow_private_custom_endpoints,
                        ca_bundle_path=custom_endpoint_ca_bundle_path,
                        client_cert=client_certificate,
                    )
                if extra_headers:
                    client_kwargs['default_headers'] = extra_headers
                if request_api_version:
                    client_kwargs['default_query'] = {'api-version': request_api_version}
                async_client = AsyncOpenAI(**client_kwargs)
                if direct_custom:
                    async_client = sanitize_custom_async_openai_client(
                        async_client,
                        api_type=api_type,
                        request_url=operation_url or client_kwargs['base_url'],
                    )
                return resolved_service(OpenAIChatCompletion(
                    service_id=service_id,
                    ai_model_id=request_model,
                    async_client=async_client,
                ))
            if direct_custom:
                client_kwargs = {
                    'api_version': api_version,
                    'azure_endpoint': resolved_azure_endpoint,
                    'default_headers': extra_headers or None,
                    'http_client': build_custom_openai_async_http_client(
                        allow_private=allow_private_custom_endpoints,
                        ca_bundle_path=custom_endpoint_ca_bundle_path,
                        client_cert=client_certificate,
                    ),
                }
                if credential_is_bearer:
                    client_kwargs['azure_ad_token'] = api_key
                else:
                    client_kwargs['api_key'] = api_key
                async_client = AsyncAzureOpenAI(**client_kwargs)
                async_client = sanitize_custom_async_openai_client(
                    async_client,
                    api_type=api_type,
                    request_url=operation_url or endpoint,
                )
                return resolved_service(AzureChatCompletion(
                    service_id=service_id,
                    deployment_name=request_model,
                    async_client=async_client,
                ))
            return resolved_service(_build_azure_chat_completion(
                service_id=service_id,
                deployment_name=request_model,
                endpoint=resolved_azure_endpoint,
                api_key=api_key,
                api_version=api_version,
                default_headers=extra_headers,
            ))

        credential = resolve_credential_for_model_endpoint_auth(auth_settings)
        scope = cognitive_services_scope
        if provider in ('aifoundry', 'new_foundry', 'anthropic', 'claude') or runtime_protocol != MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI:
            scope = resolve_foundry_scope_for_endpoint_auth(auth_settings, endpoint=endpoint)

        if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC:
            token = credential.get_token(scope).token
            return resolved_service(AnthropicSemanticKernelChatCompletion(
                service_id=service_id,
                deployment_name=request_model,
                endpoint=endpoint,
                bearer_token=token,
                extra_headers=extra_headers,
                operation_url=operation_url,
                client_cert=client_certificate,
            ))

        if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE:
            token = credential.get_token(scope).token
            request_api_version = resolve_openai_style_request_api_version(api_version)
            client_kwargs = {
                'api_key': token,
                'base_url': resolved_base_url or normalize_openai_style_base_url(endpoint),
            }
            if extra_headers:
                client_kwargs['default_headers'] = extra_headers
            if request_api_version:
                client_kwargs['default_query'] = {'api-version': request_api_version}
            return resolved_service(OpenAIChatCompletion(
                service_id=service_id,
                ai_model_id=request_model,
                async_client=AsyncOpenAI(**client_kwargs),
            ))

        token_provider = get_bearer_token_provider(credential, scope)
        try:
            return resolved_service(_build_azure_chat_completion(
                service_id=service_id,
                deployment_name=request_model,
                endpoint=resolved_azure_endpoint,
                api_version=api_version,
                azure_ad_token_provider=token_provider,
                default_headers=extra_headers,
            ))
        except TypeError:
            return resolved_service(_build_azure_chat_completion(
                service_id=service_id,
                deployment_name=request_model,
                endpoint=resolved_azure_endpoint,
                api_version=api_version,
                ad_token_provider=token_provider,
                default_headers=extra_headers,
            ))

    extra_headers = build_model_endpoint_identity_headers(settings, identity_context=model_context)
    enable_gpt_apim = settings.get('enable_gpt_apim', False)
    if enable_gpt_apim:
        return _build_azure_chat_completion(
            service_id=service_id,
            deployment_name=gpt_model,
            endpoint=settings.get('azure_apim_gpt_endpoint'),
            api_key=settings.get('azure_apim_gpt_subscription_key'),
            api_version=settings.get('azure_apim_gpt_api_version'),
            default_headers=extra_headers,
        ), MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI

    auth_type = settings.get('azure_openai_gpt_authentication_type')
    if auth_type == 'managed_identity':
        token_provider = get_bearer_token_provider(DefaultAzureCredential(), cognitive_services_scope)
        try:
            return _build_azure_chat_completion(
                service_id=service_id,
                deployment_name=gpt_model,
                endpoint=settings.get('azure_openai_gpt_endpoint'),
                api_version=settings.get('azure_openai_gpt_api_version'),
                azure_ad_token_provider=token_provider,
                default_headers=extra_headers,
            ), MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI
        except TypeError:
            return _build_azure_chat_completion(
                service_id=service_id,
                deployment_name=gpt_model,
                endpoint=settings.get('azure_openai_gpt_endpoint'),
                api_version=settings.get('azure_openai_gpt_api_version'),
                ad_token_provider=token_provider,
                default_headers=extra_headers,
            ), MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI

    return _build_azure_chat_completion(
        service_id=service_id,
        deployment_name=gpt_model,
        endpoint=settings.get('azure_openai_gpt_endpoint'),
        api_key=settings.get('azure_openai_gpt_key'),
        api_version=settings.get('azure_openai_gpt_api_version'),
        default_headers=extra_headers,
    ), MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI
