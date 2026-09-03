# functions_global_actions.py
"""
Global actions/plugins management functions.

This module provides functions for managing global actions stored in the
global_actions container with id partitioning.
"""

import logging
import uuid
from datetime import datetime
from azure.core import MatchConditions
from azure.cosmos import exceptions
from config import cosmos_global_actions_container
from functions_action_manifest import McpConfigurationError, bind_action_origin
from functions_appinsights import log_event
from functions_authentication import get_current_user_id
from functions_keyvault import keyvault_plugin_save_helper, keyvault_plugin_get_helper, keyvault_plugin_delete_helper, SecretReturnType
from functions_workspace_identities import (
    WORKSPACE_IDENTITY_SCOPE_GLOBAL,
    hydrate_action_identity_reference,
    validate_action_identity_reference,
)
from functions_chat_bootstrap_cache import bump_chat_bootstrap_global_cache_version
from json_schema_validation import is_legacy_msgraph_type, normalize_m365_action_payload, validate_legacy_action_update
from functions_legacy_action_management import (
    authorize_scoped_mcp_secret_read,
    prepare_scoped_action,
    retired_action_management_view,
    validate_scoped_mcp_action,
)
from functions_settings import get_settings


def _clean_action(action, return_type, action_id=None):
    retired_view = retired_action_management_view(action, "global", "global")
    if retired_view is not None:
        retired_view.setdefault("is_enabled", True)
        return retired_view
    cleaned = {key: value for key, value in action.items() if not key.startswith("_")}
    cleaned = bind_action_origin(cleaned, "global", "global")
    if return_type == SecretReturnType.NAME and cleaned["type"] == "mcp":
        # Workspace identity hydration treats NAME like VALUE, so defer it until authorization.
        cleaned.setdefault("is_enabled", True)
        return cleaned
    if return_type == SecretReturnType.VALUE and cleaned["type"] == "mcp":
        authorize_scoped_mcp_secret_read(cleaned, get_settings())
    cleaned = keyvault_plugin_get_helper(
        cleaned, scope_value=action_id or action.get("id"), scope="global", return_type=return_type
    )
    cleaned = hydrate_action_identity_reference(
        cleaned,
        WORKSPACE_IDENTITY_SCOPE_GLOBAL,
        WORKSPACE_IDENTITY_SCOPE_GLOBAL,
        return_type=return_type,
    )
    cleaned.setdefault("is_enabled", True)
    return bind_action_origin(cleaned, "global", "global")

def get_global_actions(return_type=SecretReturnType.TRIGGER, include_disabled=False):
    """
    Get all global actions.

    Args:
        return_type: Secret resolution mode for Key Vault-backed values.
        include_disabled (bool): When True, include disabled actions for admin management.
    
    Returns:
        list: List of global action dictionaries
    """
    try:
        query = "SELECT * FROM c"
        if not include_disabled:
            query = "SELECT * FROM c WHERE NOT IS_DEFINED(c.is_enabled) OR c.is_enabled = true"

        actions = list(cosmos_global_actions_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
    except exceptions.CosmosResourceNotFoundError:
        return []
    except Exception as exc:
        log_event("[PLUGINS] Global action listing failed", level=logging.ERROR,
                  extra={"error_type": type(exc).__name__})
        raise
    try:
        return [_clean_action(action, return_type) for action in actions]
    except Exception as exc:
        log_event("[PLUGINS] Global action normalization failed", level=logging.WARNING,
                  extra={"error_type": type(exc).__name__})
        raise


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
    except exceptions.CosmosResourceNotFoundError:
        return None
    except Exception as exc:
        log_event("[PLUGINS] Global action lookup failed", level=logging.ERROR,
                  extra={"action_id": action_id, "error_type": type(exc).__name__})
        raise
    try:
        return _clean_action(action, return_type, action_id=action_id)
    except Exception as exc:
        log_event("[PLUGINS] Global action normalization failed", level=logging.WARNING,
                  extra={"action_id": action_id, "error_type": type(exc).__name__})
        raise


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
        submitted_action = action_data
        action_data = normalize_m365_action_payload(action_data)
        action_data = prepare_scoped_action(action_data, "global", "global")
        if user_id is None:
            user_id = get_current_user_id()
        actor_user_id = user_id
        if not user_id:
            user_id = "system"

        # Ensure required fields
        if not action_data.get('id'):
            action_data['id'] = str(uuid.uuid4())
        if not isinstance(action_data['id'], str):
            raise ValueError("Action ID must be a string.")
        # Add metadata
        action_data['is_global'] = True
        now = datetime.utcnow().isoformat()

        # Check if this is a new action or an update to preserve created_by/created_at
        try:
            existing_action = cosmos_global_actions_container.read_item(
                item=action_data['id'],
                partition_key=action_data['id']
            )
        except exceptions.CosmosResourceNotFoundError:
            existing_action = None

        validate_legacy_action_update(submitted_action, existing_action)
        legacy_type = is_legacy_msgraph_type(action_data.get('type'))
        if legacy_type:
            action_data['type'] = 'msgraph'
        if existing_action:
            action_data['created_by'] = existing_action.get('created_by') or user_id
            action_data['created_at'] = existing_action.get('created_at') or now
        else:
            action_data['created_by'] = user_id
            action_data['created_at'] = now
        if 'is_enabled' in action_data:
            action_data['is_enabled'] = bool(action_data.get('is_enabled'))
        elif existing_action is not None:
            action_data['is_enabled'] = bool(existing_action.get('is_enabled', True))
        else:
            action_data['is_enabled'] = True
        action_data['modified_by'] = user_id
        action_data['modified_at'] = now
        action_data['updated_at'] = now
        action_data = bind_action_origin(action_data, "global", "global")
        if action_data["type"] == "mcp":
            validate_scoped_mcp_action(action_data, actor_user_id, get_settings())
        validate_action_identity_reference(
            action_data,
            WORKSPACE_IDENTITY_SCOPE_GLOBAL,
            WORKSPACE_IDENTITY_SCOPE_GLOBAL,
        )
        # Store secrets in Key Vault before upsert
        action_data = keyvault_plugin_save_helper(
            action_data,
            scope_value=action_data.get('id'),
            scope="global",
            existing_plugin=existing_action,
        )
        if legacy_type:
            result = cosmos_global_actions_container.replace_item(
                item=action_data['id'],
                body=action_data,
                etag=existing_action['_etag'],
                match_condition=MatchConditions.IfNotModified,
            )
        else:
            result = cosmos_global_actions_container.upsert_item(body=action_data)
        bump_chat_bootstrap_global_cache_version(reason="global_action_saved")
        return bind_action_origin(
            {key: value for key, value in result.items() if not key.startswith("_")},
            "global",
            "global",
        )
        
    except Exception as exc:
        log_event("[PLUGINS] Global action save failed", level=logging.ERROR,
                  extra={"error_type": type(exc).__name__})
        raise


def delete_global_action(action_id):
    """
    Delete a global action.
    
    Args:
        action_id (str): The action ID to delete
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Delete secrets from Key Vault before deleting the action
        action = cosmos_global_actions_container.read_item(item=action_id, partition_key=action_id)
        action = bind_action_origin(action, "global", "global")
        keyvault_plugin_delete_helper(action, scope_value=action_id, scope="global")
        cosmos_global_actions_container.delete_item(
            item=action_id,
            partition_key=action_id
        )
        bump_chat_bootstrap_global_cache_version(reason="global_action_deleted")
        return True
        
    except Exception as exc:
        log_event("[PLUGINS] Global action deletion failed", level=logging.ERROR,
                  extra={"action_id": action_id, "error_type": type(exc).__name__})
        return False


def update_global_action_enabled(action_id, is_enabled, user_id=None):
    """
    Enable or disable a global action without mutating its stored secret references.

    Args:
        action_id (str): The action ID to update.
        is_enabled (bool): The desired enabled state.
        user_id (str, optional): The user performing the change.

    Returns:
        dict: Updated action document or None if the operation fails.
    """
    try:
        if user_id is None:
            user_id = get_current_user_id()
        actor_user_id = user_id
        if not user_id:
            user_id = "system"

        existing_action = cosmos_global_actions_container.read_item(
            item=action_id,
            partition_key=action_id
        )
        action = prepare_scoped_action(existing_action, "global", "global")
        if action["type"] == "mcp":
            validate_scoped_mcp_action(action, actor_user_id, get_settings())
        now = datetime.utcnow().isoformat()
        action['is_enabled'] = bool(is_enabled)
        action['modified_by'] = user_id
        action['modified_at'] = now
        action['updated_at'] = now
        result = cosmos_global_actions_container.replace_item(
            item=action_id,
            body=action,
            etag=existing_action['_etag'],
            match_condition=MatchConditions.IfNotModified,
        )
        bump_chat_bootstrap_global_cache_version(reason="global_action_enabled_updated")
        return bind_action_origin(result, "global", "global")
    except (McpConfigurationError, PermissionError):
        raise
    except Exception as exc:
        log_event("[PLUGINS] Global action enabled-state update failed", level=logging.ERROR,
                  extra={"action_id": action_id, "error_type": type(exc).__name__})
        return None
