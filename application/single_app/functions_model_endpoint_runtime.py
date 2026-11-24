# functions_model_endpoint_runtime.py
"""Runtime helpers for configured model endpoint clients and Semantic Kernel services."""

from openai import AsyncAzureOpenAI, AsyncOpenAI, AzureOpenAI, OpenAI
from azure.identity import ClientSecretCredential, DefaultAzureCredential, get_bearer_token_provider
from model_tool_chat_completion import (
    AzureToolChatCompletion as AzureChatCompletion,
    OpenAIToolChatCompletion as OpenAIChatCompletion,
)
import copy
import hashlib
import json
from urllib.parse import quote

from config import cognitive_services_scope
from foundry_agent_runtime import resolve_authority
from functions_ai_connections import (
    AIConnectionError,
    register_capability_client_factory,
    require_model_capability,
)
from functions_model_endpoint_identity_header import build_model_endpoint_identity_headers
from functions_model_capabilities import resolve_model_token_budget
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
from functions_model_endpoint_validation import (
    CUSTOM_ENDPOINT_VERSION_PATTERN,
    ModelEndpointValidationError,
    custom_endpoint_setting_enabled,
    endpoint_uses_mai_chat_completions,
    validate_custom_model_endpoint_url,
    validate_model_endpoint_api_version,
    validate_model_endpoint_routing,
    model_endpoint_inference_api,
)
from functions_model_persona import active_model_persona_markdown
from functions_model_endpoint_urls import (
    build_model_endpoint_routing_context,
    model_endpoint_route_cache_key,
    routing_schema_version,
)
from functions_settings import resolve_model_endpoint_foundry_scope
from functions_tabular_model_diagnostics import build_tabular_model_http_options
from model_endpoint_ca_bundles import normalize_ca_bundle_reference
from model_endpoint_profiles import GENAI_MIL_PROFILE, get_custom_endpoint_profile
from model_endpoint_clients import (
    AUXILIARY_MODEL_CALL_TIMEOUT_SECONDS,
    DEFAULT_DOCUMENT_ACTION_TIMEOUT_SECONDS,
    DEFAULT_MODEL_CALL_MAX_RETRIES,
    DEFAULT_MODEL_STREAM_READ_TIMEOUT_SECONDS,
    DEFAULT_STREAM_DISCONNECT_GRACE_SECONDS,
    MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
    MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
    MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
    AnthropicSemanticKernelChatCompletion,
    CustomAnthropicChatCompletionClient,
    OpenAIStyleChatCompletionClient,
    SanitizedCustomChatCompletionClient,
    bind_callable_with_timeout,
    bind_model_endpoint_request_policy,
    build_anthropic_chat_client,
    build_openai_client_timeout,
    build_openai_client_timeout_options,
    build_openai_style_chat_client,
    build_custom_openai_async_http_client,
    build_custom_openai_sync_http_client,
    infer_model_endpoint_protocol,
    normalize_openai_style_base_url,
    resolve_model_inference_endpoint,
    resolve_document_action_timeout_seconds,
    resolve_model_call_max_retries,
    resolve_model_stream_read_timeout_seconds,
    resolve_openai_style_request_api_version,
    resolve_custom_azure_openai_base_url,
    resolve_custom_openai_base_url,
    resolve_stream_disconnect_grace_seconds,
    sanitize_custom_async_openai_client,
)


MODEL_ENDPOINT_PROVIDER_ALLOWLIST = {'aoai', 'aifoundry', 'new_foundry', 'anthropic', 'claude', 'custom'}
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
    validate_model_endpoint_api_version("aoai", kwargs.get("endpoint"), kwargs.get("api_version"))
    diagnostic_options = build_tabular_model_http_options(kwargs.get('service_id'))
    if diagnostic_options:
        client = AsyncAzureOpenAI(
            azure_endpoint=kwargs.get('endpoint'),
            azure_deployment=kwargs.get('deployment_name'),
            api_version=kwargs.get('api_version'),
            api_key=kwargs.get('api_key'),
            azure_ad_token=kwargs.get('ad_token'),
            azure_ad_token_provider=kwargs.get('azure_ad_token_provider') or kwargs.get('ad_token_provider'),
            default_headers=default_headers,
            **diagnostic_options,
        )
        service_options = dict(kwargs)
        service_options.pop('azure_ad_token_provider', None)
        return AzureChatCompletion(async_client=client, **service_options)
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
    apply_model_persona=True,
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
        if apply_model_persona is False:
            context['apply_model_persona'] = False
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
    if str(scope_type or '').strip():
        context['scope_type'] = str(scope_type).strip()
    if str(scope_id or '').strip():
        context['scope_id'] = str(scope_id).strip()

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
    if apply_model_persona is False:
        context['apply_model_persona'] = False

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
    """Return the endpoint prefix consumed by Azure OpenAI's deployment builder."""
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


def _require_chat_model_for_endpoint(endpoint_config, deployment_name='', model_id=''):
    """Validate stored model metadata before considering a legacy deployment alias."""
    if isinstance(endpoint_config, dict):
        if endpoint_config.get('enabled') is False:
            raise AIConnectionError('The selected chat connection is disabled.')
        provider = endpoint_config.get('provider') or 'aoai'
        models = [model for model in endpoint_config.get('models') or [] if isinstance(model, dict)]
        if not model_id and deployment_name:
            deployment_matches = [
                model for model in models
                if str(deployment_name).strip() == resolve_model_endpoint_request_model(endpoint_config, model)
                or str(deployment_name).strip() in {
                    str(model.get(field) or '').strip() for field in ('deploymentName', 'deployment')
                }
            ]
            models = deployment_matches or models
        for model in models:
            if model_id:
                matches = str(model.get('id') or model.get('deploymentName') or '').strip() == str(model_id).strip()
            elif provider == 'custom':
                matches = bool(deployment_name) and str(deployment_name).strip() == resolve_model_endpoint_request_model(endpoint_config, model)
            else:
                matches = bool(deployment_name) and str(deployment_name).strip() in {
                    str(model.get(field) or '').strip()
                    for field in ('deploymentName', 'deployment', 'modelName', 'name', 'id')
                }
            if matches:
                return require_model_capability(model, provider=provider)
        if model_id or ('models' in endpoint_config and deployment_name):
            raise AIConnectionError('The selected chat model is not available on this connection.')
    if deployment_name:
        require_model_capability(deployment_name)
    return None


def _resolve_custom_endpoint_runtime_options(
    endpoint_config, settings, *, resolved_route=None
):
    if not isinstance(endpoint_config, dict) or endpoint_config.get('provider') != 'custom':
        raise ModelEndpointValidationError('A configured Custom endpoint is required.')
    descriptor = get_model_endpoint_provider(
        (resolved_route or {}).get("api_type")
        or get_model_endpoint_api_type(endpoint_config)
    )
    if descriptor is None:
        raise ModelEndpointValidationError('Custom endpoint API type is not supported.')
    settings = settings or {}
    connection = endpoint_config.get('connection') or {}
    # Deferred because the settings owner is also a runtime consumer of this module.
    from functions_settings import resolve_model_endpoint_ca_trust

    ca_bundle_path = resolve_model_endpoint_ca_trust(
        endpoint_config,
        settings,
        str(settings.get('custom_model_endpoint_ca_bundle_path') or '').strip(),
    )
    transport_options = {
        'allow_private': custom_endpoint_setting_enabled(settings, 'allow_private_custom_model_endpoints'),
        'allow_insecure': custom_endpoint_setting_enabled(settings, 'allow_insecure_custom_model_endpoints'),
        'ca_bundle_path': ca_bundle_path,
        'client_cert': resolve_client_certificate(connection),
    }
    endpoint = validate_custom_model_endpoint_url(
        connection.get('endpoint'),
        allow_private=transport_options['allow_private'],
        allow_insecure=transport_options['allow_insecure'],
    )
    if descriptor.version_field:
        version = (
            (resolved_route or {}).get(descriptor.version_field)
            or connection.get(descriptor.version_field)
            or descriptor.default_version
        )
        if descriptor.requires_api_version or version:
            if not CUSTOM_ENDPOINT_VERSION_PATTERN.fullmatch(str(version or '')):
                raise ModelEndpointValidationError('The configured Custom API version is invalid.')
    credential, headers = resolve_custom_endpoint_credentials(
        endpoint_config.get('auth') or {},
        default_api_key_header=descriptor.default_api_key_header,
        default_api_key_prefix=descriptor.default_api_key_prefix,
        **transport_options,
    )
    return descriptor, endpoint, credential, headers, transport_options


def build_custom_openai_client_kwargs(
    endpoint_config, settings, *, request_model='', asynchronous=False,
    default_headers=None, resolved_route=None,
):
    """Build guarded SDK options reusable by chat, Images, and Responses adapters.

    This constructs transport/auth options only; callers must first enforce their
    operation's model capability and publication policy. It never grants image
    support based on an OpenAI-compatible protocol.
    """
    descriptor, endpoint, credential, headers, transport_options = _resolve_custom_endpoint_runtime_options(
        endpoint_config, settings, resolved_route=resolved_route,
    )
    connection = endpoint_config.get('connection') or {}
    if resolved_route is not None:
        base_url = resolved_route.get('api_base')
        if not isinstance(base_url, str) or not base_url.strip():
            raise ModelEndpointValidationError(
                'The resolved Custom endpoint API base is unavailable.'
            )
    elif descriptor.protocol == MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI:
        base_url = resolve_custom_azure_openai_base_url(endpoint, request_model, connection.get('url_mode'))
    elif descriptor.protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE:
        base_url = resolve_custom_openai_base_url(endpoint, descriptor.api_type, connection.get('url_mode'))
    else:
        raise ModelEndpointValidationError('This Custom API type does not support the OpenAI SDK.')
    merged_headers = {name.lower(): value for name, value in (default_headers or {}).items()}
    merged_headers.update({name.lower(): value for name, value in headers.items()})
    if 'authorization' in merged_headers:
        # The SDK merges its defaults case-sensitively before HTTPX folds names.
        # Match the SDK spelling to replace, rather than duplicate, its header.
        merged_headers['Authorization'] = merged_headers.pop('authorization')
    factory = build_custom_openai_async_http_client if asynchronous else build_custom_openai_sync_http_client
    kwargs = {
        'api_key': credential,
        'base_url': base_url,
        'default_headers': merged_headers,
        'http_client': factory(**transport_options),
        **build_openai_client_timeout_options(settings),
    }
    if descriptor.protocol == MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI:
        kwargs['default_query'] = {
            'api-version': (
                (resolved_route or {}).get('api_version')
                or connection.get('api_version')
            )
        }
    if get_custom_endpoint_profile(endpoint_config) == GENAI_MIL_PROFILE:
        kwargs['max_retries'] = 0
    return kwargs


def _build_custom_anthropic_client(
    endpoint_config, settings, extra_headers, *, resolved_route=None
):
    descriptor, endpoint, _, headers, transport_options = _resolve_custom_endpoint_runtime_options(
        endpoint_config, settings, resolved_route=resolved_route,
    )
    connection = endpoint_config.get('connection') or {}
    merged_headers = {name.lower(): value for name, value in (extra_headers or {}).items()}
    merged_headers.update({name.lower(): value for name, value in headers.items()})
    return CustomAnthropicChatCompletionClient(
        endpoint=endpoint, auth_headers=merged_headers,
        anthropic_version=(
            (resolved_route or {}).get('anthropic_version')
            or connection.get('anthropic_version')
            or descriptor.default_version
        ),
        url_mode='exact' if resolved_route is not None else (connection.get('url_mode') or 'auto'),
        operation_url=(resolved_route or {}).get('operation_url'),
        timeout=resolve_model_stream_read_timeout_seconds(settings),
        **transport_options,
    )


def build_model_endpoint_sync_chat_client(
    auth_settings,
    provider,
    endpoint,
    api_version,
    deployment_name='',
    *,
    api_type='',
    model_id='',
    url_mode='',
    anthropic_version=DEFAULT_ANTHROPIC_VERSION,
    allow_private_custom_endpoints=False,
    allow_insecure_custom_endpoints=False,
    custom_endpoint_ca_bundle_path='',
    settings=None,
    endpoint_config=None,
    identity_context=None,
    use_responses_api=None,
    resolved_route=None,
    apply_model_persona=True,
):
    """Create a synchronous client using canonical metadata for its wire protocol.

    ``model_id`` disambiguates stored records sharing a deployment alias. The
    caller's deployment name remains the provider request target; name-only
    legacy calls retain deployment-based inference.
    """
    if resolved_route is not None and (
        not isinstance(resolved_route, dict)
        or resolved_route.get("routing_schema_version") != 2
    ):
        raise ValueError("A resolved schema-v2 model route is required.")
    resolved_model_id = str(
        model_id
        or (resolved_route or {}).get("model_id")
        or ""
    ).strip()
    model = _require_chat_model_for_endpoint(
        endpoint_config, deployment_name, resolved_model_id
    ) or {}
    has_exact_model_identity = bool(
        resolved_model_id
        and str(model.get("id") or "").strip() == resolved_model_id
    )
    persona_markdown = (
        active_model_persona_markdown(model)
        if apply_model_persona and has_exact_model_identity
        else ""
    )
    if resolved_route is not None:
        api_type = resolved_route.get("api_type") or ""
        deployment_name = resolved_route.get("request_model") or ""
        api_version = resolved_route.get("api_version") or ""
        anthropic_version = (
            resolved_route.get("anthropic_version") or anthropic_version
        )
    auth_settings = auth_settings or {}
    extra_headers = build_model_endpoint_identity_headers(
        settings,
        endpoint_config=endpoint_config,
        identity_context=identity_context,
    )
    normalized_provider = str(provider or 'aoai').strip().lower()
    api_type = (
        resolved_route.get("api_type")
        if resolved_route is not None
        else get_model_endpoint_api_type(endpoint_config) or api_type
    )
    model_name = model.get('catalogModelId') or model.get('modelName') or model.get('behavior_name') or deployment_name
    request_policy_model = model.get('catalogModelId') or model_name
    connection = (endpoint_config or {}).get('connection') or {}
    if use_responses_api is None:
        use_responses_api = (
            resolved_route.get("inference_api") == "responses"
            if resolved_route is not None
            else connection.get('use_responses_api')
        )
    if resolved_route is None:
        validate_model_endpoint_api_version(
            normalized_provider, endpoint, api_version, api_type,
            use_responses_api=use_responses_api,
            model=model or deployment_name,
        )
        endpoint = resolve_model_inference_endpoint(
            endpoint, use_responses_api=use_responses_api,
            provider=normalized_provider, api_type=api_type,
            url_mode=connection.get('url_mode'),
            model=model or deployment_name,
        )
    runtime_protocol = (
        resolved_route.get("protocol")
        if resolved_route is not None
        else infer_model_endpoint_protocol(
            normalized_provider, endpoint, model_name, api_type
        )
    )
    inference_endpoint = (
        resolved_route.get("operation_url")
        if resolved_route is not None
        else endpoint
    )

    def finalize(client):
        bound_client = bind_model_endpoint_request_policy(
            client,
            resolved_route,
            persona_markdown=persona_markdown,
        )
        if persona_markdown:
            bound_client._simplechat_model_persona_metadata = {
                key: copy.deepcopy(value)
                for key, value in model.items()
                if key not in ("persona_markdown", "persona_enabled", "persona_text_visible")
            }
        return bound_client, runtime_protocol
    if normalized_provider == 'custom':
        connection = dict((endpoint_config or {}).get('connection') or {})
        connection.update(endpoint=connection.get('endpoint') or endpoint, api_version=connection.get('api_version') or api_version)
        if url_mode and not connection.get('url_mode'):
            connection['url_mode'] = url_mode
        if anthropic_version and not connection.get('anthropic_version'):
            connection['anthropic_version'] = anthropic_version
        custom_settings = settings
        if custom_settings is None:
            custom_settings = {
                'allow_private_custom_model_endpoints': allow_private_custom_endpoints is True,
                'allow_insecure_custom_model_endpoints': allow_insecure_custom_endpoints is True,
                'custom_model_endpoint_ca_bundle_path': custom_endpoint_ca_bundle_path,
            }
        custom_config = {
            **(endpoint_config or {}), 'provider': 'custom', 'api_type': api_type,
            'connection': connection, 'auth': auth_settings,
        }
        if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC:
            return finalize(_build_custom_anthropic_client(
                custom_config,
                custom_settings,
                extra_headers,
                resolved_route=resolved_route,
            ))
        kwargs = build_custom_openai_client_kwargs(
            custom_config,
            custom_settings,
            request_model=deployment_name,
            default_headers=extra_headers,
            resolved_route=resolved_route,
        )
        return finalize(OpenAIStyleChatCompletionClient(
            OpenAI(**kwargs),
            sanitize_errors=True,
            api_type=api_type,
            request_url=inference_endpoint,
            inference_api=(
                resolved_route.get("inference_api")
                if resolved_route is not None
                else model_endpoint_inference_api(endpoint, use_responses_api, provider=normalized_provider, model=model or deployment_name)
            ),
            model_name=request_policy_model,
            custom_profile=get_custom_endpoint_profile(custom_config),
        ))
    auth_type = str(auth_settings.get('type') or 'managed_identity').strip().lower()
    timeout_options = globals().get('build_openai_client_timeout_options', lambda *_a, **_k: {})(settings)

    if auth_type in ('api_key', 'key'):
        api_key = auth_settings.get('api_key')
        if not api_key:
            raise ValueError('Selected model endpoint is missing an API key.')
        if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC:
            return finalize(build_anthropic_chat_client(
                endpoint=inference_endpoint,
                api_key=api_key,
                extra_headers=extra_headers,
            ))
        if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE:
            if auth_settings.get('api_key_header') or endpoint_uses_mai_chat_completions(endpoint):
                api_key, auth_headers = resolve_custom_endpoint_credentials(
                    auth_settings, default_api_key_header='api-key', default_api_key_prefix='',
                )
                extra_headers = {**extra_headers, **auth_headers}
            return finalize(build_openai_style_chat_client(
                api_key,
                inference_endpoint,
                api_version,
                default_headers=extra_headers,
                model_name=request_policy_model,
            ))
        return finalize(AzureOpenAI(
            api_version=api_version,
            azure_endpoint=(
                _azure_endpoint_from_resolved_route(resolved_route)
                if resolved_route is not None
                else endpoint
            ),
            api_key=api_key,
            default_headers=extra_headers or None,
            **timeout_options,
        ))


    credential = resolve_credential_for_model_endpoint_auth(auth_settings)
    scope = cognitive_services_scope
    if normalized_provider in ('aifoundry', 'new_foundry', 'anthropic', 'claude') or runtime_protocol != MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI:
        scope = resolve_foundry_scope_for_endpoint_auth(auth_settings, endpoint=endpoint)

    if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC:
        token = credential.get_token(scope).token
        return finalize(build_anthropic_chat_client(
            endpoint=inference_endpoint,
            bearer_token=token,
            extra_headers=extra_headers,
        ))

    if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE:
        token = credential.get_token(scope).token
        return finalize(build_openai_style_chat_client(
            token,
            inference_endpoint,
            api_version,
            default_headers=extra_headers,
            model_name=request_policy_model,
        ))

    token_provider = get_bearer_token_provider(credential, scope)
    return finalize(AzureOpenAI(
        api_version=api_version,
        azure_endpoint=(
            _azure_endpoint_from_resolved_route(resolved_route)
            if resolved_route is not None
            else endpoint
        ),
        azure_ad_token_provider=token_provider,
        default_headers=extra_headers or None,
        **timeout_options,
    ))


def build_legacy_chat_client(
    settings, deployment_name, *, use_apim=False, identity_context=None, prefer_api_key=False,
):
    """Keep legacy auth and gateway headers while sharing the selected chat transport."""
    prefix = 'azure_apim_gpt' if use_apim else 'azure_openai_gpt'
    api_key = settings.get('azure_apim_gpt_subscription_key' if use_apim else 'azure_openai_gpt_key')
    auth_type = 'api_key' if use_apim else str(settings.get('azure_openai_gpt_authentication_type') or 'key').strip().lower()
    if prefer_api_key and api_key:
        auth_type = 'api_key'
    auth = {
        'type': auth_type, 'api_key': api_key,
        'tenant_id': settings.get('azure_openai_gpt_tenant_id') or settings.get('azure_openai_tenant_id'),
        'client_id': settings.get('azure_openai_gpt_client_id') or settings.get('azure_openai_client_id'),
        'client_secret': settings.get('azure_openai_gpt_client_secret') or settings.get('azure_openai_client_secret'),
        'managed_identity_client_id': settings.get('azure_openai_gpt_managed_identity_client_id') or settings.get('azure_openai_managed_identity_client_id'),
        'management_cloud': settings.get('management_cloud') or settings.get('azure_management_cloud') or 'public',
        'custom_authority': settings.get('custom_authority') or settings.get('azure_custom_authority') or '',
    }
    if auth_type in ('api_key', 'key'):
        auth['api_key_header'] = 'api-key'
    client, _ = build_model_endpoint_sync_chat_client(
        auth, 'aoai', settings.get(f'{prefix}_endpoint'), settings.get(f'{prefix}_api_version'),
        deployment_name=deployment_name, settings=settings, identity_context=identity_context,
        use_responses_api=settings.get(f'{prefix}_use_responses_api'),
    )
    return client


def build_chat_connection_client(binding, settings, *, strict_credentials=False):
    """Adapt a chat binding, optionally requiring stored credentials to resolve.

    Strict hydration is opt-in so existing consumers retain legacy Key Vault
    fallback semantics. Neither mode changes the selected connection or model.
    """
    # Credential hydration stays at the operation boundary, not in the pure binding module.
    from functions_keyvault import SecretReturnType, keyvault_model_endpoint_get_helper

    if binding.capability != 'chat':
        raise AIConnectionError('This connection binding is not configured for chat.')
    endpoint_config = binding.endpoint
    provider = endpoint_config.get('provider') or 'aoai'
    model = require_model_capability(binding.model, provider=provider)
    deployment_name = resolve_model_endpoint_request_model(endpoint_config, model)
    if not deployment_name:
        raise AIConnectionError('The selected chat model is missing its request identifier.')
    model_id = binding.selection.get('model_id') or model.get('id') or ''
    _require_chat_model_for_endpoint(endpoint_config, deployment_name, model_id)
    try:
        endpoint_config = keyvault_model_endpoint_get_helper(
            endpoint_config,
            endpoint_config.get('id') or binding.selection.get('endpoint_id'),
            scope='global',
            return_type=SecretReturnType.VALUE,
            **({'strict': True} if strict_credentials else {}),
        )
    except Exception:
        if not strict_credentials:
            raise
        raise AIConnectionError(
            'The selected model endpoint credential is unavailable.',
            'model_configuration_unavailable',
        ) from None
    connection = endpoint_config.get('connection') or {}
    resolved_route = None
    if routing_schema_version(endpoint_config) == 2:
        resolved_route = next(
            (
                route for route in validate_model_endpoint_routing(
                    endpoint_config, settings, require_resolvable=True
                )
                if route["model_id"] == model_id
            ),
            None,
        )
        if resolved_route is None:
            raise AIConnectionError(
                "The selected chat model route is unavailable."
            )
    client, _ = build_model_endpoint_sync_chat_client(
        endpoint_config.get('auth') or {},
        provider,
        connection.get('endpoint'),
        connection.get('openai_api_version') or connection.get('api_version'),
        deployment_name=deployment_name,
        api_type=(
            resolved_route.get("api_type")
            if resolved_route
            else get_model_endpoint_api_type(endpoint_config)
        ),
        url_mode=connection.get('url_mode', ''),
        anthropic_version=connection.get('anthropic_version') or DEFAULT_ANTHROPIC_VERSION,
        allow_private_custom_endpoints=bool(settings.get('allow_private_custom_model_endpoints', False)),
        allow_insecure_custom_endpoints=bool(settings.get('allow_insecure_custom_model_endpoints', False)),
        custom_endpoint_ca_bundle_path=str(settings.get('custom_model_endpoint_ca_bundle_path') or '').strip(),
        settings=settings,
        endpoint_config=endpoint_config,
        model_id=model_id,
        resolved_route=resolved_route,
    )
    return client


register_capability_client_factory('chat', build_chat_connection_client)


def _append_model_endpoint_candidate(endpoints, scope, endpoint, scope_id=''):
    if isinstance(endpoint, dict):
        endpoints.append({
            **endpoint,
            '_endpoint_scope': scope,
            '_endpoint_scope_id': str(scope_id or '').strip(),
        })


def resolve_authorized_model_endpoint_route(
    model_context, *, authorize_scope, load_endpoint, settings
):
    """Resolve a fresh, authorized schema-v2 route without hydrating secrets."""
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

    endpoint, revision = load_endpoint(
        scope_type, context["scope_id"], context["endpoint_id"]
    )
    if (
        not isinstance(endpoint, dict)
        or endpoint.get("id") != context["endpoint_id"]
        or endpoint.get("enabled", True) is not True
    ):
        raise ValueError("The selected endpoint is unavailable.")
    if routing_schema_version(endpoint) != 2:
        raise ValueError("The selected endpoint no longer uses explicit routing.")
    matches = [
        model for model in endpoint.get("models", [])
        if isinstance(model, dict) and model.get("id") == context["model_id"]
    ]
    if len(matches) != 1 or matches[0].get("enabled", True) is not True:
        raise ValueError("The selected model is unavailable.")

    routes = validate_model_endpoint_routing(
        endpoint, policy, require_resolvable=True
    )
    route = next(
        route for route in routes if route["model_id"] == context["model_id"]
    )
    _, bundle_id = normalize_ca_bundle_reference(
        endpoint.get("connection") or {}
    )
    if bundle_id:
        # Only managed-CA routes need the settings storage registry.
        from functions_settings import get_model_endpoint_ca_bundle_registry

        route["ca_bundle"] = get_model_endpoint_ca_bundle_registry(
            policy
        ).revision_token(bundle_id)
    cache_key = model_endpoint_route_cache_key(
        route,
        scope_type=scope_type,
        scope_id=context["scope_id"],
        configuration_revision=str(revision or "missing"),
    )
    return {"context": context, "route": route, "cache_key": cache_key}


def _resolve_schema_v2_model_endpoint_context(settings, model_context):
    """Reload and authorize a schema-v2 selection before hydrating its secrets."""
    from functions_group import assert_group_role, get_group_model_endpoints
    from functions_governance import ensure_governance_access
    from functions_keyvault import SecretReturnType, keyvault_model_endpoint_get_helper
    from functions_settings import get_user_settings, normalize_model_endpoints

    settings = settings if isinstance(settings, dict) else {}
    user_id = str(model_context.get("user_id") or "").strip()
    if not user_id:
        raise PermissionError("The endpoint owner could not be authorized.")
    context = build_model_endpoint_routing_context(**{
        field: model_context.get(field)
        for field in ("endpoint_id", "model_id", "scope_type", "scope_id")
    })
    scope_type = context["scope_type"]
    scope_id = context["scope_id"]
    if scope_type == "user" and scope_id != user_id:
        raise PermissionError("The user endpoint scope is not authorized.")
    if scope_type == "global" and scope_id != "global":
        raise ValueError("Invalid global model endpoint scope.")

    scope_flag = {
        "user": "allow_user_custom_endpoints",
        "group": "allow_group_custom_endpoints",
    }.get(scope_type)
    if settings.get("enable_multi_model_endpoints") is not True or (
        scope_flag and settings.get(scope_flag) is not True
    ):
        raise PermissionError("Model endpoints are disabled for this scope.")

    loaded_endpoint = {}

    def authorize_scope(requested_scope, requested_scope_id):
        if requested_scope != scope_type or requested_scope_id != scope_id:
            return False
        if requested_scope == "group":
            assert_group_role(
                user_id,
                requested_scope_id,
                allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
            )
        ensure_governance_access(
            f"governance_{requested_scope}_endpoints", user_id
        )
        return True

    def load_endpoint(requested_scope, requested_scope_id, endpoint_id):
        ensure_governance_access(
            f"governance_{requested_scope}_endpoints",
            user_id,
            item_entity_type="global_endpoint",
            item_id=endpoint_id,
        )
        source_revision = ""
        if requested_scope == "global":
            candidates = settings.get("model_endpoints", []) or []
            source_revision = str(settings.get("_etag") or "")
        elif requested_scope == "user":
            user_document = get_user_settings(user_id)
            user_settings = (
                user_document.get("settings", {})
                if isinstance(user_document, dict)
                else {}
            )
            candidates = user_settings.get("personal_model_endpoints", []) or []
            source_revision = (
                str(user_document.get("_etag") or "")
                if isinstance(user_document, dict)
                else ""
            )
        else:
            assert_group_role(
                user_id,
                requested_scope_id,
                allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
            )
            candidates = get_group_model_endpoints(requested_scope_id) or []

        normalized, _ = normalize_model_endpoints(candidates)
        matches = [
            endpoint for endpoint in normalized
            if (
                isinstance(endpoint, dict)
                and str(endpoint.get("id") or "").strip() == endpoint_id
            )
        ]
        if len(matches) != 1:
            return None, source_revision or "missing"
        endpoint = matches[0]
        if not source_revision:
            revision_payload = copy.deepcopy(endpoint)
            auth = revision_payload.get("auth")
            if isinstance(auth, dict):
                for secret_field in (
                    "api_key",
                    "bearer_token",
                    "client_secret",
                    "access_token",
                    "refresh_token",
                ):
                    auth.pop(secret_field, None)
            source_revision = hashlib.sha256(
                json.dumps(
                    revision_payload, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
        loaded_endpoint["value"] = copy.deepcopy(endpoint)
        return endpoint, source_revision

    resolved = resolve_authorized_model_endpoint_route(
        context,
        authorize_scope=authorize_scope,
        load_endpoint=load_endpoint,
        settings=settings,
    )
    endpoint = loaded_endpoint.get("value")
    if not isinstance(endpoint, dict):
        raise LookupError("The selected model endpoint could not be found.")
    endpoint = keyvault_model_endpoint_get_helper(
        endpoint,
        context["endpoint_id"],
        scope=scope_type,
        return_type=SecretReturnType.VALUE,
    )
    endpoint["_resolved_route"] = resolved["route"]
    endpoint["_route_cache_key"] = resolved["cache_key"]
    return endpoint


def resolve_model_endpoint_from_context(settings, model_context, *, authorize=False):
    """Resolve selected endpoint metadata, including secrets, from non-secret model context."""
    # Defer store imports so client adapter registration does not initialize scoped stores.
    from functions_group import get_group_model_endpoints
    from functions_keyvault import SecretReturnType, keyvault_model_endpoint_get_helper
    from functions_settings import get_user_settings, normalize_model_endpoints
    from functions_model_catalog import apply_model_profile
    # Orchestration resolves models off the request thread using a captured identity.
    if authorize:
        from functions_governance import filter_governed_model_endpoints
        from functions_group import assert_group_role

    settings = settings or {}
    model_context = model_context if isinstance(model_context, dict) else {}
    if routing_schema_version(model_context) == 2:
        if not authorize:
            raise PermissionError(
                "Explicit model routing requires an authorized execution context."
            )
        return _resolve_schema_v2_model_endpoint_context(settings, model_context)
    requested_endpoint_id = str(model_context.get('endpoint_id') or '').strip()
    requested_model_id = str(model_context.get('model_id') or '').strip()
    requested_deployment = str(model_context.get('request_model') or model_context.get('model_deployment') or '').strip()
    requested_provider = str(model_context.get('provider') or '').strip().lower()
    requested_scope_type = str(model_context.get('scope_type') or '').strip().lower()
    if requested_scope_type == 'personal':
        requested_scope_type = 'user'
    requested_scope_id = str(model_context.get('scope_id') or '').strip()
    if not settings.get('enable_multi_model_endpoints', False):
        return None
    if not (requested_endpoint_id or requested_model_id or requested_deployment):
        return None

    endpoints = []
    user_id = str(model_context.get('user_id') or '').strip()
    if authorize and not user_id:
        raise PermissionError('A model execution identity is required.')
    if user_id and settings.get('allow_user_custom_endpoints', False):
        user_settings_doc = get_user_settings(user_id)
        user_settings = user_settings_doc.get('settings', {}) if isinstance(user_settings_doc, dict) else {}
        personal_endpoints, _ = normalize_model_endpoints(user_settings.get('personal_model_endpoints', []) or [])
        if authorize:
            personal_endpoints = filter_governed_model_endpoints(
                user_id, personal_endpoints, 'governance_user_endpoints',
            )
        for endpoint in personal_endpoints:
            _append_model_endpoint_candidate(endpoints, 'user', endpoint, user_id)

    if settings.get('allow_group_custom_endpoints', False):
        seen_group_ids = set()
        for group_id in model_context.get('active_group_ids') or []:
            group_key = str(group_id or '').strip()
            if not group_key or group_key in seen_group_ids:
                continue
            seen_group_ids.add(group_key)
            if authorize:
                assert_group_role(
                    user_id, group_key, allowed_roles=('Owner', 'Admin', 'DocumentManager', 'User'),
                )
            group_endpoints, _ = normalize_model_endpoints(get_group_model_endpoints(group_key) or [])
            if authorize:
                group_endpoints = filter_governed_model_endpoints(
                    user_id, group_endpoints, 'governance_group_endpoints',
                )
            for endpoint in group_endpoints:
                _append_model_endpoint_candidate(endpoints, 'group', endpoint, group_key)

    global_endpoints, _ = normalize_model_endpoints(settings.get('model_endpoints', []) or [])
    if authorize:
        global_endpoints = filter_governed_model_endpoints(
            user_id, global_endpoints, 'governance_global_endpoints',
        )
    for endpoint in global_endpoints:
        _append_model_endpoint_candidate(endpoints, 'global', endpoint, 'global')

    if not requested_scope_type and requested_endpoint_id:
        endpoint_id_matches = [
            endpoint_cfg
            for endpoint_cfg in endpoints
            if str(endpoint_cfg.get('id') or '').strip() == requested_endpoint_id
        ]
        if len(endpoint_id_matches) > 1:
            raise AIConnectionError(
                'The selected model endpoint scope is required.',
                'model_scope_required',
            )

    for endpoint_cfg in endpoints:
        if not endpoint_cfg.get('enabled', True):
            continue
        if (
            requested_scope_type
            and endpoint_cfg.get('_endpoint_scope') != requested_scope_type
        ):
            continue
        if (
            requested_scope_id
            and endpoint_cfg.get('_endpoint_scope_id') != requested_scope_id
        ):
            continue
        if requested_endpoint_id and str(endpoint_cfg.get('id') or '').strip() != requested_endpoint_id:
            continue
        if requested_provider and str(endpoint_cfg.get('provider') or '').strip().lower() not in ('', requested_provider):
            continue

        models = endpoint_cfg.get('models', []) or []
        matched_model = None
        for model_cfg in models:
            deployment = resolve_model_endpoint_request_model(endpoint_cfg, model_cfg)
            if requested_model_id:
                if str(model_cfg.get('id') or '').strip() != requested_model_id:
                    continue
                matched_model = model_cfg
                break
            if requested_deployment and deployment == requested_deployment:
                matched_model = model_cfg
                break
        if not matched_model:
            continue
        if routing_schema_version(endpoint_cfg) == 2:
            raise ValueError(
                "An explicit schema-v2 model endpoint context is required."
            )
        effective_model = apply_model_profile(matched_model, endpoint_cfg, settings)
        endpoint_cfg['models'] = [
            effective_model if item is matched_model else item for item in models
        ]
        matched_model = effective_model
        require_model_capability(matched_model, provider=endpoint_cfg.get('provider') or 'aoai')

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


def build_semantic_kernel_chat_service_for_model(
    gpt_model,
    settings,
    *,
    service_id='chat-model',
    model_context=None,
    resolved_model_endpoint=None,
    apply_model_persona=None,
):
    """Create a Semantic Kernel chat service for the selected model endpoint."""
    settings = settings or {}
    model_context = model_context if isinstance(model_context, dict) else {}
    if apply_model_persona is None:
        apply_model_persona = model_context.get("apply_model_persona") is not False
    resolved_model_endpoint = resolved_model_endpoint if isinstance(resolved_model_endpoint, dict) else None
    resolved_route = None

    if resolved_model_endpoint is None and (
        model_context.get('endpoint_id') or model_context.get('model_id')
    ):
        resolved_model_endpoint = resolve_model_endpoint_from_context(
            settings,
            model_context,
            authorize=routing_schema_version(model_context) == 2,
        )
        if resolved_model_endpoint is None:
            raise AIConnectionError('The selected chat connection or model is unavailable.')
    if resolved_model_endpoint:
        resolved_route = resolved_model_endpoint.get('_resolved_route')
        if (
            routing_schema_version(resolved_model_endpoint) == 2
            and not isinstance(resolved_route, dict)
        ):
            raise ValueError(
                "Explicit model routing must be re-resolved before dispatch."
            )

    persona_markdown = ""

    def finalize_service(service, protocol):
        if resolved_route is not None:
            if isinstance(service, AnthropicSemanticKernelChatCompletion):
                service.resolved_route = copy.deepcopy(resolved_route)
            else:
                bind_model_endpoint_request_policy(
                    service.client,
                    resolved_route,
                    persona_markdown=persona_markdown,
                )
        elif (
            persona_markdown
            and not isinstance(service, AnthropicSemanticKernelChatCompletion)
        ):
            bind_model_endpoint_request_policy(
                service.client,
                None,
                persona_markdown=persona_markdown,
            )
        if isinstance(service, AnthropicSemanticKernelChatCompletion):
            service.model_persona_markdown = persona_markdown
        return service, protocol

    provider = str(model_context.get('provider') or '').strip().lower()
    endpoint = str(model_context.get('endpoint') or '').strip()
    api_version = str(model_context.get('api_version') or '').strip()
    auth_settings = model_context.get('auth') if isinstance(model_context.get('auth'), dict) else {}
    deployment_name = str(model_context.get('request_model') or model_context.get('model_deployment') or gpt_model or '').strip()
    matched_model = None

    if resolved_model_endpoint:
        provider = str(resolved_model_endpoint.get('provider') or provider or 'aoai').strip().lower()
        connection = resolved_model_endpoint.get('connection', {}) or {}
        endpoint = str(connection.get('endpoint') or endpoint).strip()
        api_version = str(
            (
                resolved_route.get('api_version')
                if resolved_route
                else connection.get('openai_api_version')
                or connection.get('api_version')
                or api_version
            )
        ).strip()
        auth_settings = resolved_model_endpoint.get('auth', {}) or auth_settings
        requested_model_id = str(
            model_context.get('model_id')
            or (resolved_route or {}).get("model_id")
            or ""
        ).strip()
        matched_model = _require_chat_model_for_endpoint(
            resolved_model_endpoint, deployment_name, requested_model_id,
        )
        if matched_model and resolved_route is None:
            deployment_name = resolve_model_endpoint_request_model(resolved_model_endpoint, matched_model)
        if resolved_route is not None:
            deployment_name = str(
                resolved_route.get('request_model') or ''
            ).strip()
    elif deployment_name:
        require_model_capability(deployment_name, provider=provider or 'aoai')
        configured_endpoint = endpoint or settings.get('azure_openai_gpt_endpoint')
        for candidate in (settings.get('gpt_model') or {}).get('selected') or ():
            if (
                candidate.get('deploymentName') == deployment_name
                and (candidate.get('endpoint') or configured_endpoint) == configured_endpoint
            ):
                matched_model = candidate
                break

    requested_model_id = str(model_context.get('model_id') or '').strip()
    if apply_model_persona and (
        requested_model_id
        and str((matched_model or {}).get('id') or '').strip() == requested_model_id
    ):
        persona_markdown = active_model_persona_markdown(matched_model)

    if not resolved_model_endpoint and provider in ('', 'aoai', 'aifoundry', 'new_foundry') and not (
        provider and endpoint and deployment_name
    ):
        legacy_apim = settings.get('enable_gpt_apim', False)
        legacy_prefix = 'azure_apim_gpt' if legacy_apim else 'azure_openai_gpt'
        legacy_endpoint = settings.get(f'{legacy_prefix}_endpoint')
        # Legacy global/APIM settings can name v1 without a saved connection record.
        if infer_model_endpoint_protocol(
            'aoai', legacy_endpoint, deployment_name,
            use_responses_api=settings.get(f'{legacy_prefix}_use_responses_api'),
        ) == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE:
            provider = provider or 'aoai'
            endpoint = str(legacy_endpoint or '').strip()
            api_version = str(settings.get(f'{legacy_prefix}_api_version') or '').strip()
            managed_identity = not legacy_apim and settings.get('azure_openai_gpt_authentication_type') == 'managed_identity'
            auth_settings = {'type': 'managed_identity' if managed_identity else 'api_key'}
            if not managed_identity:
                auth_settings['api_key'] = settings.get(
                    'azure_apim_gpt_subscription_key' if legacy_apim else 'azure_openai_gpt_key',
                )
                auth_settings['api_key_header'] = 'api-key'

    api_type = (
        resolved_route.get("api_type")
        if resolved_route
        else get_model_endpoint_api_type(resolved_model_endpoint)
    )
    use_responses_api = (
        (
            resolved_route.get("inference_api") == "responses"
            if resolved_route
            else (
                (resolved_model_endpoint or {}).get('connection') or {}
            ).get('use_responses_api')
        )
        if resolved_model_endpoint else settings.get(
            'azure_apim_gpt_use_responses_api' if settings.get('enable_gpt_apim') else 'azure_openai_gpt_use_responses_api',
        )
    )
    if resolved_route is None:
        endpoint = resolve_model_inference_endpoint(
            endpoint, use_responses_api=use_responses_api,
            provider=provider or 'aoai', api_type=api_type,
            url_mode=((resolved_model_endpoint or {}).get('connection') or {}).get('url_mode'),
            model=matched_model or deployment_name,
        )
    dispatch_endpoint = (
        resolved_route.get("operation_url") if resolved_route else endpoint
    )
    validate_model_endpoint_api_version(
        provider or 'aoai',
        endpoint,
        api_version,
        api_type,
        use_responses_api=use_responses_api,
        model=matched_model or deployment_name,
    )
    model_token_budget = resolve_model_token_budget(
        matched_model or {'deploymentName': deployment_name},
        resolved_model_endpoint,
        provider='azure' if api_type == 'azure_openai' else provider or 'aoai',
        protocol=(
            resolved_route.get("inference_api")
            if resolved_route
            else model_endpoint_inference_api(
                endpoint,
                use_responses_api,
                provider=provider or "aoai",
                model=matched_model or deployment_name,
            )
        ),
    )

    if provider == 'custom' and (not resolved_model_endpoint or not endpoint or not deployment_name):
        raise AIConnectionError('The selected Custom chat connection or request model is unavailable.')
    if provider and endpoint and deployment_name:
        if provider == 'custom':
            if resolved_model_endpoint is None:
                raise AIConnectionError('The selected Custom connection must be resolved from saved settings.')
            runtime_protocol = (
                resolved_route.get("protocol")
                if resolved_route
                else infer_model_endpoint_protocol(
                    provider, endpoint, deployment_name, api_type
                )
            )
            extra_headers = build_model_endpoint_identity_headers(
                settings, endpoint_config=resolved_model_endpoint, identity_context=model_context,
            )
            if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC:
                return finalize_service(AnthropicSemanticKernelChatCompletion(
                    service_id=service_id, deployment_name=deployment_name, endpoint=endpoint,
                    custom_client=_build_custom_anthropic_client(
                        resolved_model_endpoint,
                        settings,
                        extra_headers,
                        resolved_route=resolved_route,
                    ),
                ), runtime_protocol)
            kwargs = build_custom_openai_client_kwargs(
                resolved_model_endpoint, settings, request_model=deployment_name,
                asynchronous=True, default_headers=extra_headers,
                resolved_route=resolved_route,
            )
            async_client = sanitize_custom_async_openai_client(
                AsyncOpenAI(**kwargs),
                api_type=api_type,
                request_url=dispatch_endpoint or kwargs['base_url'],
                custom_profile=get_custom_endpoint_profile(resolved_model_endpoint),
            )
            return finalize_service(OpenAIChatCompletion(
                service_id=service_id, ai_model_id=deployment_name, async_client=async_client,
                model_token_budget=model_token_budget,
                inference_api=(
                    resolved_route.get("inference_api")
                    if resolved_route
                    else model_endpoint_inference_api(
                        endpoint,
                        use_responses_api,
                        provider=provider,
                        model=matched_model or deployment_name,
                    )
                ),
            ), runtime_protocol)
        runtime_protocol = (
            resolved_route.get("protocol")
            if resolved_route
            else infer_model_endpoint_protocol(
                provider, endpoint, deployment_name
            )
        )
        auth_type = str(auth_settings.get('type') or 'managed_identity').lower()
        extra_headers = build_model_endpoint_identity_headers(
            settings,
            endpoint_config=resolved_model_endpoint,
            identity_context=model_context,
        )
        if auth_type in ('api_key', 'key'):
            api_key = auth_settings.get('api_key')
            if not api_key:
                raise ValueError('Selected model endpoint is missing an API key.')
            if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC:
                return finalize_service(AnthropicSemanticKernelChatCompletion(
                    service_id=service_id,
                    deployment_name=deployment_name,
                    endpoint=dispatch_endpoint,
                    api_key=api_key,
                    extra_headers=extra_headers,
                ), runtime_protocol)
            if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE:
                request_api_version = resolve_openai_style_request_api_version(api_version)
                if auth_settings.get('api_key_header') or endpoint_uses_mai_chat_completions(endpoint):
                    api_key, auth_headers = resolve_custom_endpoint_credentials(
                        auth_settings, default_api_key_header='api-key', default_api_key_prefix='',
                    )
                    extra_headers = {**extra_headers, **auth_headers}
                client_kwargs = {
                    'api_key': api_key,
                    'base_url': normalize_openai_style_base_url(dispatch_endpoint),
                    **globals().get('build_openai_client_timeout_options', lambda *_a, **_k: {})(settings),
                }
                if extra_headers:
                    client_kwargs['default_headers'] = extra_headers
                if request_api_version:
                    client_kwargs['default_query'] = {'api-version': request_api_version}
                return finalize_service(OpenAIChatCompletion(
                    service_id=service_id,
                    ai_model_id=deployment_name,
                    async_client=AsyncOpenAI(**client_kwargs),
                    model_token_budget=model_token_budget,
                    inference_api=(
                        resolved_route.get("inference_api")
                        if resolved_route
                        else model_endpoint_inference_api(
                            endpoint,
                            use_responses_api,
                            provider=provider,
                            model=matched_model or deployment_name,
                        )
                    ),
                ), runtime_protocol)
            return finalize_service(_build_azure_chat_completion(
                service_id=service_id,
                deployment_name=deployment_name,
                endpoint=(
                    _azure_endpoint_from_resolved_route(resolved_route)
                    if resolved_route
                    else endpoint
                ),
                api_key=api_key,
                api_version=api_version,
                default_headers=extra_headers,
                model_token_budget=model_token_budget,
            ), runtime_protocol)

        credential = resolve_credential_for_model_endpoint_auth(auth_settings)
        scope = cognitive_services_scope
        if provider in ('aifoundry', 'new_foundry', 'anthropic', 'claude') or runtime_protocol != MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI:
            scope = resolve_foundry_scope_for_endpoint_auth(auth_settings, endpoint=endpoint)

        if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC:
            token = credential.get_token(scope).token
            return finalize_service(AnthropicSemanticKernelChatCompletion(
                service_id=service_id,
                deployment_name=deployment_name,
                endpoint=dispatch_endpoint,
                bearer_token=token,
                extra_headers=extra_headers,
            ), runtime_protocol)

        if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE:
            token = credential.get_token(scope).token
            request_api_version = resolve_openai_style_request_api_version(api_version)
            client_kwargs = {
                'api_key': token,
                'base_url': normalize_openai_style_base_url(dispatch_endpoint),
                **globals().get('build_openai_client_timeout_options', lambda *_a, **_k: {})(settings),
            }
            if extra_headers:
                client_kwargs['default_headers'] = extra_headers
            if request_api_version:
                client_kwargs['default_query'] = {'api-version': request_api_version}
            return finalize_service(OpenAIChatCompletion(
                service_id=service_id,
                ai_model_id=deployment_name,
                async_client=AsyncOpenAI(**client_kwargs),
                model_token_budget=model_token_budget,
                inference_api=(
                    resolved_route.get("inference_api")
                    if resolved_route
                    else model_endpoint_inference_api(
                        endpoint,
                        use_responses_api,
                        provider=provider,
                        model=matched_model or deployment_name,
                    )
                ),
            ), runtime_protocol)

        token_provider = get_bearer_token_provider(credential, scope)
        try:
            return finalize_service(_build_azure_chat_completion(
                service_id=service_id,
                deployment_name=deployment_name,
                endpoint=(
                    _azure_endpoint_from_resolved_route(resolved_route)
                    if resolved_route
                    else endpoint
                ),
                api_version=api_version,
                azure_ad_token_provider=token_provider,
                default_headers=extra_headers,
                model_token_budget=model_token_budget,
            ), runtime_protocol)
        except TypeError:
            return finalize_service(_build_azure_chat_completion(
                service_id=service_id,
                deployment_name=deployment_name,
                endpoint=(
                    _azure_endpoint_from_resolved_route(resolved_route)
                    if resolved_route
                    else endpoint
                ),
                api_version=api_version,
                ad_token_provider=token_provider,
                default_headers=extra_headers,
                model_token_budget=model_token_budget,
            ), runtime_protocol)

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
            model_token_budget=model_token_budget,
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
                model_token_budget=model_token_budget,
            ), MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI
        except TypeError:
            return _build_azure_chat_completion(
                service_id=service_id,
                deployment_name=gpt_model,
                endpoint=settings.get('azure_openai_gpt_endpoint'),
                api_version=settings.get('azure_openai_gpt_api_version'),
                ad_token_provider=token_provider,
                default_headers=extra_headers,
                model_token_budget=model_token_budget,
            ), MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI

    return _build_azure_chat_completion(
        service_id=service_id,
        deployment_name=gpt_model,
        endpoint=settings.get('azure_openai_gpt_endpoint'),
        api_key=settings.get('azure_openai_gpt_key'),
        api_version=settings.get('azure_openai_gpt_api_version'),
        default_headers=extra_headers,
        model_token_budget=model_token_budget,
    ), MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI
