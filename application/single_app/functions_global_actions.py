# functions_global_actions.py
"""
Global actions/plugins management functions.

This module provides functions for managing global actions stored in the
global_actions container with id partitioning.
"""

import uuid
import json
import traceback
from datetime import datetime
from config import cosmos_global_actions_container
from functions_authentication import get_current_user_id
from functions_keyvault import keyvault_plugin_save_helper, keyvault_plugin_get_helper, keyvault_plugin_delete_helper, SecretReturnType

def get_global_actions(return_type=SecretReturnType.TRIGGER):
    """
    Get all global actions.
    
    Returns:
        list: List of global action dictionaries
    """
    try:
        actions = list(cosmos_global_actions_container.query_items(
            query="SELECT * FROM c",
            enable_cross_partition_query=True
        ))
        # Resolve Key Vault references for each action
        actions = [keyvault_plugin_get_helper(a, scope_value=a.get('id'), scope="global", return_type=return_type) for a in actions]
        return actions
        
    except Exception as e:
        print(f"❌ Error getting global actions: {str(e)}")
        traceback.print_exc()
        return []


def get_global_action(action_id, return_type=SecretReturnType.TRIGGER):
    """
    Get a specific global action by ID.
    
    Args:
        action_id (str): The action ID
        
    Returns:
        dict: Action data or None if not found
    """
    try:
        action = cosmos_global_actions_container.read_item(
            item=action_id,
            partition_key=action_id
        )
        # Resolve Key Vault references
        action = keyvault_plugin_get_helper(action, scope_value=action_id, scope="global", return_type=return_type)
        print(f"✅ Found global action: {action_id}")
        return action
        
    except Exception as e:
        print(f"❌ Error getting global action {action_id}: {str(e)}")
        return None


def save_global_action(action_data, user_id=None):
    """
    Save or update a global action.
    
    Args:
        action_data (dict): Action data to save
        user_id (str, optional): The user ID of the person performing the action
        
    Returns:
        dict: Saved action data or None if failed
    """
    try:
        if user_id is None:
            user_id = get_current_user_id()
        if not user_id:
            user_id = "system"

        # Ensure required fields
        if 'id' not in action_data:
            action_data['id'] = str(uuid.uuid4())
        # Add metadata
        action_data['is_global'] = True
        now = datetime.utcnow().isoformat()

        # Check if this is a new action or an update to preserve created_by/created_at
        existing_action = None
        try:
            existing_action = cosmos_global_actions_container.read_item(
                item=action_data['id'],
                partition_key=action_data['id']
            )
        except Exception:
            pass

        if existing_action:
            action_data['created_by'] = existing_action.get('created_by') or user_id
            action_data['created_at'] = existing_action.get('created_at') or now
        else:
            action_data['created_by'] = user_id
            action_data['created_at'] = now
        action_data['modified_by'] = user_id
        action_data['modified_at'] = now
        action_data['updated_at'] = now
        print(f"💾 Saving global action: {action_data.get('name', 'Unknown')}")
        # Store secrets in Key Vault before upsert
        action_data = keyvault_plugin_save_helper(
            action_data,
            scope_value=action_data.get('id'),
            scope="global",
            existing_plugin=existing_action,
        )
        result = cosmos_global_actions_container.upsert_item(body=action_data)
        print(f"✅ Global action saved successfully: {result['id']}")
        return result
        
    except Exception as e:
        print(f"❌ Error saving global action: {str(e)}")
        traceback.print_exc()
        return None


def delete_global_action(action_id):
    """
    Delete a global action.
    
    Args:
        action_id (str): The action ID to delete
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        print(f"🗑️ Deleting global action: {action_id}")
        # Delete secrets from Key Vault before deleting the action
        action = get_global_action(action_id, return_type=SecretReturnType.NAME)
        if action:
            keyvault_plugin_delete_helper(action, scope_value=action_id, scope="global")
        cosmos_global_actions_container.delete_item(
            item=action_id,
            partition_key=action_id
        )
        print(f"✅ Global action deleted successfully: {action_id}")
        return True
        
    except Exception as e:
        print(f"❌ Error deleting global action {action_id}: {str(e)}")
        traceback.print_exc()
        return False


