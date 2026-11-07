# functions_chat_model_catalog.py
"""The authorized model catalog shared by chat selection and request replay."""

from functions_ai_connections import filter_model_endpoints_by_capability
from functions_governance import ensure_governance_access
from functions_group import get_group_model_endpoints
from functions_model_capabilities import REASONING_IDENTIFIER_FIELDS, resolve_model_reasoning_policy
from functions_model_catalog import get_effective_model_profiles, model_profile_projection
from functions_model_endpoint_types import resolve_model_endpoint_request_model
from functions_settings import normalize_model_endpoints, sanitize_model_endpoints_for_frontend


def normalize_chat_model_value(value):
    return str(value or '').strip()


def filter_chat_model_endpoints_by_governance(user_id, endpoints, feature_key):
    try:
        ensure_governance_access(feature_key, user_id)
    except PermissionError:
        return []

    allowed_endpoints = []
    for endpoint in endpoints or []:
        if not isinstance(endpoint, dict):
            continue
        endpoint_id = str(endpoint.get('id') or '').strip()
        if endpoint_id:
            try:
                ensure_governance_access(
                    feature_key,
                    user_id,
                    item_entity_type='global_endpoint',
                    item_id=endpoint_id,
                )
            except PermissionError:
                continue
        allowed_endpoints.append(endpoint)
    return allowed_endpoints


def chat_model_reasoning_metadata(model):
    model_name = next((
        model[field].strip() for field in REASONING_IDENTIFIER_FIELDS
        if isinstance(model.get(field), str) and model[field].strip()
    ), '')
    return {
        'model_name': model_name,
        'reasoning_capabilities': resolve_model_reasoning_policy(model),
    }


def build_chat_model_catalog(*, user_id, settings, user_settings_dict, user_groups_raw):
    profiles = get_effective_model_profiles(settings)
    if not settings.get('enable_multi_model_endpoints', False):
        if settings.get('enable_gpt_apim', False):
            models = [
                {'deploymentName': name.strip(), 'modelName': name.strip()}
                for name in str(settings.get('azure_apim_gpt_deployment') or '').split(',')
                if name.strip()
            ]
        else:
            models = (settings.get('gpt_model') or {}).get('selected', [])
        catalog = []
        for model in models:
            if not isinstance(model, dict):
                continue
            deployment = normalize_chat_model_value(model.get('deploymentName'))
            if deployment:
                reasoning_metadata = chat_model_reasoning_metadata(model)
                catalog.append({
                    'selection_key': deployment,
                    'deployment_name': deployment,
                    'display_name': reasoning_metadata['model_name'],
                    **reasoning_metadata,
                    **model_profile_projection(model, {}, settings, profiles),
                })
        return catalog

    catalog = []

    def append_models(endpoints, scope_type, scope_id=None, scope_name=None):
        sanitized_endpoints = sanitize_model_endpoints_for_frontend(endpoints, catalog_settings=settings)
        normalized_endpoints, _ = normalize_model_endpoints(sanitized_endpoints)

        for endpoint in filter_model_endpoints_by_capability(normalized_endpoints):
            if not endpoint.get('enabled', True):
                continue

            endpoint_id = endpoint.get('id') or ''
            provider = endpoint.get('provider') or 'aoai'
            models = endpoint.get('models') or []
            for model in models:
                if not isinstance(model, dict) or not model.get('enabled', True):
                    continue

                model_id = model.get('id') or model.get('deploymentName') or model.get('deployment') or model.get('modelName') or model.get('name') or ''
                request_model = resolve_model_endpoint_request_model(endpoint, model)
                deployment_name = request_model
                display_name = model.get('displayName') or model.get('modelName') or request_model or deployment_name or model.get('name') or model_id
                selection_key = f"{scope_type}:{scope_id or ''}:{endpoint_id}:{model_id or deployment_name or request_model}"
                catalog.append({
                    'selection_key': selection_key,
                    'model_id': model_id,
                    **chat_model_reasoning_metadata(model),
                    'display_name': display_name,
                    'request_model': request_model,
                    'deployment_name': deployment_name,
                    'endpoint_id': endpoint_id,
                    'provider': provider,
                    'scope_type': scope_type,
                    'scope_id': scope_id,
                    'scope_name': scope_name,
                    'icon': model.get('icon') if isinstance(model.get('icon'), dict) else {},
                    **model_profile_projection(model, endpoint, settings, profiles),
                })

    append_models(
        filter_chat_model_endpoints_by_governance(
            user_id, settings.get('model_endpoints', []) or [], 'governance_global_endpoints',
        ),
        'global', None, 'Global',
    )
    if settings.get('allow_user_custom_endpoints', False):
        append_models(
            filter_chat_model_endpoints_by_governance(
                user_id, user_settings_dict.get('personal_model_endpoints', []) or [], 'governance_user_endpoints',
            ),
            'personal', user_id, 'Personal',
        )
    if settings.get('enable_group_workspaces', False) and settings.get('allow_group_custom_endpoints', False):
        for group_doc in user_groups_raw:
            group_id = group_doc.get('id')
            if group_id:
                append_models(
                    filter_chat_model_endpoints_by_governance(
                        user_id, get_group_model_endpoints(group_id), 'governance_group_endpoints',
                    ),
                    'group', group_id, group_doc.get('name', 'Unnamed Group'),
                )
    return catalog
