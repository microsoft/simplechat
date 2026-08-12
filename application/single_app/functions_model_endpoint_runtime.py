# functions_model_endpoint_runtime.py
"""Runtime helpers for configured model endpoint clients and Semantic Kernel services."""

from openai import AsyncOpenAI, AzureOpenAI
from azure.identity import ClientSecretCredential, DefaultAzureCredential, get_bearer_token_provider
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion, OpenAIChatCompletion

from config import cognitive_services_scope
from foundry_agent_runtime import resolve_authority
from functions_settings import resolve_model_endpoint_foundry_scope
from model_endpoint_clients import (
    MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
    MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
    MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
    AnthropicSemanticKernelChatCompletion,
    build_anthropic_chat_client,
    build_openai_style_chat_client,
    infer_model_endpoint_protocol,
    normalize_openai_style_base_url,
    resolve_openai_style_request_api_version,
)


MODEL_ENDPOINT_PROVIDER_ALLOWLIST = {'aoai', 'aifoundry', 'new_foundry', 'anthropic', 'claude'}
MODEL_CONTEXT_AUTH_FIELDS = (
    'type',
    'tenant_id',
    'client_id',
    'managed_identity_client_id',
    'management_cloud',
    'foundry_scope',
    'authority',
)


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
    endpoint_id=None,
    model_id=None,
    model_deployment=None,
    user_id=None,
    active_group_ids=None,
):
    """Build non-secret model endpoint metadata for downstream helper calls."""
    context = {
        'provider': str(provider or '').strip().lower(),
        'endpoint': str(endpoint or '').strip(),
        'api_version': str(api_version or '').strip(),
        'endpoint_id': str(endpoint_id or '').strip(),
        'model_id': str(model_id or '').strip(),
        'model_deployment': str(model_deployment or '').strip(),
    }

    normalized_user_id = str(user_id or '').strip()
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


def build_model_endpoint_sync_chat_client(
    auth_settings,
    provider,
    endpoint,
    api_version,
    deployment_name='',
):
    """Create a protocol-aware synchronous chat client for a configured model endpoint."""
    auth_settings = auth_settings or {}
    normalized_provider = str(provider or 'aoai').strip().lower()
    runtime_protocol = infer_model_endpoint_protocol(normalized_provider, endpoint, deployment_name)
    auth_type = str(auth_settings.get('type') or 'managed_identity').strip().lower()

    if auth_type in ('api_key', 'key'):
        api_key = auth_settings.get('api_key')
        if not api_key:
            raise ValueError('Selected model endpoint is missing an API key.')
        if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC:
            return build_anthropic_chat_client(endpoint=endpoint, api_key=api_key), runtime_protocol
        if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE:
            return build_openai_style_chat_client(api_key, endpoint, api_version), runtime_protocol
        return AzureOpenAI(
            api_version=api_version,
            azure_endpoint=endpoint,
            api_key=api_key,
        ), runtime_protocol

    credential = resolve_credential_for_model_endpoint_auth(auth_settings)
    scope = cognitive_services_scope
    if normalized_provider in ('aifoundry', 'new_foundry', 'anthropic', 'claude') or runtime_protocol != MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI:
        scope = resolve_foundry_scope_for_endpoint_auth(auth_settings, endpoint=endpoint)

    if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC:
        token = credential.get_token(scope).token
        return build_anthropic_chat_client(endpoint=endpoint, bearer_token=token), runtime_protocol

    if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE:
        token = credential.get_token(scope).token
        return build_openai_style_chat_client(token, endpoint, api_version), runtime_protocol

    token_provider = get_bearer_token_provider(credential, scope)
    return AzureOpenAI(
        api_version=api_version,
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
    ), runtime_protocol


def _append_model_endpoint_candidate(endpoints, scope, endpoint):
    if isinstance(endpoint, dict):
        endpoints.append({**endpoint, '_endpoint_scope': scope})


def resolve_model_endpoint_from_context(settings, model_context):
    """Resolve selected endpoint metadata, including secrets, from non-secret model context."""
    from functions_group import get_group_model_endpoints
    from functions_keyvault import SecretReturnType, keyvault_model_endpoint_get_helper
    from functions_settings import get_user_settings, normalize_model_endpoints

    settings = settings or {}
    model_context = model_context if isinstance(model_context, dict) else {}
    requested_endpoint_id = str(model_context.get('endpoint_id') or '').strip()
    requested_model_id = str(model_context.get('model_id') or '').strip()
    requested_deployment = str(model_context.get('model_deployment') or '').strip()
    requested_provider = str(model_context.get('provider') or '').strip().lower()
    if not settings.get('enable_multi_model_endpoints', False):
        return None
    if not (requested_endpoint_id or requested_model_id or requested_deployment):
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
            group_endpoints, _ = normalize_model_endpoints(get_group_model_endpoints(group_key) or [])
            for endpoint in group_endpoints:
                _append_model_endpoint_candidate(endpoints, 'group', endpoint)

    global_endpoints, _ = normalize_model_endpoints(settings.get('model_endpoints', []) or [])
    for endpoint in global_endpoints:
        _append_model_endpoint_candidate(endpoints, 'global', endpoint)

    for endpoint_cfg in endpoints:
        if not endpoint_cfg.get('enabled', True):
            continue
        if requested_endpoint_id and str(endpoint_cfg.get('id') or '').strip() != requested_endpoint_id:
            continue
        if requested_provider and str(endpoint_cfg.get('provider') or '').strip().lower() not in ('', requested_provider):
            continue

        models = endpoint_cfg.get('models', []) or []
        matched_model = None
        for model_cfg in models:
            deployment = str(model_cfg.get('deploymentName') or model_cfg.get('deployment') or '').strip()
            if requested_model_id and str(model_cfg.get('id') or '').strip() == requested_model_id:
                matched_model = model_cfg
                break
            if requested_deployment and deployment == requested_deployment:
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

    if resolved_model_endpoint is None and (
        model_context.get('endpoint_id') or model_context.get('model_id')
    ):
        resolved_model_endpoint = resolve_model_endpoint_from_context(settings, model_context)

    provider = str(model_context.get('provider') or '').strip().lower()
    endpoint = str(model_context.get('endpoint') or '').strip()
    api_version = str(model_context.get('api_version') or '').strip()
    auth_settings = model_context.get('auth') if isinstance(model_context.get('auth'), dict) else {}
    deployment_name = str(model_context.get('model_deployment') or gpt_model or '').strip()

    if resolved_model_endpoint:
        provider = str(resolved_model_endpoint.get('provider') or provider or 'aoai').strip().lower()
        connection = resolved_model_endpoint.get('connection', {}) or {}
        endpoint = str(connection.get('endpoint') or endpoint).strip()
        api_version = str(
            connection.get('openai_api_version')
            or connection.get('api_version')
            or api_version
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
        if matched_model is None and deployment_name:
            matched_model = next(
                (
                    model for model in resolved_models
                    if str(model.get('deploymentName') or model.get('deployment') or '').strip() == deployment_name
                ),
                None,
            )
        if matched_model:
            deployment_name = str(
                matched_model.get('deploymentName') or matched_model.get('deployment') or deployment_name
            ).strip()

    if provider and endpoint and deployment_name:
        runtime_protocol = infer_model_endpoint_protocol(provider, endpoint, deployment_name)
        auth_type = str(auth_settings.get('type') or 'managed_identity').lower()
        if auth_type in ('api_key', 'key'):
            api_key = auth_settings.get('api_key')
            if not api_key:
                raise ValueError('Selected model endpoint is missing an API key.')
            if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC:
                return AnthropicSemanticKernelChatCompletion(
                    service_id=service_id,
                    deployment_name=deployment_name,
                    endpoint=endpoint,
                    api_key=api_key,
                ), runtime_protocol
            if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE:
                request_api_version = resolve_openai_style_request_api_version(api_version)
                client_kwargs = {
                    'api_key': api_key,
                    'base_url': normalize_openai_style_base_url(endpoint),
                }
                if request_api_version:
                    client_kwargs['default_query'] = {'api-version': request_api_version}
                return OpenAIChatCompletion(
                    service_id=service_id,
                    ai_model_id=deployment_name,
                    async_client=AsyncOpenAI(**client_kwargs),
                ), runtime_protocol
            return AzureChatCompletion(
                service_id=service_id,
                deployment_name=deployment_name,
                endpoint=endpoint,
                api_key=api_key,
                api_version=api_version,
            ), runtime_protocol

        credential = resolve_credential_for_model_endpoint_auth(auth_settings)
        scope = cognitive_services_scope
        if provider in ('aifoundry', 'new_foundry', 'anthropic', 'claude') or runtime_protocol != MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI:
            scope = resolve_foundry_scope_for_endpoint_auth(auth_settings, endpoint=endpoint)

        if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC:
            token = credential.get_token(scope).token
            return AnthropicSemanticKernelChatCompletion(
                service_id=service_id,
                deployment_name=deployment_name,
                endpoint=endpoint,
                bearer_token=token,
            ), runtime_protocol

        if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE:
            token = credential.get_token(scope).token
            request_api_version = resolve_openai_style_request_api_version(api_version)
            client_kwargs = {
                'api_key': token,
                'base_url': normalize_openai_style_base_url(endpoint),
            }
            if request_api_version:
                client_kwargs['default_query'] = {'api-version': request_api_version}
            return OpenAIChatCompletion(
                service_id=service_id,
                ai_model_id=deployment_name,
                async_client=AsyncOpenAI(**client_kwargs),
            ), runtime_protocol

        token_provider = get_bearer_token_provider(credential, scope)
        try:
            return AzureChatCompletion(
                service_id=service_id,
                deployment_name=deployment_name,
                endpoint=endpoint,
                api_version=api_version,
                azure_ad_token_provider=token_provider,
            ), runtime_protocol
        except TypeError:
            return AzureChatCompletion(
                service_id=service_id,
                deployment_name=deployment_name,
                endpoint=endpoint,
                api_version=api_version,
                ad_token_provider=token_provider,
            ), runtime_protocol

    enable_gpt_apim = settings.get('enable_gpt_apim', False)
    if enable_gpt_apim:
        return AzureChatCompletion(
            service_id=service_id,
            deployment_name=gpt_model,
            endpoint=settings.get('azure_apim_gpt_endpoint'),
            api_key=settings.get('azure_apim_gpt_subscription_key'),
            api_version=settings.get('azure_apim_gpt_api_version'),
        ), MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI

    auth_type = settings.get('azure_openai_gpt_authentication_type')
    if auth_type == 'managed_identity':
        token_provider = get_bearer_token_provider(DefaultAzureCredential(), cognitive_services_scope)
        try:
            return AzureChatCompletion(
                service_id=service_id,
                deployment_name=gpt_model,
                endpoint=settings.get('azure_openai_gpt_endpoint'),
                api_version=settings.get('azure_openai_gpt_api_version'),
                azure_ad_token_provider=token_provider,
            ), MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI
        except TypeError:
            return AzureChatCompletion(
                service_id=service_id,
                deployment_name=gpt_model,
                endpoint=settings.get('azure_openai_gpt_endpoint'),
                api_version=settings.get('azure_openai_gpt_api_version'),
                ad_token_provider=token_provider,
            ), MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI

    return AzureChatCompletion(
        service_id=service_id,
        deployment_name=gpt_model,
        endpoint=settings.get('azure_openai_gpt_endpoint'),
        api_key=settings.get('azure_openai_gpt_key'),
        api_version=settings.get('azure_openai_gpt_api_version'),
    ), MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI
