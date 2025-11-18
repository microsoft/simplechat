# functions_personal_actions.py

"""
Personal Actions (Plugins) Management

This module handles all operations related to personal actions/plugins stored in the 
personal_actions container with user_id partitioning.
"""

import uuid
from datetime import datetime
from azure.cosmos import exceptions
from flask import current_app
from functions_keyvault import keyvault_plugin_save_helper, keyvault_plugin_get_helper, keyvault_plugin_delete_helper, SecretReturnType
from functions_settings import get_user_settings, update_user_settings
from config import cosmos_personal_actions_container
import logging

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
            cleaned_action = {k: v for k, v in action.items() if not k.startswith('_')}
            cleaned_action = keyvault_plugin_get_helper(cleaned_action, scope_value=user_id, scope="user", return_type=return_type)
            cleaned_actions.append(cleaned_action)
        return cleaned_actions
        
    except exceptions.CosmosResourceNotFoundError:
        return []
    except Exception as e:
        current_app.logger.error(f"Error fetching personal actions for user {user_id}: {e}")
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
        
        # Remove Cosmos metadata and resolve Key Vault references
        cleaned_action = {k: v for k, v in action.items() if not k.startswith('_')}
        cleaned_action = keyvault_plugin_get_helper(cleaned_action, scope_value=user_id, scope="user", return_type=return_type)
        return cleaned_action
        
    except Exception as e:
        current_app.logger.error(f"Error fetching action {action_id} for user {user_id}: {e}")
        return None

def save_personal_action(user_id, action_data):
    """
    Save or update a personal action/plugin.
    
    Args:
        user_id (str): The user's unique identifier
        action_data (dict): Action configuration data
        
    Returns:
        dict: Saved action data with ID
    """
    try:
        # Check if an action with this name already exists
        existing_action = None
        if 'name' in action_data and action_data['name']:
            existing_action = get_personal_action(user_id, action_data['name'])
        
        # Preserve existing ID if updating, or generate new ID if creating
        if existing_action:
            # Update existing action - preserve the original ID
            action_data['id'] = existing_action['id']
        elif 'id' not in action_data or not action_data['id']:
            # New action - generate UUID for ID
            action_data['id'] = str(uuid.uuid4())
            
        action_data['user_id'] = user_id
        action_data['last_updated'] = datetime.utcnow().isoformat()
        
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
        
        # Store secrets in Key Vault before upsert
        action_data = keyvault_plugin_save_helper(action_data, scope_value=user_id, scope="user")
        result = cosmos_personal_actions_container.upsert_item(body=action_data)
        # Remove Cosmos metadata from response
        cleaned_result = {k: v for k, v in result.items() if not k.startswith('_')}
        return cleaned_result
        
    except Exception as e:
        current_app.logger.error(f"Error saving action for user {user_id}: {e}")
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
        # Try to find the action first to get the correct ID
        action = get_personal_action(user_id, action_id)
        if not action:
            return False
            
        # Delete secrets from Key Vault before deleting the action
        keyvault_plugin_delete_helper(action, scope_value=user_id, scope="user")
        cosmos_personal_actions_container.delete_item(
            item=action['id'],
            partition_key=user_id
        )
        return True
        
    except exceptions.CosmosResourceNotFoundError:
        return False
    except Exception as e:
        current_app.logger.error(f"Error deleting action {action_id} for user {user_id}: {e}")
        raise

def ensure_migration_complete(user_id):
    """
    Ensure that migration is complete by checking for and cleaning up any remaining legacy data.
    This is more thorough than just checking if personal container is empty.
    
    Args:
        user_id (str): The user's unique identifier
        
    Returns:
        int: Number of actions migrated (0 if already migrated)
    """
    try:
        user_settings = get_user_settings(user_id)
        plugins = user_settings.get('settings', {}).get('plugins', [])
        
        # If there are still legacy plugins, migrate them
        if plugins:
            # Check if we already have personal actions to avoid duplicate migration
            existing_personal_actions = get_personal_actions(user_id)
            
            # Only migrate if we don't already have personal actions or if legacy count is higher
            if not existing_personal_actions or len(plugins) > len(existing_personal_actions):
                return migrate_actions_from_user_settings(user_id)
            else:
                # Clean up legacy data without migration (already migrated)
                settings_to_update = user_settings.get('settings', {})
                settings_to_update['plugins'] = []  # Set to empty array instead of removing
                update_user_settings(user_id, settings_to_update)
                current_app.logger.info(f"Cleaned up legacy plugin data for user {user_id} (already migrated)")
                return 0
        
        return 0
        
    except Exception as e:
        current_app.logger.error(f"Error ensuring action migration complete for user {user_id}: {e}")
        return 0

def migrate_actions_from_user_settings(user_id):
    """
    Migrate actions/plugins from user settings to personal_actions container.
    
    Args:
        user_id (str): The user's unique identifier
        
    Returns:
        int: Number of actions migrated
    """
    try:
        user_settings = get_user_settings(user_id)
        plugins = user_settings.get('settings', {}).get('plugins', [])
        
        # Get existing personal actions to avoid duplicates
        existing_personal_actions = get_personal_actions(user_id)
        existing_action_names = {action['name'] for action in existing_personal_actions}
        
        migrated_count = 0
        for plugin in plugins:
            try:
                # Skip if plugin already exists in personal container
                if plugin.get('name') in existing_action_names:
                    current_app.logger.info(f"Skipping migration of plugin '{plugin.get('name')}' - already exists")
                    continue
                # Ensure plugin has an ID (generate GUID if missing)
                if 'id' not in plugin or not plugin['id']:
                    plugin['id'] = str(uuid.uuid4())
                # Store secrets in Key Vault before migration
                plugin = keyvault_plugin_save_helper(plugin, scope_value=user_id, scope="user")
                save_personal_action(user_id, plugin)
                migrated_count += 1
            except Exception as e:
                current_app.logger.error(f"Error migrating plugin {plugin.get('name', 'unknown')} for user {user_id}: {e}")
                
        # Always remove plugins from user settings after processing (even if no new ones migrated)
        settings_to_update = user_settings.get('settings', {})
        settings_to_update['plugins'] = []  # Set to empty array instead of removing
        update_user_settings(user_id, settings_to_update)
            
        current_app.logger.info(f"Migrated {migrated_count} new actions for user {user_id}, cleaned up legacy data")
        return migrated_count
        
    except Exception as e:
        current_app.logger.error(f"Error during action migration for user {user_id}: {e}")
        return 0

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
            cleaned_action = {k: v for k, v in action.items() if not k.startswith('_')}
            cleaned_action = keyvault_plugin_get_helper(cleaned_action, scope_value=user_id, scope="user", return_type=return_type)
            cleaned_actions.append(cleaned_action)
            
        return cleaned_actions
        
    except Exception as e:
        current_app.logger.error(f"Error fetching actions by names for user {user_id}: {e}")
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
            cleaned_action = {k: v for k, v in action.items() if not k.startswith('_')}
            cleaned_action = keyvault_plugin_get_helper(cleaned_action, scope_value=user_id, scope="user", return_type=return_type)
            cleaned_actions.append(cleaned_action)
            
        return cleaned_actions
        
    except Exception as e:
        current_app.logger.error(f"Error fetching actions by type {action_type} for user {user_id}: {e}")
        return []
