# route_backend_agents.py

import re
import uuid
import logging
import builtins
from flask import Blueprint, jsonify, request, current_app, session
from config import (
    cosmos_global_agents_container,
    cosmos_group_agents_container,
    cosmos_personal_agents_container,
)
from semantic_kernel_loader import get_agent_orchestration_types
from functions_settings import get_settings, update_settings, get_user_settings, update_user_settings, sanitize_model_endpoints_for_frontend
from functions_global_agents import get_global_agents, save_global_agent, delete_global_agent
from functions_personal_agents import get_personal_agents, ensure_migration_complete, save_personal_agent, delete_personal_agent
from functions_group import require_active_group, assert_group_role
from functions_agent_payload import (
    AgentPayloadError,
    can_agent_use_default_multi_endpoint_model,
    get_agent_model_binding,
    has_agent_custom_connection_override,
    is_azure_ai_foundry_agent,
    sanitize_agent_payload,
)
from functions_group_agents import (
    get_group_agents,
    get_group_agent,
    save_group_agent,
    delete_group_agent,
    validate_group_agent_payload,
)
from functions_debug import debug_print
from functions_authentication import *
from functions_appinsights import log_event
from functions_group import get_group_model_endpoints, require_active_group
from json_schema_validation import validate_agent
from swagger_wrapper import swagger_route, get_auth_security
from functions_activity_logging import (
    log_agent_creation,
    log_agent_update,
    log_agent_deletion,
    log_general_admin_action,
)

bpa = Blueprint('admin_agents', __name__)


def _build_user_selectable_agents(user_id, requested_agent=None):
    """Build the set of agents the current user is allowed to select."""
    settings = get_settings()
    requested_agent = requested_agent or {}
    candidates = []

    for agent in get_personal_agents(user_id):
        candidate = dict(agent)
        candidate['is_global'] = False
        candidate['is_group'] = False
        candidate['group_id'] = None
        candidate['group_name'] = None
        candidates.append(candidate)

    merge_global = settings.get('per_user_semantic_kernel', False) and settings.get('merge_global_semantic_kernel_with_workspace', False)
    if merge_global or requested_agent.get('is_global'):
        for agent in get_global_agents():
            candidate = dict(agent)
            candidate['is_global'] = True
            candidate['is_group'] = False
            candidate['group_id'] = None
            candidate['group_name'] = None
            candidates.append(candidate)

    requested_group_id = str(requested_agent.get('group_id') or '').strip()
    if requested_agent.get('is_group') and not requested_group_id:
        try:
            requested_group_id = require_active_group(user_id)
        except Exception:
            requested_group_id = ''

    if requested_group_id:
        requested_group_name = requested_agent.get('group_name')
        for agent in get_group_agents(requested_group_id):
            candidate = dict(agent)
            candidate['is_global'] = False
            candidate['is_group'] = True
            candidate['group_id'] = requested_group_id
            if requested_group_name and not candidate.get('group_name'):
                candidate['group_name'] = requested_group_name
            candidates.append(candidate)

    return candidates


def _find_matching_user_selected_agent(candidates, requested_agent):
    """Return the canonical agent record matching the requested selection payload."""
    if not isinstance(requested_agent, dict):
        return None

    requested_name = str(requested_agent.get('name') or '').strip()
    requested_id = str(requested_agent.get('id') or '').strip()
    requested_is_global = bool(requested_agent.get('is_global', False))
    requested_is_group = bool(requested_agent.get('is_group', False))
    requested_group_id = str(requested_agent.get('group_id') or '').strip()

    def scope_matches(candidate):
        candidate_is_global = bool(candidate.get('is_global', False))
        candidate_is_group = bool(candidate.get('is_group', False))
        if requested_is_group:
            if not candidate_is_group:
                return False
            if requested_group_id:
                return str(candidate.get('group_id') or '') == requested_group_id
            return True
        if requested_is_global:
            return candidate_is_global and not candidate_is_group
        return not candidate_is_global and not candidate_is_group

    if requested_id:
        match = next(
            (candidate for candidate in candidates if str(candidate.get('id') or '') == requested_id and scope_matches(candidate)),
            None,
        )
        if match:
            return match

    if requested_name:
        return next(
            (candidate for candidate in candidates if candidate.get('name') == requested_name and scope_matches(candidate)),
            None,
        )

    return None


def _strip_cosmos_metadata(document):
    if not isinstance(document, dict):
        return {}
    return {key: value for key, value in document.items() if not str(key).startswith('_')}


def _format_model_provider_label(provider):
    normalized_provider = str(provider or '').strip().lower()
    if normalized_provider == 'aifoundry':
        return 'Foundry (classic)'
    if normalized_provider == 'new_foundry':
        return 'New Foundry'
    return 'Azure OpenAI'


def _summarize_model_binding(endpoint_candidates, binding):
    endpoint_id = str(binding.get('endpoint_id') or '').strip()
    model_id = str(binding.get('model_id') or '').strip()
    provider = str(binding.get('provider') or '').strip().lower()

    if not endpoint_id and not model_id:
        return {
            'valid': False,
            'state': 'missing',
            'endpoint_id': '',
            'model_id': '',
            'provider': provider,
            'label': 'Not set',
        }

    if not endpoint_id or not model_id:
        return {
            'valid': False,
            'state': 'incomplete',
            'endpoint_id': endpoint_id,
            'model_id': model_id,
            'provider': provider,
            'label': 'Incomplete saved model selection',
        }

    endpoint_cfg = next((candidate for candidate in endpoint_candidates if candidate.get('id') == endpoint_id), None)
    if not endpoint_cfg:
        return {
            'valid': False,
            'state': 'endpoint_missing',
            'endpoint_id': endpoint_id,
            'model_id': model_id,
            'provider': provider,
            'label': f'Missing endpoint: {endpoint_id}',
        }

    if not endpoint_cfg.get('enabled', True):
        return {
            'valid': False,
            'state': 'endpoint_disabled',
            'endpoint_id': endpoint_id,
            'model_id': model_id,
            'provider': provider,
            'label': f'Disabled endpoint: {endpoint_cfg.get("name") or endpoint_id}',
        }

    models = endpoint_cfg.get('models', []) or []
    model_cfg = next((model for model in models if model.get('id') == model_id), None)
    if not model_cfg:
        return {
            'valid': False,
            'state': 'model_missing',
            'endpoint_id': endpoint_id,
            'model_id': model_id,
            'provider': provider,
            'label': f'Missing model: {model_id}',
        }

    if not model_cfg.get('enabled', True):
        return {
            'valid': False,
            'state': 'model_disabled',
            'endpoint_id': endpoint_id,
            'model_id': model_id,
            'provider': provider,
            'label': f'Disabled model: {model_cfg.get("displayName") or model_id}',
        }

    resolved_provider = str(endpoint_cfg.get('provider') or provider or '').strip().lower()
    endpoint_name = endpoint_cfg.get('name') or endpoint_cfg.get('connection', {}).get('endpoint') or endpoint_id
    model_name = model_cfg.get('displayName') or model_cfg.get('deploymentName') or model_cfg.get('modelName') or model_id
    scope_name = str(endpoint_cfg.get('scope') or '').strip().title()
    scope_prefix = f'{scope_name} - ' if scope_name else ''

    return {
        'valid': True,
        'state': 'valid',
        'endpoint_id': endpoint_id,
        'model_id': model_id,
        'provider': resolved_provider,
        'label': f'{scope_prefix}{endpoint_name} / {model_name} ({_format_model_provider_label(resolved_provider)})',
    }


def _binding_matches_default_model(binding_summary, default_model_info):
    return bool(
        binding_summary.get('valid')
        and default_model_info.get('valid')
        and binding_summary.get('endpoint_id') == default_model_info.get('endpoint_id')
        and binding_summary.get('model_id') == default_model_info.get('model_id')
    )


def _build_agent_migration_key(scope, scope_id, agent_id, agent_name):
    scope_value = str(scope or '').strip()
    scope_id_value = str(scope_id or '').strip()
    agent_id_value = str(agent_id or agent_name or '').strip()
    return f'{scope_value}:{scope_id_value}:{agent_id_value}'


def _clear_legacy_agent_connection_override(agent):
    if not isinstance(agent, dict):
        return agent

    for field_name in (
        'azure_openai_gpt_endpoint',
        'azure_openai_gpt_key',
        'azure_openai_gpt_deployment',
        'azure_openai_gpt_api_version',
        'azure_agent_apim_gpt_endpoint',
        'azure_agent_apim_gpt_subscription_key',
        'azure_agent_apim_gpt_deployment',
        'azure_agent_apim_gpt_api_version',
    ):
        agent[field_name] = ''

    agent['enable_agent_gpt_apim'] = False
    return agent


def _build_default_model_info(settings):
    default_selection = settings.get('default_model_selection', {}) or {}
    default_endpoint_id = str(default_selection.get('endpoint_id') or '').strip()
    default_model_id = str(default_selection.get('model_id') or '').strip()
    default_provider = str(default_selection.get('provider') or '').strip().lower()
    binding = {
        'endpoint_id': default_endpoint_id,
        'model_id': default_model_id,
        'provider': default_provider,
    }

    if not default_endpoint_id or not default_model_id:
        return {
            'configured': False,
            'valid': False,
            'endpoint_id': default_endpoint_id,
            'model_id': default_model_id,
            'provider': default_provider,
            'state': 'missing',
            'label': 'No default model selected',
        }

    binding_summary = _summarize_model_binding(build_combined_model_endpoints(settings), binding)
    return {
        'configured': True,
        'valid': binding_summary['valid'],
        'endpoint_id': default_endpoint_id,
        'model_id': default_model_id,
        'provider': binding_summary.get('provider') or default_provider,
        'state': binding_summary['state'],
        'label': binding_summary['label'] if binding_summary['valid'] else 'Saved default model is no longer available',
    }


def _load_all_agent_records_for_default_migration():
    records = []

    global_agents = list(
        cosmos_global_agents_container.query_items(
            query='SELECT * FROM c',
            enable_cross_partition_query=True,
        )
    )
    for agent in global_agents:
        cleaned = _strip_cosmos_metadata(agent)
        cleaned['is_global'] = True
        cleaned['is_group'] = False
        cleaned.setdefault('agent_type', 'local')
        records.append({
            'scope': 'global',
            'scope_id': '',
            'scope_label': 'Global',
            'agent': cleaned,
        })

    group_agents = list(
        cosmos_group_agents_container.query_items(
            query='SELECT * FROM c',
            enable_cross_partition_query=True,
        )
    )
    for agent in group_agents:
        cleaned = _strip_cosmos_metadata(agent)
        group_id = str(cleaned.get('group_id') or '').strip()
        cleaned['is_global'] = False
        cleaned['is_group'] = True
        cleaned.setdefault('agent_type', 'local')
        records.append({
            'scope': 'group',
            'scope_id': group_id,
            'scope_label': group_id or 'Unknown group',
            'agent': cleaned,
        })

    personal_agents = list(
        cosmos_personal_agents_container.query_items(
            query='SELECT * FROM c',
            enable_cross_partition_query=True,
        )
    )
    for agent in personal_agents:
        cleaned = _strip_cosmos_metadata(agent)
        user_id = str(cleaned.get('user_id') or '').strip()
        cleaned['is_global'] = False
        cleaned['is_group'] = False
        cleaned.setdefault('agent_type', 'local')
        records.append({
            'scope': 'personal',
            'scope_id': user_id,
            'scope_label': user_id or 'Unknown user',
            'agent': cleaned,
        })

    return records


def _get_endpoint_candidates_for_agent(settings, record, cache):
    scope = record['scope']
    scope_id = record['scope_id']

    if scope == 'group' and scope_id:
        cache_key = f'group:{scope_id}'
        if cache_key not in cache:
            cache[cache_key] = build_combined_model_endpoints(settings, group_id=scope_id)
        return cache[cache_key]

    if scope == 'personal' and scope_id:
        cache_key = f'personal:{scope_id}'
        if cache_key not in cache:
            cache[cache_key] = build_combined_model_endpoints(settings, user_id=scope_id)
        return cache[cache_key]

    if 'global' not in cache:
        cache['global'] = build_combined_model_endpoints(settings)
    return cache['global']


def _classify_agent_for_default_model_migration(record, settings, default_model_info, endpoint_cache):
    agent = record['agent']
    endpoint_candidates = _get_endpoint_candidates_for_agent(settings, record, endpoint_cache)
    binding = get_agent_model_binding(agent)
    binding_summary = _summarize_model_binding(endpoint_candidates, binding)
    agent_name = str(agent.get('name') or '').strip() or 'Unnamed agent'
    display_name = str(agent.get('display_name') or '').strip() or agent_name
    agent_id = str(agent.get('id') or '').strip()
    agent_type = str(agent.get('agent_type') or 'local').strip().lower() or 'local'
    selection_key = _build_agent_migration_key(record['scope'], record['scope_id'], agent_id, agent_name)
    selected_by_default = False
    can_force_migrate = False
    migration_action = 'none'

    if is_azure_ai_foundry_agent(agent):
        migration_status = 'manual_review'
        reason = 'Foundry agents are managed separately and cannot be rebound from this tool.'
    elif binding_summary['valid'] and _binding_matches_default_model(binding_summary, default_model_info):
        migration_status = 'already_migrated'
        reason = 'Agent is already bound to the saved default model.'
    elif has_agent_custom_connection_override(agent):
        migration_status = 'manual_review'
        if default_model_info['valid']:
            can_force_migrate = True
            migration_action = 'force_override_to_default'
            reason = 'Agent has explicit custom connection values. Select it in review to override those settings and bind it to the saved default model.'
        else:
            reason = 'Save a valid default model before overriding explicit custom connection values.'
    elif binding_summary['valid']:
        migration_status = 'manual_review'
        if default_model_info['valid']:
            can_force_migrate = True
            migration_action = 'rebind_to_default'
            reason = 'Agent is already bound to a different model than the saved default. Select it in review to rebind it intentionally.'
        else:
            reason = 'Save a valid default model before rebinding agents to a new default.'
    elif default_model_info['valid'] and can_agent_use_default_multi_endpoint_model(agent):
        migration_status = 'ready_to_migrate'
        reason = 'Agent uses inherited/default routing and can be bound to the saved admin default model.'
        selected_by_default = True
        migration_action = 'apply_default'
    else:
        migration_status = 'needs_default_model'
        reason = 'Save a valid default model before migrating inherited agents.'

    return {
        'scope': record['scope'],
        'scope_id': record['scope_id'],
        'scope_label': record['scope_label'],
        'agent_id': agent_id,
        'agent_name': agent_name,
        'agent_display_name': display_name,
        'agent_type': agent_type,
        'migration_status': migration_status,
        'reason': reason,
        'current_binding_state': binding_summary['state'],
        'current_binding_label': binding_summary['label'],
        'selection_key': selection_key,
        'selected_by_default': selected_by_default,
        'can_force_migrate': can_force_migrate,
        'migration_action': migration_action,
        'can_select': bool(selected_by_default or can_force_migrate),
        'can_migrate': bool(selected_by_default or can_force_migrate),
        '_raw_agent': agent,
    }


def _build_default_model_agent_migration_preview(settings):
    default_model_info = _build_default_model_info(settings)
    endpoint_cache = {}
    records = [
        _classify_agent_for_default_model_migration(record, settings, default_model_info, endpoint_cache)
        for record in _load_all_agent_records_for_default_migration()
    ]

    status_order = {
        'ready_to_migrate': 0,
        'manual_review': 1,
        'needs_default_model': 2,
        'already_migrated': 3,
    }
    scope_order = {
        'global': 0,
        'group': 1,
        'personal': 2,
    }
    records.sort(
        key=lambda record: (
            status_order.get(record['migration_status'], 99),
            scope_order.get(record['scope'], 99),
            record['scope_label'].lower(),
            record['agent_display_name'].lower(),
        )
    )

    summary = {
        'total_agents': len(records),
        'ready_to_migrate': sum(record['migration_status'] == 'ready_to_migrate' for record in records),
        'needs_default_model': sum(record['migration_status'] == 'needs_default_model' for record in records),
        'manual_review': sum(record['migration_status'] == 'manual_review' for record in records),
        'already_migrated': sum(record['migration_status'] == 'already_migrated' for record in records),
        'selectable_override': sum(record['migration_status'] == 'manual_review' and record['can_force_migrate'] for record in records),
        'selected_by_default': sum(record['selected_by_default'] for record in records),
        'selectable_total': sum(record['can_select'] for record in records),
    }
    summary['pending_action'] = summary['ready_to_migrate'] + summary['needs_default_model'] + summary['selectable_override']

    return {
        'default_model': default_model_info,
        'summary': summary,
        'agents': [{key: value for key, value in record.items() if key != '_raw_agent'} for record in records],
        'records': records,
        'migration_notice_enabled': bool((settings.get('multi_endpoint_migration_notice', {}) or {}).get('enabled', False)),
    }


def _maybe_disable_multi_endpoint_migration_notice(settings, preview):
    if preview['summary']['ready_to_migrate'] or preview['summary']['needs_default_model']:
        return False

    notice = settings.get('multi_endpoint_migration_notice', {}) or {}
    if not notice.get('enabled', False):
        return False

    notice['enabled'] = False
    update_settings({'multi_endpoint_migration_notice': notice})
    return True

# === AGENT GUID GENERATION ENDPOINT ===
@bpa.route('/api/agents/generate_id', methods=['GET'])
@swagger_route(
    security=get_auth_security()
)
@login_required
def generate_agent_id():
    """Generate a new GUID for agent creation (user or admin)."""
    return jsonify({'id': str(uuid.uuid4())})

# === USER AGENTS ENDPOINTS ===
@bpa.route('/api/user/agents', methods=['GET'])
@swagger_route(
    security=get_auth_security()
)
@login_required
def get_user_agents():
    settings = get_settings()
    if not settings.get('allow_user_agents', False):
        return jsonify([])
    user_id = get_current_user_id()
    # Ensure migration is complete (will migrate any remaining legacy data)
    ensure_migration_complete(user_id)
    
    # Get agents from the new personal_agents container
    agents = get_personal_agents(user_id)
    
    # Always mark user agents as is_global: False
    for agent in agents:
        agent['is_global'] = False
        agent['is_group'] = False
        agent.setdefault('agent_type', 'local')

    # Check global/merge toggles
    per_user = settings.get('per_user_semantic_kernel', False)
    merge_global = settings.get('merge_global_semantic_kernel_with_workspace', False)
    if per_user and merge_global:
        # Import and get global agents from container
        global_agents = get_global_agents()
        # Mark global agents
        for agent in global_agents:
            agent['is_global'] = True
            agent['is_group'] = False
            agent.setdefault('agent_type', 'local')
        
        # Merge agents using ID as key to avoid name conflicts
        # This allows both personal and global agents with same name to coexist
        all_agents = {}
        
        # Add personal agents first
        for agent in agents:
            key = f"personal_{agent.get('id', agent['name'])}"
            all_agents[key] = agent
            
        # Add global agents
        for agent in global_agents:
            key = f"global_{agent.get('id', agent['name'])}"
            all_agents[key] = agent

        return jsonify(list(all_agents.values()))
    else:
        return jsonify(agents)

@bpa.route('/api/user/agents', methods=['POST'])
@swagger_route(
    security=get_auth_security()
)
@login_required
@enabled_required("allow_user_agents")
def set_user_agents():
    user_id = get_current_user_id()
    agents = request.json if isinstance(request.json, list) else []
    settings = get_settings()
    # If custom endpoints are not allowed, strip deployment settings for endpoint, key, and api-revision
    if not settings.get('allow_user_custom_endpoints', False):
        for agent in agents:
            # APIM fields
            for k in ['azure_agent_apim_gpt_endpoint', 'azure_agent_apim_gpt_subscription_key', 'azure_agent_apim_gpt_api_revision']:
                agent.pop(k, None)
            # Non-APIM fields
            for k in ['azure_openai_gpt_endpoint', 'azure_openai_gpt_key', 'azure_openai_gpt_api_revision']:
                agent.pop(k, None)

    # Remove any global agents before saving
    filtered_agents = []
    for agent in agents:
        if agent.get('is_global', False):
            continue  # Skip global agents
        try:
            cleaned_agent = sanitize_agent_payload(agent)
        except AgentPayloadError as exc:
            return jsonify({'error': str(exc)}), 400
        cleaned_agent['is_global'] = False
        cleaned_agent['is_group'] = False
        validation_error = validate_agent(cleaned_agent)
        if validation_error:
            return jsonify({'error': f'Agent validation failed: {validation_error}'}), 400
        filtered_agents.append(cleaned_agent)

    # Enforce global agent only if per_user_semantic_kernel is False
    per_user_semantic_kernel = settings.get('per_user_semantic_kernel', False)
    if not per_user_semantic_kernel:
        global_selected_agent = settings.get('global_selected_agent', {})
        global_name = global_selected_agent.get('name')
        if global_name:
            found = any(a.get('name') == global_name for a in filtered_agents)
            if not found:
                return jsonify({'error': f'At least one agent must match the global_selected_agent ("{global_name}").'}), 400

    # Get current personal agents to determine what to delete
    current_agents = get_personal_agents(user_id)
    current_agent_names = set(agent['name'] for agent in current_agents)
    
    # Save new/updated agents to personal_agents container
    for agent in filtered_agents:
        save_personal_agent(user_id, agent)
    
    # Delete agents that are no longer in the filtered list
    new_agent_names = set(agent['name'] for agent in filtered_agents)
    agents_to_delete = current_agent_names - new_agent_names
    for agent_name in agents_to_delete:
        delete_personal_agent(user_id, agent_name)
    
    # Log individual agent activities
    for agent in filtered_agents:
        a_name = agent.get('name', '')
        a_id = agent.get('id', '')
        a_display = agent.get('display_name', a_name)
        if a_name in current_agent_names:
            log_agent_update(user_id=user_id, agent_id=a_id, agent_name=a_name, agent_display_name=a_display, scope='personal')
        else:
            log_agent_creation(user_id=user_id, agent_id=a_id, agent_name=a_name, agent_display_name=a_display, scope='personal')
    for agent_name in agents_to_delete:
        log_agent_deletion(user_id=user_id, agent_id=agent_name, agent_name=agent_name, scope='personal')

    log_event("User agents updated", extra={"user_id": user_id, "agents_count": len(filtered_agents)})
    return jsonify({'success': True})

# Add a DELETE endpoint for user agents (if not present)
@bpa.route('/api/user/agents/<agent_name>', methods=['DELETE'])
@swagger_route(
    security=get_auth_security()
)
@enabled_required("allow_user_agents")
@login_required
def delete_user_agent(agent_name):
    user_id = get_current_user_id()
    # Get current agents from personal_agents container
    agents = get_personal_agents(user_id)
    agent_to_delete = next((a for a in agents if a['name'] == agent_name), None)
    if not agent_to_delete:
        return jsonify({'error': 'Agent not found.'}), 404
    
    # Prevent deleting the agent that matches global_selected_agent
    settings = get_settings()
    global_selected_agent = settings.get('global_selected_agent', {})
    global_selected_name = global_selected_agent.get('name')
    if agent_to_delete.get('name') == global_selected_name:
        return jsonify({'error': 'Cannot delete the agent set as global_selected_agent. Please set another agent as global first.'}), 400
    
    # Delete from personal_agents container
    delete_personal_agent(user_id, agent_name)
    
    # Log agent deletion activity
    log_agent_deletion(user_id=user_id, agent_id=agent_to_delete.get('id', agent_name), agent_name=agent_name, scope='personal')

    # Check if there are any agents left and if they match global_selected_agent
    remaining_agents = get_personal_agents(user_id)
    if len(remaining_agents) > 0:
        found = any(a.get('name') == global_selected_name for a in remaining_agents)
        if not found:
            return jsonify({'error': 'There must be at least one agent matching the global_selected_agent.'}), 400
  
    log_event("User agent deleted", extra={"user_id": user_id, "agent_name": agent_name})
    return jsonify({'success': True})


# === GROUP AGENT ENDPOINTS ===

@bpa.route('/api/group/agents', methods=['GET'])
@swagger_route(security=get_auth_security())
@login_required
@user_required
@enabled_required('enable_group_workspaces')
@enabled_required('allow_group_agents')
def get_group_agents_route():
    user_id = get_current_user_id()
    try:
        active_group = require_active_group(user_id)
        assert_group_role(
            user_id,
            active_group,
            allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except LookupError as exc:
        return jsonify({'error': str(exc)}), 404
    except PermissionError as exc:
        return jsonify({'error': str(exc)}), 403

    agents = get_group_agents(active_group)
    return jsonify({'agents': agents}), 200


@bpa.route('/api/group/agents/<agent_id>', methods=['GET'])
@swagger_route(security=get_auth_security())
@login_required
@user_required
@enabled_required('enable_group_workspaces')
@enabled_required('allow_group_agents')
def get_group_agent_route(agent_id):
    user_id = get_current_user_id()
    try:
        active_group = require_active_group(user_id)
        assert_group_role(
            user_id,
            active_group,
            allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except LookupError as exc:
        return jsonify({'error': str(exc)}), 404
    except PermissionError as exc:
        return jsonify({'error': str(exc)}), 403

    agent = get_group_agent(active_group, agent_id)
    if not agent:
        return jsonify({'error': 'Agent not found'}), 404
    return jsonify(agent), 200


@bpa.route('/api/group/agents', methods=['POST'])
@swagger_route(security=get_auth_security())
@login_required
@user_required
@enabled_required('enable_group_workspaces')
@enabled_required('allow_group_agents')
def create_group_agent_route():
    user_id = get_current_user_id()
    try:
        active_group = require_active_group(user_id)
        app_settings = get_settings()
        allowed_roles = ("Owner",) if app_settings.get('require_owner_for_group_agent_management') else ("Owner", "Admin")
        assert_group_role(user_id, active_group, allowed_roles=allowed_roles)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except LookupError as exc:
        return jsonify({'error': str(exc)}), 404
    except PermissionError as exc:
        return jsonify({'error': str(exc)}), 403

    payload = request.get_json(silent=True) or {}
    try:
        validate_group_agent_payload(payload, partial=False)
        cleaned_payload = sanitize_agent_payload(payload)
    except (ValueError, AgentPayloadError) as exc:
        return jsonify({'error': str(exc)}), 400

    settings = get_settings()
    if not settings.get('allow_group_custom_endpoints', False):
        for key in [
            'azure_agent_apim_gpt_endpoint',
            'azure_agent_apim_gpt_subscription_key',
            'azure_agent_apim_gpt_api_revision',
            'azure_openai_gpt_endpoint',
            'azure_openai_gpt_key',
            'azure_openai_gpt_api_revision'
        ]:
            cleaned_payload.pop(key, None)

    for key in ('group_id', 'last_updated', 'is_global', 'is_group'):
        cleaned_payload.pop(key, None)

    try:
        saved = save_group_agent(active_group, cleaned_payload, user_id=user_id)
    except Exception as exc:
        debug_print('Failed to save group agent: %s', exc)
        return jsonify({'error': 'Unable to save agent'}), 500

    log_agent_creation(user_id=user_id, agent_id=saved.get('id', ''), agent_name=saved.get('name', ''), agent_display_name=saved.get('display_name', ''), scope='group', group_id=active_group)
    return jsonify(saved), 201


@bpa.route('/api/group/agents/<agent_id>', methods=['PATCH'])
@swagger_route(security=get_auth_security())
@login_required
@user_required
@enabled_required('enable_group_workspaces')
@enabled_required('allow_group_agents')
def update_group_agent_route(agent_id):
    user_id = get_current_user_id()
    try:
        active_group = require_active_group(user_id)
        app_settings = get_settings()
        allowed_roles = ("Owner",) if app_settings.get('require_owner_for_group_agent_management') else ("Owner", "Admin")
        assert_group_role(user_id, active_group, allowed_roles=allowed_roles)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except LookupError as exc:
        return jsonify({'error': str(exc)}), 404
    except PermissionError as exc:
        return jsonify({'error': str(exc)}), 403

    existing = get_group_agent(active_group, agent_id)
    if not existing:
        return jsonify({'error': 'Agent not found'}), 404

    updates = request.get_json(silent=True) or {}
    for key in ('id', 'group_id', 'last_updated', 'is_global', 'is_group'):
        updates.pop(key, None)

    try:
        validate_group_agent_payload(updates, partial=True)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    merged = dict(existing)
    merged.update(updates)
    merged['id'] = agent_id

    try:
        validate_group_agent_payload(merged, partial=False)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    try:
        cleaned_payload = sanitize_agent_payload(merged)
    except AgentPayloadError as exc:
        return jsonify({'error': str(exc)}), 400

    settings = get_settings()
    if not settings.get('allow_group_custom_endpoints', False):
        for key in [
            'azure_agent_apim_gpt_endpoint',
            'azure_agent_apim_gpt_subscription_key',
            'azure_agent_apim_gpt_api_revision',
            'azure_openai_gpt_endpoint',
            'azure_openai_gpt_key',
            'azure_openai_gpt_api_revision'
        ]:
            cleaned_payload.pop(key, None)

    try:
        saved = save_group_agent(active_group, cleaned_payload, user_id=user_id)
    except Exception as exc:
        debug_print('Failed to update group agent %s: %s', agent_id, exc)
        return jsonify({'error': 'Unable to update agent'}), 500

    log_agent_update(user_id=user_id, agent_id=agent_id, agent_name=saved.get('name', ''), agent_display_name=saved.get('display_name', ''), scope='group', group_id=active_group)
    return jsonify(saved), 200


@bpa.route('/api/group/agents/<agent_id>', methods=['DELETE'])
@swagger_route(security=get_auth_security())
@login_required
@user_required
@enabled_required('enable_group_workspaces')
@enabled_required('allow_group_agents')
def delete_group_agent_route(agent_id):
    user_id = get_current_user_id()
    try:
        active_group = require_active_group(user_id)
        app_settings = get_settings()
        allowed_roles = ("Owner",) if app_settings.get('require_owner_for_group_agent_management') else ("Owner", "Admin")
        assert_group_role(user_id, active_group, allowed_roles=allowed_roles)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except LookupError as exc:
        return jsonify({'error': str(exc)}), 404
    except PermissionError as exc:
        return jsonify({'error': str(exc)}), 403

    try:
        removed = delete_group_agent(active_group, agent_id)
    except Exception as exc:
        debug_print('Failed to delete group agent %s: %s', agent_id, exc)
        return jsonify({'error': 'Unable to delete agent'}), 500

    if not removed:
        return jsonify({'error': 'Agent not found'}), 404
    log_agent_deletion(user_id=user_id, agent_id=agent_id, agent_name=agent_id, scope='group', group_id=active_group)
    return jsonify({'message': 'Agent deleted'}), 200

# User endpoint to set selected agent (new model, not legacy default_agent)
@bpa.route('/api/user/settings/selected_agent', methods=['POST'])
@swagger_route(
    security=get_auth_security()
)
@login_required
def set_user_selected_agent():
    user_id = get_current_user_id()
    data = request.json
    selected_agent = data.get('selected_agent')
    if not selected_agent:
        return jsonify({'error': 'selected_agent is required.'}), 400
    if not isinstance(selected_agent, dict):
        return jsonify({'error': 'selected_agent must be an object.'}), 400

    candidates = _build_user_selectable_agents(user_id, requested_agent=selected_agent)
    matched_agent = _find_matching_user_selected_agent(candidates, selected_agent)
    if not matched_agent:
        return jsonify({'error': 'Selected agent is not available for this user or scope.'}), 400

    user_settings = get_user_settings(user_id)
    settings_to_update = user_settings.get('settings', {})
    agent_name = (matched_agent.get('name') or '').strip()
    if not agent_name:
        return jsonify({'error': 'selected_agent.name is required.'}), 400
    agent = {
        "id": matched_agent.get('id'),
        "name": agent_name,
        "display_name": matched_agent.get('display_name', matched_agent.get('name')),
        "is_global": matched_agent.get('is_global', False),
        "is_group": matched_agent.get('is_group', False),
        "group_id": matched_agent.get('group_id'),
        "group_name": matched_agent.get('group_name')
    }
    settings_to_update['selected_agent'] = agent
    settings_to_update['enable_agents'] = True
    update_user_settings(user_id, settings_to_update)
    log_event("User selected agent set", extra={"user_id": user_id, "selected_agent": agent})
    return jsonify({'success': True})

@bpa.route('/api/user/agent/settings', methods=['GET'])
@swagger_route(
    security=get_auth_security()
)
@login_required
def get_global_agent_settings_for_users():
    user_id = get_current_user_id()
    return get_global_agent_settings(include_admin_extras=False, user_id=user_id)

@bpa.route('/api/group/agent/settings', methods=['GET'])
@swagger_route(
    security=get_auth_security()
)
@login_required
@user_required
@enabled_required('enable_group_workspaces')
def get_group_agent_settings():
    user_id = get_current_user_id()
    try:
        group_id = require_active_group(user_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return get_global_agent_settings(include_admin_extras=False, user_id=user_id, group_id=group_id)

# === ADMIN AGENTS ENDPOINTS ===
@bpa.route('/api/admin/agent/settings', methods=['GET'])
@swagger_route(
    security=get_auth_security()
)
@login_required
@admin_required
def get_all_admin_settings():
    return get_global_agent_settings(include_admin_extras=True)

@bpa.route('/api/admin/agents/selected_agent', methods=['POST'])
@swagger_route(
    security=get_auth_security()
)
@login_required
@admin_required
def set_selected_agent():
    try:
        data = request.json
        agent_name = data.get('name')
        if not agent_name:
            return jsonify({'error': 'Agent name is required.'}), 400

        # Import and get global agents from container
        agents = get_global_agents()
        
        # Check that the agent exists
        found = any(a.get('name') == agent_name for a in agents)
        if not found:
            return jsonify({'error': 'Agent not found.'}), 404

        # Set global_selected_agent field only
        settings = get_settings()
        settings['global_selected_agent'] = { 'name': agent_name, 'is_global': True, 'is_group': False }
        update_settings(settings)
        log_event("Global selected agent set", extra={"action": "set-global-selected", "agent_name": agent_name, "user": str(get_current_user_id())})
        # --- HOT RELOAD TRIGGER ---
        setattr(builtins, "kernel_reload_needed", True)
        return jsonify({'success': True})
    except Exception as e:
        log_event(f"Error setting default agent: {e}", level=logging.ERROR)
        return jsonify({'error': 'Failed to set default agent.'}), 500


@bpa.route('/api/admin/agents', methods=['GET'])
@swagger_route(
    security=get_auth_security()
)
@login_required
@admin_required
def list_agents():
    try:
        # Use new global agents container
        agents = get_global_agents()
        
        # Ensure each agent has an actions_to_load field
        for agent in agents:
            if 'actions_to_load' not in agent:
                agent['actions_to_load'] = []
            # Mark as global agents
            agent['is_global'] = True
            agent['is_group'] = False
        
        log_event("List agents", extra={"action": "list", "user": str(get_current_user_id())})
        return jsonify(agents)
    except Exception as e:
        log_event(f"Error listing agents: {e}", level=logging.ERROR)
        return jsonify({'error': 'Failed to list agents.'}), 500


@bpa.route('/api/admin/agents/default-model-migration/preview', methods=['GET'])
@swagger_route(
    security=get_auth_security()
)
@login_required
@admin_required
def preview_default_model_agent_migration():
    settings = get_settings()
    if not settings.get('enable_semantic_kernel', False):
        return jsonify({'error': 'Enable Agents before using default-model review.'}), 400
    if not settings.get('enable_multi_model_endpoints', False):
        return jsonify({'error': 'Multi-endpoint model management is not enabled.'}), 400

    preview = _build_default_model_agent_migration_preview(settings)
    return jsonify({key: value for key, value in preview.items() if key != 'records'})


@bpa.route('/api/admin/agents/default-model-migration/run', methods=['POST'])
@swagger_route(
    security=get_auth_security()
)
@login_required
@admin_required
def run_default_model_agent_migration():
    settings = get_settings()
    if not settings.get('enable_semantic_kernel', False):
        return jsonify({'error': 'Enable Agents before using default-model review.'}), 400
    if not settings.get('enable_multi_model_endpoints', False):
        return jsonify({'error': 'Multi-endpoint model management is not enabled.'}), 400

    request_data = request.get_json(silent=True) or {}
    requested_keys = []
    for value in request_data.get('selected_agent_keys', []) or []:
        key = str(value or '').strip()
        if key and key not in requested_keys:
            requested_keys.append(key)

    preview = _build_default_model_agent_migration_preview(settings)
    default_model = preview['default_model']
    if not default_model['valid']:
        return jsonify({
            'error': 'A saved default model is required before migrating agents.',
            'preview': {key: value for key, value in preview.items() if key != 'records'},
        }), 400

    selectable_records = {
        record['selection_key']: record
        for record in preview['records']
        if record.get('can_select')
    }

    invalid_requested_keys = [key for key in requested_keys if key not in selectable_records]
    if invalid_requested_keys:
        return jsonify({
            'error': 'One or more selected agents cannot be migrated to the saved default model.',
            'invalid_selected_agent_keys': invalid_requested_keys,
            'preview': {key: value for key, value in preview.items() if key != 'records'},
        }), 400

    if requested_keys:
        candidates = [selectable_records[key] for key in requested_keys]
    else:
        candidates = [record for record in preview['records'] if record.get('selected_by_default')]

    if not candidates:
        return jsonify({
            'error': 'Select at least one eligible agent to migrate.',
            'preview': {key: value for key, value in preview.items() if key != 'records'},
        }), 400

    migrated_by_scope = {
        'global': 0,
        'group': 0,
        'personal': 0,
    }
    failures = []
    admin_user_id = str(get_current_user_id() or '')
    admin_profile = session.get('user', {}) or {}
    admin_email = admin_profile.get('preferred_username', admin_profile.get('email', 'unknown'))
    override_count = sum(record.get('migration_status') == 'manual_review' for record in candidates)

    for record in candidates:
        scope = record['scope']
        scope_id = record['scope_id']
        agent = dict(record['_raw_agent'])
        if record.get('migration_action') == 'force_override_to_default':
            agent = _clear_legacy_agent_connection_override(agent)
        agent['model_endpoint_id'] = default_model['endpoint_id']
        agent['model_id'] = default_model['model_id']
        agent['model_provider'] = default_model['provider']

        try:
            if scope == 'global':
                result = save_global_agent(agent, user_id=admin_user_id)
            elif scope == 'group':
                result = save_group_agent(scope_id, agent, user_id=admin_user_id)
            else:
                result = save_personal_agent(scope_id, agent, actor_user_id=admin_user_id)

            if not result:
                raise ValueError('Agent save did not return a result.')

            migrated_by_scope[scope] += 1
        except Exception as exc:
            log_event(
                f"Default-model migration failed for agent {record['agent_name']}: {exc}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            failures.append({
                'scope': scope,
                'scope_id': scope_id,
                'agent_id': record['agent_id'],
                'agent_name': record['agent_name'],
                'error': str(exc),
            })

    migrated_count = sum(migrated_by_scope.values())
    if migrated_count:
        setattr(builtins, 'kernel_reload_needed', True)

    refreshed_settings = get_settings()
    refreshed_preview = _build_default_model_agent_migration_preview(refreshed_settings)
    notice_cleared = _maybe_disable_multi_endpoint_migration_notice(refreshed_settings, refreshed_preview)
    if notice_cleared:
        refreshed_settings = get_settings()
        refreshed_preview = _build_default_model_agent_migration_preview(refreshed_settings)

    log_general_admin_action(
        admin_user_id=admin_user_id,
        admin_email=admin_email,
        action='Applied saved default model to selected agents',
        description=f'Applied the saved default model endpoint to {migrated_count} selected agents.',
        additional_context={
            'migrated_by_scope': migrated_by_scope,
            'failed_count': len(failures),
            'selected_agent_count': len(candidates),
            'override_count': override_count,
            'default_model_endpoint_id': default_model['endpoint_id'],
            'default_model_id': default_model['model_id'],
            'notice_cleared': notice_cleared,
        },
    )

    return jsonify({
        'success': len(failures) == 0,
        'selected_agent_count': len(candidates),
        'migrated_count': migrated_count,
        'override_count': override_count,
        'migrated_by_scope': migrated_by_scope,
        'failed': failures,
        'notice_cleared': notice_cleared,
        'preview': {key: value for key, value in refreshed_preview.items() if key != 'records'},
    })

@bpa.route('/api/admin/agents', methods=['POST'])
@swagger_route(
    security=get_auth_security()
)
@login_required
@admin_required
def add_agent():
    try:
        agents = get_global_agents()
        new_agent = request.json.copy() if hasattr(request.json, 'copy') else dict(request.json)
        try:
            cleaned_agent = sanitize_agent_payload(new_agent)
        except AgentPayloadError as exc:
            log_event("Add agent failed: payload error", level=logging.WARNING, extra={"action": "add", "error": str(exc)})
            return jsonify({'error': str(exc)}), 400
        cleaned_agent['is_global'] = True
        cleaned_agent['is_group'] = False
        validation_error = validate_agent(cleaned_agent)
        if validation_error:
            log_event("Add agent failed: validation error", level=logging.WARNING, extra={"action": "add", "agent": cleaned_agent, "error": validation_error})
            return jsonify({'error': validation_error}), 400
        # Prevent duplicate names (case-insensitive)
        if any(a['name'].lower() == cleaned_agent['name'].lower() for a in agents):
            log_event("Add agent failed: duplicate name", level=logging.WARNING, extra={"action": "add", "agent": cleaned_agent})
            return jsonify({'error': 'Agent with this name already exists.'}), 400
        # Assign a new GUID as id unless this is the default agent (which should have a static GUID)
        if not cleaned_agent.get('default_agent', False):
            cleaned_agent['id'] = str(uuid.uuid4())
        else:
            # If default_agent, ensure the static GUID is present (do not overwrite if already set)
            if not cleaned_agent.get('id'):
                cleaned_agent['id'] = '15b0c92a-741d-42ff-ba0b-367c7ee0c848'
        
        # Save to global agents container
        result = save_global_agent(cleaned_agent, user_id=str(get_current_user_id()))
        if not result:
            return jsonify({'error': 'Failed to save agent.'}), 500

        log_agent_creation(user_id=str(get_current_user_id()), agent_id=cleaned_agent.get('id', ''), agent_name=cleaned_agent.get('name', ''), agent_display_name=cleaned_agent.get('display_name', ''), scope='global')
        log_event("Agent added", extra={"action": "add", "agent": {k: v for k, v in cleaned_agent.items() if k != 'id'}, "user": str(get_current_user_id())})
        # --- HOT RELOAD TRIGGER ---
        setattr(builtins, "kernel_reload_needed", True)
        return jsonify({'success': True})
    except Exception as e:
        log_event(f"Error adding agent: {e}", level=logging.ERROR)
        return jsonify({'error': 'Failed to add agent.'}), 500

@bpa.route('/api/admin/agents/settings/<setting_name>', methods=['GET'])
@swagger_route(
    security=get_auth_security()
)
@login_required
@admin_required
def get_admin_agent_settings(setting_name):
    settings = get_settings()
    selected_value = settings.get(setting_name, {})
    return jsonify({setting_name: selected_value})

# Add a generic agent settings update route for simple values
@bpa.route('/api/admin/agents/settings/<setting_name>', methods=['POST'])
@swagger_route(
    security=get_auth_security()
)
@login_required
@admin_required
def update_agent_setting(setting_name):
    """
    Update a simple setting in the global settings.
    Supports dot notation for object properties (e.g., foo.bar).
    Only supports simple values (str, int, bool, float, None).
    """
    try:
        data = request.json
        if 'value' not in data:
            return jsonify({'error': 'Missing value in request.'}), 400
        value = data['value']
        settings = get_settings()
        keys = setting_name.split('.')
        target = settings
        for k in keys[:-1]:
            if k not in target or not isinstance(target[k], dict):
                return jsonify({'error': f'Cannot set nested property: {setting_name}'}), 400
            target = target[k]
        key = keys[-1]
        # Only allow simple types
        if isinstance(value, (str, int, float, bool)) or value is None:
            target[key] = value
        else:
            return jsonify({'error': 'Only simple values (str, int, float, bool, None) are allowed.'}), 400
        update_settings(settings)
        log_event("Agent setting updated", 
            extra={
                "setting": setting_name,
                "value": value,
                "user": str(get_current_user_id())
            }
        )
        setattr(builtins, "kernel_reload_needed", True)
        return jsonify({'success': True})
    except Exception as e:
        log_event(f"Error updating agent setting: {e}",
            level=logging.ERROR,
            exceptionTraceback=True
        )
        return jsonify({'error': 'Failed to update agent setting.'}), 500

@bpa.route('/api/admin/agents/<agent_name>', methods=['PUT'])
@swagger_route(
    security=get_auth_security()
)
@login_required
@admin_required
def edit_agent(agent_name):
    try:
        agents = get_global_agents()
        updated_agent = request.json.copy() if hasattr(request.json, 'copy') else dict(request.json)
        try:
            cleaned_agent = sanitize_agent_payload(updated_agent)
        except AgentPayloadError as exc:
            log_event("Edit agent failed: payload error", level=logging.WARNING, extra={"action": "edit", "agent_name": agent_name, "error": str(exc)})
            return jsonify({'error': str(exc)}), 400
        cleaned_agent['is_global'] = True
        cleaned_agent['is_group'] = False
        validation_error = validate_agent(cleaned_agent)
        if validation_error:
            log_event("Edit agent failed: validation error", level=logging.WARNING, extra={"action": "edit", "agent": cleaned_agent, "error": validation_error})
            return jsonify({'error': validation_error}), 400
        # --- Require at least one deployment field ---
        if not (cleaned_agent.get('azure_openai_gpt_deployment') or cleaned_agent.get('azure_agent_apim_gpt_deployment')):
            log_event("Edit agent failed: missing deployment field", level=logging.WARNING, extra={"action": "edit", "agent": cleaned_agent})
            return jsonify({'error': 'Agent must have either azure_openai_gpt_deployment or azure_agent_apim_gpt_deployment set.'}), 400
        
        # Find the agent to update
        agent_found = False
        for a in agents:
            if a['name'] == agent_name:
                # Preserve the existing id
                cleaned_agent['id'] = a.get('id')
                agent_found = True
                break
        
        if not agent_found:
            log_event("Edit agent failed: not found", level=logging.WARNING, extra={"action": "edit", "agent_name": agent_name})
            return jsonify({'error': 'Agent not found.'}), 404
        
        # Save the updated agent
        result = save_global_agent(cleaned_agent, user_id=str(get_current_user_id()))
        if not result:
            return jsonify({'error': 'Failed to save agent.'}), 500

        log_agent_update(user_id=str(get_current_user_id()), agent_id=cleaned_agent.get('id', ''), agent_name=agent_name, agent_display_name=cleaned_agent.get('display_name', ''), scope='global')
        log_event(
            f"Agent {agent_name} edited",
            extra={
                "action": "edit", 
                "agent": {k: v for k, v in cleaned_agent.items() if k != 'id'},
                "user": str(get_current_user_id()),
            }
        )
        # --- HOT RELOAD TRIGGER ---
        setattr(builtins, "kernel_reload_needed", True)
        return jsonify({'success': True})
    except Exception as e:
        log_event(f"Error editing agent: {e}", level=logging.ERROR, exceptionTraceback=True)
        return jsonify({'error': 'Failed to edit agent.'}), 500

@bpa.route('/api/admin/agents/<agent_name>', methods=['DELETE'])
@swagger_route(
    security=get_auth_security()
)
@login_required
@admin_required
def delete_agent(agent_name):
    try:
        agents = get_global_agents()
        
        # Find the agent to delete
        agent_to_delete = None
        for a in agents:
            if a['name'] == agent_name:
                agent_to_delete = a
                break
        
        if not agent_to_delete:
            log_event("Delete agent failed: not found", level=logging.WARNING, extra={"action": "delete", "agent_name": agent_name})
            return jsonify({'error': 'Agent not found.'}), 404
        
        # Delete the agent
        success = delete_global_agent(agent_to_delete['id'])
        if not success:
            return jsonify({'error': 'Failed to delete agent.'}), 500
        
        log_agent_deletion(user_id=str(get_current_user_id()), agent_id=agent_to_delete.get('id', ''), agent_name=agent_name, scope='global')
        log_event("Agent deleted", extra={"action": "delete", "agent_name": agent_name, "user": str(get_current_user_id())})
        # --- HOT RELOAD TRIGGER ---
        setattr(builtins, "kernel_reload_needed", True)
        return jsonify({'success': True})
    except Exception as e:
        log_event(f"Error deleting agent: {e}", level=logging.ERROR,exceptionTraceback=True)
        return jsonify({'error': 'Failed to delete agent.'}), 500

@bpa.route('/api/orchestration_types', methods=['GET'])
@swagger_route(
    security=get_auth_security()
)
@login_required
@admin_required
def orchestration_types():
    """Return the available orchestration types (full metadata)."""
    return jsonify(get_agent_orchestration_types())

@bpa.route('/api/orchestration_settings', methods=['GET', 'POST'])
@swagger_route(
    security=get_auth_security()
)
@login_required
@admin_required
def orchestration_settings():
    if request.method == 'GET':
        settings = get_settings()
        return jsonify({
            "orchestration_type": settings.get("orchestration_type"),
            "enable_multi_agent_orchestration": settings.get("enable_multi_agent_orchestration"),
            "max_rounds_per_agent": settings.get("max_rounds_per_agent"),
        })
    else:
        try:
            data = request.json
            types = get_agent_orchestration_types()
            # Validate input
            orchestration_type = data.get("orchestration_type")
            enable_multi = None
            max_rounds = data.get("max_rounds_per_agent")
            matched_type = next((t for t in types if t.get("value") == orchestration_type), None)
            if matched_type['agent_mode'] == 'multi':
                enable_multi = True
            else:
                enable_multi = False
            if orchestration_type == "group_chat":
                if not isinstance(max_rounds, int) or max_rounds <= 0:
                    return jsonify({"error": "max_rounds_per_agent must be an integer > 0 for group_chat."}), 400
            
            # Save settings
            settings = get_settings()
            settings["orchestration_type"] = orchestration_type
            settings["enable_multi_agent_orchestration"] = enable_multi
            if orchestration_type == "group_chat":
                settings["max_rounds_per_agent"] = max_rounds
            else:
                settings["max_rounds_per_agent"] = 1
            update_settings(settings)
            # --- HOT RELOAD TRIGGER ---
            setattr(builtins, "kernel_reload_needed", True)
            return jsonify({'success': True})
        except Exception as e:
            log_event(f"Error updating orchestration settings: {e}", level=logging.ERROR, exceptionTraceback=True)
            return jsonify({'error': 'Failed to update orchestration settings.'}), 500

def build_combined_model_endpoints(settings, user_id=None, group_id=None):
    endpoints = []
    global_endpoints = settings.get("model_endpoints", []) or []
    for endpoint in global_endpoints:
        enriched = dict(endpoint)
        enriched["scope"] = "global"
        endpoints.append(enriched)

    allow_user_custom_endpoints = settings.get("allow_user_custom_endpoints", False)
    allow_group_custom_endpoints = settings.get("allow_group_custom_endpoints", False)

    if group_id:
        if allow_group_custom_endpoints:
            group_endpoints = get_group_model_endpoints(group_id)
            for endpoint in group_endpoints:
                enriched = dict(endpoint)
                enriched["scope"] = "group"
                enriched["group_id"] = group_id
                endpoints.append(enriched)
    elif user_id:
        if allow_user_custom_endpoints:
            user_settings = get_user_settings(user_id)
            personal = user_settings.get("settings", {}).get("personal_model_endpoints", [])
            for endpoint in personal:
                enriched = dict(endpoint)
                enriched["scope"] = "user"
                endpoints.append(enriched)

    return sanitize_model_endpoints_for_frontend(endpoints)


def get_global_agent_settings(include_admin_extras=False, user_id=None, group_id=None):    
    settings = get_settings()
    agents = get_global_agents()
    combined_endpoints = []
    base_endpoints = settings.get("model_endpoints", []) or []
    multi_flag = settings.get("enable_multi_model_endpoints", False)
    allow_custom = settings.get("allow_user_custom_endpoints", False) or settings.get("allow_group_custom_endpoints", False)
    should_include_endpoints = multi_flag or base_endpoints or allow_custom

    if should_include_endpoints:
        combined_endpoints = build_combined_model_endpoints(settings, user_id=user_id, group_id=group_id)

    effective_multi_flag = bool(multi_flag or combined_endpoints)
    
    # Return selected_agent and any other relevant settings for admin UI
    return jsonify({
        "semantic_kernel_agents": agents,
        "orchestration_type": settings.get("orchestration_type", "default_agent"),
        "enable_multi_agent_orchestration": settings.get("enable_multi_agent_orchestration", False),
        "max_rounds_per_agent": settings.get("max_rounds_per_agent", 1),
        "per_user_semantic_kernel": settings.get("per_user_semantic_kernel", False),
        "enable_time_plugin": settings.get("enable_time_plugin", False),
        "enable_fact_memory_plugin": settings.get("enable_fact_memory_plugin", False),
        "enable_math_plugin": settings.get("enable_math_plugin", False),
        "enable_text_plugin": settings.get("enable_text_plugin", False),
        "enable_http_plugin": settings.get("enable_http_plugin", False),
        "enable_wait_plugin": settings.get("enable_wait_plugin", False),
        "enable_default_embedding_model_plugin": settings.get("enable_default_embedding_model_plugin", False),
        "global_selected_agent": settings.get("global_selected_agent", {}),
        "merge_global_semantic_kernel_with_workspace": settings.get("merge_global_semantic_kernel_with_workspace", False),
        "enable_gpt_apim": settings.get("enable_gpt_apim", False),
        "azure_apim_gpt_deployment": settings.get("azure_apim_gpt_deployment", ""),
        "gpt_model": settings.get("gpt_model", {}),
        "allow_user_agents": settings.get("allow_user_agents", False),
        "allow_user_custom_endpoints": settings.get("allow_user_custom_endpoints", False),
        "allow_group_agents": settings.get("allow_group_agents", False),
        "allow_group_custom_endpoints": settings.get("allow_group_custom_endpoints", False),
        "allow_ai_foundry_agents": settings.get("allow_ai_foundry_agents", False),
        "allow_group_ai_foundry_agents": settings.get("allow_group_ai_foundry_agents", False),
        "allow_personal_ai_foundry_agents": settings.get("allow_personal_ai_foundry_agents", False),
        "allow_new_foundry_agents": settings.get("allow_new_foundry_agents", False),
        "allow_group_new_foundry_agents": settings.get("allow_group_new_foundry_agents", False),
        "allow_personal_new_foundry_agents": settings.get("allow_personal_new_foundry_agents", False),
        "enable_multi_model_endpoints": effective_multi_flag,
        "model_endpoints": combined_endpoints,
    })
    