# functions_group_actions.py

"""Group-level plugin/action management helpers."""

import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from azure.cosmos import exceptions

from config import cosmos_group_actions_container
from functions_action_manifest import bind_action_origin, is_retired_mcp_stdio
from functions_appinsights import log_event
from functions_authentication import get_current_user_id
from functions_keyvault import (
    SecretReturnType,
    keyvault_plugin_delete_helper,
    keyvault_plugin_get_helper,
    keyvault_plugin_save_helper,
)
from functions_workspace_identities import (
    WORKSPACE_IDENTITY_SCOPE_GROUP,
    hydrate_action_identity_reference,
    validate_action_identity_reference,
)
from functions_governance import ensure_action_type_access, filter_actions_by_action_type_access
from functions_chat_bootstrap_cache import bump_chat_bootstrap_global_cache_version
from functions_legacy_action_management import (
    authorize_scoped_mcp_secret_read,
    prepare_scoped_action,
    retired_action_management_view,
    validate_scoped_mcp_action,
)
from functions_settings import get_settings


_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def get_group_actions(
    group_id: str, return_type: SecretReturnType = SecretReturnType.TRIGGER
) -> List[Dict[str, Any]]:
    """Return all actions/plugins scoped to the provided group."""
    try:
        query = "SELECT * FROM c WHERE c.group_id = @group_id"
        parameters = [
            {"name": "@group_id", "value": group_id},
        ]
        results = list(
            cosmos_group_actions_container.query_items(
                query=query,
                parameters=parameters,
                partition_key=group_id,
            )
        )
    except exceptions.CosmosResourceNotFoundError:
        return []
    except Exception as exc:
        log_event("[PLUGINS] Group action listing failed", level=logging.ERROR,
                  extra={"group_id": group_id, "error_type": type(exc).__name__})
        raise
    try:
        return [_clean_action(action, group_id, return_type) for action in results]
    except Exception as exc:
        log_event("[PLUGINS] Group action normalization failed", level=logging.WARNING,
                  extra={"group_id": group_id, "error_type": type(exc).__name__})
        raise


def get_governed_group_actions(
    group_id: str,
    user_id: str,
    return_type: SecretReturnType = SecretReturnType.TRIGGER,
) -> List[Dict[str, Any]]:
    """Return group actions that the user can access by action type governance."""
    actions = get_group_actions(group_id, return_type=return_type)
    active_actions = [action for action in actions if not is_retired_mcp_stdio(action)]
    allowed_actions = filter_actions_by_action_type_access(
        user_id, active_actions, 'governance_group_actions', 'group'
    )
    return [action for action in actions if is_retired_mcp_stdio(action) or action in allowed_actions]


def get_group_action(
    group_id: str, action_id: str, return_type: SecretReturnType = SecretReturnType.TRIGGER
) -> Optional[Dict[str, Any]]:
    """Fetch a single group action by id or name."""
    try:
        try:
            action = cosmos_group_actions_container.read_item(
                item=action_id,
                partition_key=group_id,
            )
        except exceptions.CosmosResourceNotFoundError:
            query = "SELECT * FROM c WHERE c.group_id = @group_id AND c.name = @name"
            parameters = [
                {"name": "@group_id", "value": group_id},
                {"name": "@name", "value": action_id},
            ]
            actions = list(
                cosmos_group_actions_container.query_items(
                    query=query,
                    parameters=parameters,
                    partition_key=group_id,
                )
            )
            if not actions:
                return None
            action = actions[0]
    except exceptions.CosmosResourceNotFoundError:
        return None
    except Exception as exc:
        log_event("[PLUGINS] Group action lookup failed", level=logging.ERROR,
                  extra={"group_id": group_id, "action_id": action_id, "error_type": type(exc).__name__})
        raise

    try:
        return _clean_action(action, group_id, return_type)
    except Exception as exc:
        log_event("[PLUGINS] Group action normalization failed", level=logging.WARNING,
                  extra={"group_id": group_id, "action_id": action_id, "error_type": type(exc).__name__})
        raise


def save_group_action(group_id: str, action_data: Dict[str, Any], user_id: Optional[str] = None) -> Dict[str, Any]:
    """Create or update a group action entry."""
    payload = prepare_scoped_action(action_data, "group", group_id)
    user_id = user_id or get_current_user_id()
    action_id = payload.get("id") or str(uuid.uuid4())
    if not isinstance(action_id, str):
        raise ValueError("Action ID must be a string.")

    payload["id"] = action_id
    payload["group_id"] = group_id
    now = datetime.utcnow().isoformat()
    payload["last_updated"] = now

    # Track who created/modified this action
    existing_action = None
    try:
        existing_action = cosmos_group_actions_container.read_item(
            item=action_id,
            partition_key=group_id,
        )
    except exceptions.CosmosResourceNotFoundError:
        pass

    if existing_action:
        payload["created_by"] = existing_action.get("created_by", user_id)
        payload["created_at"] = existing_action.get("created_at", now)
    else:
        payload["created_by"] = user_id
        payload["created_at"] = now
    payload["modified_by"] = user_id
    payload["modified_at"] = now

    payload.setdefault("name", "")
    payload.setdefault("displayName", payload.get("name", ""))
    payload.setdefault("type", "")
    payload.setdefault("description", "")
    payload.setdefault("endpoint", "")
    payload.setdefault("auth", {"type": "identity"})
    payload.setdefault("metadata", {})
    payload.setdefault("additionalFields", {})

    if not isinstance(payload["auth"], dict):
        payload["auth"] = {"type": "identity"}
    elif "type" not in payload["auth"]:
        payload["auth"]["type"] = "identity"

    if user_id:
        ensure_action_type_access('governance_group_actions', user_id, payload.get('type'), 'group')

    payload.pop("user_id", None)
    payload = bind_action_origin(payload, "group", group_id)
    if payload["type"] == "mcp":
        validate_scoped_mcp_action(payload, user_id, get_settings())

    validate_action_identity_reference(
        payload,
        WORKSPACE_IDENTITY_SCOPE_GROUP,
        group_id,
    )

    payload = keyvault_plugin_save_helper(
        payload,
        scope_value=group_id,
        scope="group",
        existing_plugin=existing_action,
    )

    try:
        stored = cosmos_group_actions_container.upsert_item(body=payload)
        bump_chat_bootstrap_global_cache_version(reason="group_action_saved")
        return _clean_action(stored, group_id, SecretReturnType.TRIGGER)
    except Exception as exc:
        log_event("[PLUGINS] Group action save failed", level=logging.ERROR,
                  extra={"group_id": group_id, "action_id": action_id, "error_type": type(exc).__name__})
        raise


def delete_group_action(group_id: str, action_id: str) -> bool:
    """Remove a group action entry if it exists."""
    try:
        action = cosmos_group_actions_container.read_item(
            item=action_id,
            partition_key=group_id,
        )
    except exceptions.CosmosResourceNotFoundError:
        return False

    try:
        keyvault_plugin_delete_helper(action, scope_value=group_id, scope="group")
        cosmos_group_actions_container.delete_item(
            item=action_id,
            partition_key=group_id,
        )
        bump_chat_bootstrap_global_cache_version(reason="group_action_deleted")
        return True
    except Exception as exc:
        log_event("[PLUGINS] Group action deletion failed", level=logging.ERROR,
                  extra={"group_id": group_id, "action_id": action_id, "error_type": type(exc).__name__})
        raise


def validate_group_action_payload(payload: Dict[str, Any], partial: bool = False) -> None:
    """Validate incoming payload data for group actions."""
    if not isinstance(payload, dict):
        raise ValueError("Action payload must be an object")

    required_fields = (
        "name",
        "displayName",
        "type",
        "description",
        "endpoint",
        "auth",
        "metadata",
        "additionalFields",
    )

    if not partial:
        missing = [field for field in required_fields if field not in payload]
        if missing:
            raise ValueError(f"Missing required action fields: {', '.join(missing)}")

    if "name" in payload:
        name = payload["name"]
        if not isinstance(name, str) or not name or not _NAME_PATTERN.fullmatch(name):
            raise ValueError("Action name must be alphanumeric with optional underscores or hyphens")

    if "displayName" in payload and not isinstance(payload["displayName"], str):
        raise ValueError("displayName must be a string")

    if "type" in payload and not isinstance(payload["type"], str):
        raise ValueError("type must be a string")

    if "description" in payload and not isinstance(payload["description"], str):
        raise ValueError("description must be a string")

    if "endpoint" in payload and not isinstance(payload["endpoint"], str):
        raise ValueError("endpoint must be a string")

    if "auth" in payload and not isinstance(payload["auth"], dict):
        raise ValueError("auth must be an object")

    if "metadata" in payload and not isinstance(payload["metadata"], dict):
        raise ValueError("metadata must be an object")

    if "additionalFields" in payload and not isinstance(payload["additionalFields"], dict):
        raise ValueError("additionalFields must be an object")


def _clean_action(
    action: Dict[str, Any],
    group_id: str,
    return_type: SecretReturnType,
) -> Dict[str, Any]:
    retired_view = retired_action_management_view(action, "group", group_id)
    if retired_view is not None:
        return retired_view
    cleaned = {k: v for k, v in action.items() if not k.startswith("_")}
    cleaned = bind_action_origin(cleaned, "group", group_id)
    if return_type == SecretReturnType.NAME and cleaned["type"] == "mcp":
        # Workspace identity hydration treats NAME like VALUE, so defer it until authorization.
        return cleaned
    if return_type == SecretReturnType.VALUE and cleaned["type"] == "mcp":
        ensure_action_type_access("governance_group_actions", get_current_user_id(), "mcp", "group")
        authorize_scoped_mcp_secret_read(cleaned, get_settings())
    cleaned = keyvault_plugin_get_helper(
        cleaned,
        scope_value=group_id,
        scope="group",
        return_type=return_type,
    )
    cleaned = hydrate_action_identity_reference(
        cleaned,
        WORKSPACE_IDENTITY_SCOPE_GROUP,
        group_id,
        return_type=return_type,
    )
    return bind_action_origin(cleaned, "group", group_id)
