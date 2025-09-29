# route_backend_agents.py

import re
import uuid
import logging
import builtins
from flask import Blueprint, jsonify, request
from semantic_kernel_loader import get_agent_orchestration_types
from functions_settings import get_settings, update_settings, get_user_settings, update_user_settings
from functions_global_agents import get_global_agents, save_global_agent, delete_global_agent
from functions_authentication import *
from functions_appinsights import log_event
from json_schema_validation import validate_agent
from swagger_wrapper import swagger_route, get_auth_security

bpa = Blueprint('admin_agents', __name__)

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
    user_id = get_current_user_id()
    
    # Import the new personal agents functions
    from functions_personal_agents import get_personal_agents, ensure_migration_complete
    
    # Ensure migration is complete (will migrate any remaining legacy data)
    ensure_migration_complete(user_id)
    
    # Get agents from the new personal_agents container
    agents = get_personal_agents(user_id)
    
    # Always mark user agents as is_global: False
    for agent in agents:
        agent['is_global'] = False

    # Check global/merge toggles
    settings = get_settings()
    per_user = settings.get('per_user_semantic_kernel', False)
    merge_global = settings.get('merge_global_semantic_kernel_with_workspace', False)
    if per_user and merge_global:
        # Import and get global agents from container
        from functions_global_agents import get_global_agents
        global_agents = get_global_agents()
        # Mark global agents
        for agent in global_agents:
            agent['is_global'] = True
        
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

    # Import the new personal agents functions
    from functions_personal_agents import save_personal_agent, delete_personal_agent, get_personal_agents
    
    # If custom endpoints are not allowed, strip deployment settings for endpoint, key, and api-revision
    if not settings.get('allow_user_custom_agent_endpoints', False):
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
        agent['is_global'] = False  # Ensure user agents are not global
        # --- Require at least one deployment field ---
        #if not (agent.get('azure_openai_gpt_deployment') or agent.get('azure_agent_apim_gpt_deployment')):
        #    return jsonify({'error': f'Agent "{agent.get("name", "(unnamed)")}" must have either azure_openai_gpt_deployment or azure_agent_apim_gpt_deployment set.'}), 400
        validation_error = validate_agent(agent)
        if validation_error:
            return jsonify({'error': f'Agent validation failed: {validation_error}'}), 400
        filtered_agents.append(agent)

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
    
    # Import the new personal agents functions
    from functions_personal_agents import get_personal_agents, delete_personal_agent
    
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
    
    # Check if there are any agents left and if they match global_selected_agent
    remaining_agents = get_personal_agents(user_id)
    if len(remaining_agents) > 0:
        found = any(a.get('name') == global_selected_name for a in remaining_agents)
        if not found:
            return jsonify({'error': 'There must be at least one agent matching the global_selected_agent.'}), 400
  
    log_event("User agent deleted", extra={"user_id": user_id, "agent_name": agent_name})
    return jsonify({'success': True})

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
    user_settings = get_user_settings(user_id)
    settings_to_update = user_settings.get('settings', {})
    agent = {
        "name": selected_agent.get('name'),
        "is_global": selected_agent.get('is_global', False)
    }
    settings_to_update['selected_agent'] = agent
    update_user_settings(user_id, settings_to_update)
    log_event("User selected agent set", extra={"user_id": user_id, "selected_agent": selected_agent})
    return jsonify({'success': True})

@bpa.route('/api/user/agent/settings', methods=['GET'])
@swagger_route(
    security=get_auth_security()
)
@login_required
def get_global_agent_settings_for_users():
    return get_global_agent_settings(include_admin_extras=False)

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
        from functions_global_agents import get_global_agents
        agents = get_global_agents()
        
        # Check that the agent exists
        found = any(a.get('name') == agent_name for a in agents)
        if not found:
            return jsonify({'error': 'Agent not found.'}), 404

        # Set global_selected_agent field only
        settings = get_settings()
        settings['global_selected_agent'] = { 'name': agent_name, 'is_global': True }
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
        from functions_global_agents import get_global_agents
        
        agents = get_global_agents()
        
        # Ensure each agent has an actions_to_load field
        for agent in agents:
            if 'actions_to_load' not in agent:
                agent['actions_to_load'] = []
            # Mark as global agents
            agent['is_global'] = True
        
        log_event("List agents", extra={"action": "list", "user": str(get_current_user_id())})
        return jsonify(agents)
    except Exception as e:
        log_event(f"Error listing agents: {e}", level=logging.ERROR)
        return jsonify({'error': 'Failed to list agents.'}), 500

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
        new_agent['is_global'] = True
        validation_error = validate_agent(new_agent)
        if validation_error:
            log_event("Add agent failed: validation error", level=logging.WARNING, extra={"action": "add", "agent": new_agent, "error": validation_error})
            return jsonify({'error': validation_error}), 400
        # Prevent duplicate names (case-insensitive)
        if any(a['name'].lower() == new_agent['name'].lower() for a in agents):
            log_event("Add agent failed: duplicate name", level=logging.WARNING, extra={"action": "add", "agent": new_agent})
            return jsonify({'error': 'Agent with this name already exists.'}), 400
        # Assign a new GUID as id unless this is the default agent (which should have a static GUID)
        if not new_agent.get('default_agent', False):
            new_agent['id'] = str(uuid.uuid4())
        else:
            # If default_agent, ensure the static GUID is present (do not overwrite if already set)
            if not new_agent.get('id'):
                new_agent['id'] = '15b0c92a-741d-42ff-ba0b-367c7ee0c848'
        
        # Save to global agents container
        result = save_global_agent(new_agent)
        if not result:
            return jsonify({'error': 'Failed to save agent.'}), 500
        
        # Enforce that if there are agents, one must match global_selected_agent
        settings = get_settings()
        global_selected_agent = settings.get('global_selected_agent', {})
        global_selected_name = global_selected_agent.get('name')
        updated_agents = get_global_agents()
        if len(updated_agents) > 0:
            found = any(a.get('name') == global_selected_name for a in updated_agents)
            if not found:
                return jsonify({'error': 'There must be at least one agent matching the global_selected_agent.'}), 400
        
        log_event("Agent added", extra={"action": "add", "agent": {k: v for k, v in new_agent.items() if k != 'id'}, "user": str(get_current_user_id())})
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
        from functions_global_agents import get_global_agents, save_global_agent
        
        agents = get_global_agents()
        updated_agent = request.json.copy() if hasattr(request.json, 'copy') else dict(request.json)
        updated_agent['is_global'] = True
        validation_error = validate_agent(updated_agent)
        if validation_error:
            log_event("Edit agent failed: validation error", level=logging.WARNING, extra={"action": "edit", "agent": updated_agent, "error": validation_error})
            return jsonify({'error': validation_error}), 400
        # --- Require at least one deployment field ---
        if not (updated_agent.get('azure_openai_gpt_deployment') or updated_agent.get('azure_agent_apim_gpt_deployment')):
            log_event("Edit agent failed: missing deployment field", level=logging.WARNING, extra={"action": "edit", "agent": updated_agent})
            return jsonify({'error': 'Agent must have either azure_openai_gpt_deployment or azure_agent_apim_gpt_deployment set.'}), 400
        
        # Find the agent to update
        agent_found = False
        for a in agents:
            if a['name'] == agent_name:
                # Preserve the existing id
                updated_agent['id'] = a.get('id')
                agent_found = True
                break
        
        if not agent_found:
            log_event("Edit agent failed: not found", level=logging.WARNING, extra={"action": "edit", "agent_name": agent_name})
            return jsonify({'error': 'Agent not found.'}), 404
        
        # Save the updated agent
        result = save_global_agent(updated_agent)
        if not result:
            return jsonify({'error': 'Failed to save agent.'}), 500
        
        # Enforce that if there are agents, one must match global_selected_agent
        settings = get_settings()
        global_selected_agent = settings.get('global_selected_agent', {})
        global_selected_name = global_selected_agent.get('name')
        updated_agents = get_global_agents()
        if len(updated_agents) > 0:
            found = any(a.get('name') == global_selected_name for a in updated_agents)
            if not found:
                return jsonify({'error': 'There must be at least one agent matching the global_selected_agent.'}), 400
        
        log_event(
            f"Agent {agent_name} edited",
            extra={
                "action": "edit", 
                "agent": {k: v for k, v in updated_agent.items() if k != 'id'},
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
        from functions_global_agents import get_global_agents, delete_global_agent
        
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

def get_global_agent_settings(include_admin_extras=False):
    from functions_global_agents import get_global_agents
    
    settings = get_settings()
    agents = get_global_agents()
    
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
        "allow_user_custom_agent_endpoints": settings.get("allow_user_custom_agent_endpoints", False),
        "allow_group_agents": settings.get("allow_group_agents", False),
        "allow_group_custom_agent_endpoints": settings.get("allow_group_custom_agent_endpoints", False),
    })
    