# route_migration.py

"""
Migration endpoints for moving data from user settings to personal containers.
"""

from flask import Blueprint, jsonify, request
from functions_authentication import login_required, get_current_user_id
from functions_personal_agents import migrate_agents_from_user_settings, get_personal_agents
from functions_personal_actions import migrate_actions_from_user_settings, get_personal_actions
from functions_appinsights import log_event
from swagger_wrapper import swagger_route, get_auth_security
import logging

bp_migration = Blueprint('migration', __name__)

@bp_migration.route('/api/migrate/agents', methods=['POST'])
@swagger_route(
    security=get_auth_security()
)
@login_required
def migrate_user_agents():
    """Migrate user agents from user settings to personal_agents container."""
    user_id = get_current_user_id()
    
    try:
        migrated_count = migrate_agents_from_user_settings(user_id)
        agents = get_personal_agents(user_id)
        
        log_event("User agents migrated", extra={
            "user_id": user_id, 
            "migrated_count": migrated_count,
            "total_agents": len(agents)
        })
        
        return jsonify({
            'success': True,
            'migrated_count': migrated_count,
            'total_agents': len(agents),
            'agents': agents
        })
        
    except Exception as e:
        log_event(f"Error migrating user agents: {e}", level=logging.ERROR, exceptionTraceback=True)
        return jsonify({'error': 'Failed to migrate agents'}), 500

@bp_migration.route('/api/migrate/actions', methods=['POST'])
@swagger_route(
    security=get_auth_security()
)
@login_required
def migrate_user_actions():
    """Migrate user actions/plugins from user settings to personal_actions container."""
    user_id = get_current_user_id()
    
    try:
        migrated_count = migrate_actions_from_user_settings(user_id)
        actions = get_personal_actions(user_id)
        
        log_event("User actions migrated", extra={
            "user_id": user_id, 
            "migrated_count": migrated_count,
            "total_actions": len(actions)
        })
        
        return jsonify({
            'success': True,
            'migrated_count': migrated_count,
            'total_actions': len(actions),
            'actions': actions
        })
        
    except Exception as e:
        log_event(f"Error migrating user actions: {e}", level=logging.ERROR, exceptionTraceback=True)
        return jsonify({'error': 'Failed to migrate actions'}), 500

@bp_migration.route('/api/migrate/all', methods=['POST'])
@swagger_route(
    security=get_auth_security()
)
@login_required
def migrate_all_user_data():
    """Migrate both agents and actions from user settings to personal containers."""
    user_id = get_current_user_id()
    
    try:
        agents_migrated = migrate_agents_from_user_settings(user_id)
        actions_migrated = migrate_actions_from_user_settings(user_id)
        
        # Force clear any remaining legacy data in user settings
        from functions_settings import get_user_settings, update_user_settings
        user_settings = get_user_settings(user_id)
        settings_to_update = user_settings.get('settings', {})
        
        # Set legacy data to empty arrays instead of removing keys
        legacy_cleared = False
        if settings_to_update.get('agents'):
            settings_to_update['agents'] = []
            legacy_cleared = True
        if settings_to_update.get('plugins'):
            settings_to_update['plugins'] = []
            legacy_cleared = True
            
        if legacy_cleared:
            update_user_settings(user_id, settings_to_update)
            log_event(f"Forced clearing of legacy data for user {user_id}")
        
        agents = get_personal_agents(user_id)
        actions = get_personal_actions(user_id)
        
        log_event("All user data migrated", extra={
            "user_id": user_id, 
            "agents_migrated": agents_migrated,
            "actions_migrated": actions_migrated,
            "total_agents": len(agents),
            "total_actions": len(actions)
        })
        
        return jsonify({
            'success': True,
            'agents_migrated': agents_migrated,
            'actions_migrated': actions_migrated,
            'total_agents': len(agents),
            'total_actions': len(actions),
            'agents': agents,
            'actions': actions
        })
        
    except Exception as e:
        log_event(f"Error migrating all user data: {e}", level=logging.ERROR, exceptionTraceback=True)
        return jsonify({'error': 'Failed to migrate user data'}), 500

@bp_migration.route('/api/migrate/status', methods=['GET'])
@swagger_route(
    security=get_auth_security()
)
@login_required
def get_migration_status():
    """Check migration status and current data in personal containers."""
    user_id = get_current_user_id()
    
    try:
        from functions_settings import get_user_settings
        
        # Check current user settings
        user_settings = get_user_settings(user_id).get('settings', {})
        legacy_agents = user_settings.get('agents', [])
        legacy_actions = user_settings.get('plugins', [])
        
        # Check personal containers
        personal_agents = get_personal_agents(user_id)
        personal_actions = get_personal_actions(user_id)
        
        return jsonify({
            'legacy_data': {
                'agents_count': len(legacy_agents),
                'actions_count': len(legacy_actions),
                'agents': legacy_agents,
                'actions': legacy_actions
            },
            'personal_containers': {
                'agents_count': len(personal_agents),
                'actions_count': len(personal_actions),
                'agents': personal_agents,
                'actions': personal_actions
            },
            'migration_needed': len(legacy_agents) > 0 or len(legacy_actions) > 0
        })
        
    except Exception as e:
        log_event(f"Error checking migration status: {e}", level=logging.ERROR, exceptionTraceback=True)
        return jsonify({'error': 'Failed to check migration status'}), 500
