# route_migration.py

"""
Migration endpoints for moving data from user settings to personal containers.
"""

import logging

from flask import Blueprint, jsonify
from functions_authentication import get_current_user_id, login_required, user_required, user_required_blueprint
from functions_personal_agents import migrate_agents_from_user_settings, get_personal_agents
from functions_personal_actions import (
    get_action_migration_status,
    get_personal_actions,
    list_legacy_personal_actions,
    migrate_actions_from_user_settings,
)
from functions_settings import get_user_settings, update_user_settings
from functions_keyvault import redact_plugin_secret_values
from functions_appinsights import log_event
from swagger_wrapper import swagger_route, get_auth_security

bp_migration = Blueprint('migration', __name__)
bp_migration.before_request(user_required_blueprint())

@bp_migration.route('/api/migrate/agents', methods=['POST'])
@swagger_route(
    security=get_auth_security()
)
@login_required
@user_required
def migrate_user_agents():
    """Migrate user agents from user settings to personal_agents container."""
    user_id = get_current_user_id()
    
    try:
        migrated_count = migrate_agents_from_user_settings(user_id)
        agents = get_personal_agents(user_id)
        
        log_event("[USER_SETTINGS] User agents migrated", extra={
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
        
    except Exception as exc:
        log_event("[USER_SETTINGS] Agent migration failed", level=logging.ERROR,
                  extra={"user_id": user_id, "error_type": type(exc).__name__})
        return jsonify({'error': 'Failed to migrate agents'}), 500

@bp_migration.route('/api/migrate/actions', methods=['POST'])
@swagger_route(
    security=get_auth_security()
)
@login_required
@user_required
def migrate_user_actions():
    """Migrate user actions/plugins from user settings to personal_actions container."""
    user_id = get_current_user_id()
    
    try:
        outcome = migrate_actions_from_user_settings(user_id)
        actions = [redact_plugin_secret_values(action) for action in get_personal_actions(user_id)]
        legacy_actions = list_legacy_personal_actions(user_id)
        
        log_event("[PLUGINS] User action migration processed", extra={
            "user_id": user_id, 
            "migrated_count": outcome["migrated_count"],
            "retained_count": outcome["retained_count"],
            "failed_count": outcome["failed_count"],
            "total_actions": len(actions)
        })
        
        return jsonify({
            **outcome,
            'success': outcome["complete"] and outcome["failed_count"] == 0,
            'total_actions': len(actions),
            'actions': actions + legacy_actions,
            'action_migration': outcome,
        })
        
    except PermissionError:
        return jsonify({'error': 'You are not authorized to migrate these actions.'}), 403
    except Exception as exc:
        log_event("[PLUGINS] User action migration failed", level=logging.ERROR,
                  extra={"user_id": user_id, "error_type": type(exc).__name__})
        return jsonify({'error': 'Failed to migrate actions'}), 500

@bp_migration.route('/api/migrate/all', methods=['POST'])
@swagger_route(
    security=get_auth_security()
)
@login_required
@user_required
def migrate_all_user_data():
    """Migrate both agents and actions from user settings to personal containers."""
    user_id = get_current_user_id()
    
    try:
        agents_migrated = migrate_agents_from_user_settings(user_id)
        action_outcome = migrate_actions_from_user_settings(user_id)
        
        user_settings = get_user_settings(user_id)
        if user_settings.get('settings', {}).get('agents'):
            agents_cleared = update_user_settings(user_id, {'agents': []})
            if not agents_cleared:
                return jsonify({'error': 'Failed to finish agent migration.'}), 500
        
        agents = get_personal_agents(user_id)
        actions = [redact_plugin_secret_values(action) for action in get_personal_actions(user_id)]
        legacy_actions = list_legacy_personal_actions(user_id)
        
        log_event("[USER_SETTINGS] User migration processed", extra={
            "user_id": user_id, 
            "agents_migrated": agents_migrated,
            "actions_migrated": action_outcome["migrated_count"],
            "actions_retained": action_outcome["retained_count"],
            "actions_failed": action_outcome["failed_count"],
            "total_agents": len(agents),
            "total_actions": len(actions)
        })
        
        return jsonify({
            'success': action_outcome["complete"] and action_outcome["failed_count"] == 0,
            'agents_migrated': agents_migrated,
            'actions_migrated': action_outcome["migrated_count"],
            'actions_retained': action_outcome["retained_count"],
            'actions_failed': action_outcome["failed_count"],
            'action_migration': action_outcome,
            'migration_complete': action_outcome["complete"],
            'total_agents': len(agents),
            'total_actions': len(actions),
            'agents': agents,
            'actions': actions + legacy_actions,
        })
        
    except PermissionError:
        return jsonify({'error': 'You are not authorized to migrate these actions.'}), 403
    except Exception as exc:
        log_event("[USER_SETTINGS] User migration failed", level=logging.ERROR,
                  extra={"user_id": user_id, "error_type": type(exc).__name__})
        return jsonify({'error': 'Failed to migrate user data'}), 500

@bp_migration.route('/api/migrate/status', methods=['GET'])
@swagger_route(
    security=get_auth_security()
)
@login_required
@user_required
def get_migration_status():
    """Check migration status and current data in personal containers."""
    user_id = get_current_user_id()
    
    try:
        # Check current user settings
        user_settings = get_user_settings(user_id).get('settings', {})
        legacy_agents = user_settings.get('agents', [])
        action_status = get_action_migration_status(user_id)
        
        # Check personal containers
        personal_agents = get_personal_agents(user_id)
        personal_actions = [redact_plugin_secret_values(action) for action in get_personal_actions(user_id)]
        
        return jsonify({
            'legacy_data': {
                'agents_count': len(legacy_agents),
                'actions_count': action_status["total_count"],
                'actions_pending_count': action_status["pending_count"],
                'actions_retained_count': action_status["retained_count"],
                'actions_unsupported_count': action_status["retired_count"],
                'actions_failed_count': action_status["failed_count"],
                'agents': legacy_agents,
                'actions': action_status["actions"],
            },
            'personal_containers': {
                'agents_count': len(personal_agents),
                'actions_count': len(personal_actions),
                'agents': personal_agents,
                'actions': personal_actions
            },
            'action_migration': action_status,
            'migration_needed': len(legacy_agents) > 0 or not action_status["complete"],
        })
        
    except PermissionError:
        return jsonify({'error': 'You are not authorized to view this migration status.'}), 403
    except Exception as exc:
        log_event("[USER_SETTINGS] Migration status lookup failed", level=logging.ERROR,
                  extra={"user_id": user_id, "error_type": type(exc).__name__})
        return jsonify({'error': 'Failed to check migration status'}), 500
