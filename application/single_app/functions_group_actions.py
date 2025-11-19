# functions_group_actions.py

"""Group-level plugin/action management helpers."""

import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from azure.cosmos import exceptions
from flask import current_app

from config import cosmos_group_actions_container
from functions_keyvault import (
    SecretReturnType,
    keyvault_plugin_delete_helper,
    keyvault_plugin_get_helper,
    keyvault_plugin_save_helper,
)


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
        return [_clean_action(action, group_id, return_type) for action in results]
    except exceptions.CosmosResourceNotFoundError:
        return []
    except Exception as exc:
        current_app.logger.error(
            "Error fetching group actions for %s: %s", group_id, exc
        )
        return []


def get_group_action(
    group_id: str, action_id: str, return_type: SecretReturnType = SecretReturnType.TRIGGER
) -> Optional[Dict[str, Any]]:
    """Fetch a single group action by id or name."""
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
    except Exception as exc:
        current_app.logger.error(
            "Error fetching group action %s for %s: %s", action_id, group_id, exc
        )
        return None

    return _clean_action(action, group_id, return_type)


def save_group_action(group_id: str, action_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create or update a group action entry."""
    payload = dict(action_data)
    action_id = payload.get("id") or str(uuid.uuid4())

    payload["id"] = action_id
    payload["group_id"] = group_id
    payload["last_updated"] = datetime.utcnow().isoformat()

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

    payload.pop("user_id", None)

    payload = keyvault_plugin_save_helper(payload, scope_value=group_id, scope="group")

    try:
        stored = cosmos_group_actions_container.upsert_item(body=payload)
        return _clean_action(stored, group_id, SecretReturnType.TRIGGER)
    except Exception as exc:
        current_app.logger.error(
            "Error saving group action %s for %s: %s", action_id, group_id, exc
        )
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
        return True
    except Exception as exc:
        current_app.logger.error(
            "Error deleting group action %s for %s: %s", action_id, group_id, exc
        )
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
    cleaned = {k: v for k, v in action.items() if not k.startswith("_")}
    cleaned = keyvault_plugin_get_helper(
        cleaned,
        scope_value=group_id,
        scope="group",
        return_type=return_type,
    )
    cleaned.setdefault("is_global", False)
    cleaned.setdefault("is_group", True)
    cleaned.setdefault("scope", "group")
    return cleaned
