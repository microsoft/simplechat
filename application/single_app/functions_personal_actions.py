# functions_personal_actions.py

"""
Personal Actions (Plugins) Management

This module handles all operations related to personal actions/plugins stored in the 
personal_actions container with user_id partitioning.
"""

import uuid
import hashlib
from copy import deepcopy
from datetime import datetime
from azure.core import MatchConditions
from azure.cosmos import exceptions
from flask import current_app
from functions_keyvault import keyvault_plugin_save_helper, keyvault_plugin_get_helper, keyvault_plugin_delete_helper, SecretReturnType
from functions_settings import get_user_settings, update_user_settings
import functions_settings
from functions_workspace_identities import (
    WORKSPACE_IDENTITY_SCOPE_PERSONAL,
    hydrate_action_identity_reference,
    validate_action_identity_reference,
)
from functions_debug import debug_print
from config import cosmos_personal_actions_container, cosmos_user_settings_container
import logging
from functions_appinsights import log_event
from functions_governance import ensure_action_type_access, filter_actions_by_action_type_access
from functions_chat_bootstrap_cache import bump_chat_bootstrap_user_cache_version
from json_schema_validation import (
    ACTION_MIGRATION_ID_PREFIX,
    is_legacy_msgraph_type,
    normalize_m365_action_payload,
    validate_legacy_action_update,
)


def _is_action_migration_record(action):
    return bool(action.get('_action_migration')) or str(action.get('id') or '').startswith(ACTION_MIGRATION_ID_PREFIX)


def get_governed_personal_actions(user_id, return_type=SecretReturnType.TRIGGER):
    """
    Fetch personal actions only after the current user passes governance checks.

    Args:
        user_id (str): The user's unique identifier

    Returns:
        list: List of action/plugin dictionaries
    """
    actions = get_personal_actions(user_id, return_type=return_type)
    return filter_actions_by_action_type_access(user_id, actions, 'governance_user_actions', 'personal')

def get_personal_actions(user_id, return_type=SecretReturnType.TRIGGER):
    """
    Fetch all personal actions/plugins for a user.
    
    Args:
        user_id (str): The user's unique identifier
        
    Returns:
        list: List of action/plugin dictionaries
    """
    try:
        query = "SELECT * FROM c WHERE c.user_id = @user_id"
        parameters = [{"name": "@user_id", "value": user_id}]
        
        actions = list(cosmos_personal_actions_container.query_items(
            query=query,
            parameters=parameters,
            partition_key=user_id
        ))
        
        # Remove Cosmos metadata for cleaner response and resolve Key Vault references
        cleaned_actions = []
        for action in actions:
            if _is_action_migration_record(action):
                continue
            cleaned_action = {k: v for k, v in action.items() if not k.startswith('_')}
            cleaned_action = keyvault_plugin_get_helper(cleaned_action, scope_value=user_id, scope="user", return_type=return_type)
            cleaned_action = hydrate_action_identity_reference(
                cleaned_action,
                WORKSPACE_IDENTITY_SCOPE_PERSONAL,
                user_id,
                return_type=return_type,
            )
            cleaned_actions.append(cleaned_action)
        return cleaned_actions
        
    except exceptions.CosmosResourceNotFoundError:
        return []
    except Exception as e:
        debug_print(f"Error fetching personal actions for user {user_id}: {e}")
        return []

def get_personal_action(user_id, action_id, return_type=SecretReturnType.TRIGGER):
    """
    Fetch a specific personal action/plugin.
    
    Args:
        user_id (str): The user's unique identifier
        action_id (str): The action's unique identifier (can be name or UUID)
        
    Returns:
        dict: Action dictionary or None if not found
    """
    try:
        try:
            action = cosmos_personal_actions_container.read_item(
                item=action_id,
                partition_key=user_id
            )
        except exceptions.CosmosResourceNotFoundError:
            # If not found by ID, try to find by name
            query = "SELECT * FROM c WHERE c.user_id = @user_id AND c.name = @name"
            parameters = [
                {"name": "@user_id", "value": user_id},
                {"name": "@name", "value": action_id}
            ]
            
            actions = list(cosmos_personal_actions_container.query_items(
                query=query,
                parameters=parameters,
                partition_key=user_id
            ))
            
            if not actions:
                return None
            action = actions[0]
        
        if _is_action_migration_record(action):
            log_event(
                "[USER_SETTINGS] Internal action migration record excluded from action lookup.",
                level=logging.WARNING,
                extra={"user_id": user_id},
            )
            return None

        # Remove Cosmos metadata and resolve Key Vault references
        cleaned_action = {k: v for k, v in action.items() if not k.startswith('_')}
        cleaned_action = keyvault_plugin_get_helper(cleaned_action, scope_value=user_id, scope="user", return_type=return_type)
        cleaned_action = hydrate_action_identity_reference(
            cleaned_action,
            WORKSPACE_IDENTITY_SCOPE_PERSONAL,
            user_id,
            return_type=return_type,
        )
        return cleaned_action
        
    except Exception as e:
        debug_print(f"Error fetching action {action_id} for user {user_id}: {e}")
        return None

def save_personal_action(user_id, action_data, enforce_governance=True):
    """
    Save or update a personal action/plugin.
    
    Args:
        user_id (str): The user's unique identifier
        action_data (dict): Action configuration data
        
    Returns:
        dict: Saved action data with ID
    """
    try:
        action_data = deepcopy(action_data)
        action_data = normalize_m365_action_payload(action_data)
        legacy_type = is_legacy_msgraph_type(action_data.get('type'))
        existing_action = None
        if action_data.get('id'):
            try:
                existing_action = cosmos_personal_actions_container.read_item(
                    item=action_data['id'],
                    partition_key=user_id,
                )
            except exceptions.CosmosResourceNotFoundError:
                pass
        validate_legacy_action_update(action_data, existing_action, 'user_id', user_id)
        if legacy_type:
            action_data['type'] = 'msgraph'
        if not legacy_type and 'name' in action_data and action_data['name']:
            existing_action = existing_action or get_personal_action(
                user_id,
                action_data['name'],
                return_type=SecretReturnType.NAME,
            )
        
        # Preserve existing ID if updating, or generate new ID if creating
        now = datetime.utcnow().isoformat()
        if existing_action:
            # Update existing action - preserve the original ID and creation tracking
            action_data['id'] = existing_action['id']
            action_data['created_by'] = existing_action.get('created_by', user_id)
            action_data['created_at'] = existing_action.get('created_at', now)
        elif 'id' not in action_data or not action_data['id']:
            # New action - generate UUID for ID
            action_data['id'] = str(uuid.uuid4())
            action_data['created_by'] = user_id
            action_data['created_at'] = now
        else:
            # Has an ID but no existing action found - treat as new
            action_data['created_by'] = user_id
            action_data['created_at'] = now
        action_data['modified_by'] = user_id
        action_data['modified_at'] = now

        action_data['user_id'] = user_id
        action_data['last_updated'] = now

        validate_action_identity_reference(
            action_data,
            WORKSPACE_IDENTITY_SCOPE_PERSONAL,
            user_id,
        )
        
        # Validate required fields
        required_fields = ['name', 'displayName', 'type', 'description']
        for field in required_fields:
            if field not in action_data:
                if field == 'displayName':
                    action_data[field] = action_data.get('name', '')
                else:
                    action_data[field] = ''
                    
        # Set defaults for optional fields
        action_data.setdefault('endpoint', '')
        action_data.setdefault('auth', {'type': 'identity'})
        action_data.setdefault('metadata', {})
        action_data.setdefault('additionalFields', {})
        
        # Ensure auth has default structure
        if not isinstance(action_data['auth'], dict):
            action_data['auth'] = {'type': 'identity'}
        elif 'type' not in action_data['auth']:
            action_data['auth']['type'] = 'identity'

        if enforce_governance:
            ensure_action_type_access('governance_user_actions', user_id, action_data.get('type'), 'personal')
        
        # Store secrets in Key Vault before upsert
        action_data = keyvault_plugin_save_helper(
            action_data,
            scope_value=user_id,
            scope="user",
            existing_plugin=existing_action,
        )
        if legacy_type:
            result = cosmos_personal_actions_container.replace_item(
                item=existing_action['id'],
                body=action_data,
                etag=existing_action['_etag'],
                match_condition=MatchConditions.IfNotModified,
            )
        else:
            result = cosmos_personal_actions_container.upsert_item(body=action_data)
        # Remove Cosmos metadata from response
        cleaned_result = {k: v for k, v in result.items() if not k.startswith('_')}
        bump_chat_bootstrap_user_cache_version(user_id, reason="personal_action_saved")
        return cleaned_result
        
    except Exception as e:
        debug_print(f"Error saving action for user {user_id}: {e}")
        raise

def delete_personal_action(user_id, action_id):
    """
    Delete a personal action/plugin.
    
    Args:
        user_id (str): The user's unique identifier
        action_id (str): The action's unique identifier OR name
        
    Returns:
        bool: True if deleted, False if not found
    """
    try:
        ensure_migration_complete(user_id)
        # Try to find the action first to get the correct ID
        action = get_personal_action(user_id, action_id, return_type=SecretReturnType.NAME)
        if not action:
            return False

        ensure_action_type_access('governance_user_actions', user_id, action.get('type'), 'personal')
            
        # Delete secrets from Key Vault before deleting the action
        keyvault_plugin_delete_helper(action, scope_value=user_id, scope="user")
        cosmos_personal_actions_container.delete_item(
            item=action['id'],
            partition_key=user_id
        )
        bump_chat_bootstrap_user_cache_version(user_id, reason="personal_action_deleted")
        return True
        
    except exceptions.CosmosResourceNotFoundError:
        return False
    except Exception as e:
        debug_print(f"Error deleting action {action_id} for user {user_id}: {e}")
        raise

def ensure_migration_complete(user_id):
    """Migrate the authoritative historical settings snapshot without count heuristics."""
    return migrate_actions_from_user_settings(user_id)

def migrate_actions_from_user_settings(user_id):
    """Migrate historical settings once; receipts survive deletion of an action.

    Settings write/import ingress must use validate_legacy_plugin_settings_update.
    Only this server-read historical boundary may create a combined Graph action.
    Each legacy creation and receipt is atomic, so a retry cannot resurrect it.
    """
    try:
        get_user_settings(user_id)
        user_settings = cosmos_user_settings_container.read_item(item=user_id, partition_key=user_id)
        plugins = user_settings.get('settings', {}).get('plugins') or []
        if not plugins:
            return 0
        if not isinstance(plugins, list):
            raise ValueError("Historical action settings must be an array.")

        migrated_count = 0
        for plugin in plugins:
            if not isinstance(plugin, dict) or not plugin.get('name'):
                raise ValueError("Historical action settings contain an invalid record.")
            if is_legacy_msgraph_type(plugin.get('type')):
                migrated_count += _migrate_historical_msgraph_action(user_id, plugin)
            else:
                existing = get_personal_action(
                    user_id, plugin.get('id') or plugin['name'], return_type=SecretReturnType.NAME,
                )
                if not existing:
                    save_personal_action(user_id, deepcopy(plugin), enforce_governance=False)
                    migrated_count += 1

        updated_settings = deepcopy(user_settings)
        updated_settings['settings']['plugins'] = []
        stored = cosmos_user_settings_container.replace_item(
            item=user_id,
            body=updated_settings,
            etag=user_settings['_etag'],
            match_condition=MatchConditions.IfNotModified,
        )
        functions_settings._set_request_cached_user_settings(user_id, stored)
        functions_settings._delete_user_ui_settings_cache(user_id)
        bump_chat_bootstrap_user_cache_version(user_id, reason="personal_actions_migrated")
        return migrated_count
    except exceptions.CosmosResourceNotFoundError:
        raise
    except (ValueError, RuntimeError, exceptions.CosmosHttpResponseError, exceptions.CosmosBatchOperationError) as exc:
        log_event(
            "[USER_SETTINGS] Historical action migration requires retry or review; original settings were retained.",
            level=logging.ERROR,
            extra={"user_id": user_id, "error_type": type(exc).__name__},
        )
        raise


def _migrate_historical_msgraph_action(user_id, plugin):
    source_key = str(plugin.get('id') or plugin['name'])
    digest = hashlib.sha256(source_key.encode('utf-8')).hexdigest()
    receipt_id = f"{ACTION_MIGRATION_ID_PREFIX}{digest}"
    try:
        cosmos_personal_actions_container.read_item(item=receipt_id, partition_key=user_id)
        return 0
    except exceptions.CosmosResourceNotFoundError:
        pass

    action_id = plugin.get('id') or str(uuid.uuid5(uuid.NAMESPACE_URL, f"{user_id}:legacy-action:{source_key}"))
    existing = None
    try:
        existing = cosmos_personal_actions_container.read_item(item=action_id, partition_key=user_id)
    except exceptions.CosmosResourceNotFoundError:
        pass
    payload = deepcopy(plugin)
    payload['id'] = action_id
    payload['user_id'] = user_id
    payload['type'] = 'msgraph'
    if existing:
        validate_legacy_action_update(payload, existing, 'user_id', user_id)
    else:
        name_conflicts = list(cosmos_personal_actions_container.query_items(
            query="SELECT c.id FROM c WHERE c.user_id = @user_id AND c.name = @name",
            parameters=[{"name": "@user_id", "value": user_id}, {"name": "@name", "value": plugin['name']}],
            partition_key=user_id,
        ))
        if name_conflicts:
            raise ValueError("Historical action ID conflicts require administrator review.")
        validate_action_identity_reference(payload, WORKSPACE_IDENTITY_SCOPE_PERSONAL, user_id)
        payload = keyvault_plugin_save_helper(payload, scope_value=user_id, scope="user")

    receipt = {
        'id': receipt_id,
        'user_id': user_id,
        '_action_migration': True,
        'action_id': action_id,
        'version': '0.261.029',
    }
    operations = [('create', (receipt,))]
    if not existing:
        operations.append(('create', (payload,)))
    try:
        cosmos_personal_actions_container.execute_item_batch(
            batch_operations=operations, partition_key=user_id,
        )
    except exceptions.CosmosBatchOperationError as exc:
        if exc.status_code != 409:
            raise
        cosmos_personal_actions_container.read_item(item=receipt_id, partition_key=user_id)
        return 0
    return 0 if existing else 1

def get_actions_by_names(user_id, action_names, return_type=SecretReturnType.TRIGGER):
    """
    Get multiple actions by their names.
    
    Args:
        user_id (str): The user's unique identifier
        action_names (list): List of action names to retrieve
        
    Returns:
        list: List of action dictionaries
    """
    try:
        if not action_names:
            return []
            
        # Create IN clause for query
        placeholders = ", ".join([f"@name{i}" for i in range(len(action_names))])
        query = f"SELECT * FROM c WHERE c.user_id = @user_id AND c.name IN ({placeholders})"
        
        parameters = [{"name": "@user_id", "value": user_id}]
        for i, name in enumerate(action_names):
            parameters.append({"name": f"@name{i}", "value": name})
        
        actions = list(cosmos_personal_actions_container.query_items(
            query=query,
            parameters=parameters,
            partition_key=user_id
        ))
        
        # Remove Cosmos metadata
        cleaned_actions = []
        for action in actions:
            if _is_action_migration_record(action):
                continue
            cleaned_action = {k: v for k, v in action.items() if not k.startswith('_')}
            cleaned_action = keyvault_plugin_get_helper(cleaned_action, scope_value=user_id, scope="user", return_type=return_type)
            cleaned_actions.append(cleaned_action)
            
        return cleaned_actions
        
    except Exception as e:
        debug_print(f"Error fetching actions by names for user {user_id}: {e}")
        return []

def get_actions_by_type(user_id, action_type, return_type=SecretReturnType.TRIGGER):
    """
    Get all actions of a specific type for a user.
    
    Args:
        user_id (str): The user's unique identifier
        action_type (str): The type of actions to retrieve (e.g., 'openapi', 'sql_query')
        
    Returns:
        list: List of action dictionaries
    """
    try:
        query = "SELECT * FROM c WHERE c.user_id = @user_id AND c.type = @type"
        parameters = [
            {"name": "@user_id", "value": user_id},
            {"name": "@type", "value": action_type}
        ]
        
        actions = list(cosmos_personal_actions_container.query_items(
            query=query,
            parameters=parameters,
            partition_key=user_id
        ))
        
        # Remove Cosmos metadata
        cleaned_actions = []
        for action in actions:
            if _is_action_migration_record(action):
                continue
            cleaned_action = {k: v for k, v in action.items() if not k.startswith('_')}
            cleaned_action = keyvault_plugin_get_helper(cleaned_action, scope_value=user_id, scope="user", return_type=return_type)
            cleaned_actions.append(cleaned_action)
            
        return cleaned_actions
        
    except Exception as e:
        debug_print(f"Error fetching actions by type {action_type} for user {user_id}: {e}")
        return []
