# functions_group_agents.py

"""Group-level agent management helpers."""

import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from azure.cosmos import exceptions
from flask import current_app

from config import cosmos_group_agents_container
from functions_keyvault import (
    keyvault_agent_delete_helper,
    keyvault_agent_get_helper,
    keyvault_agent_save_helper,
)


_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def get_group_agents(group_id: str) -> List[Dict[str, Any]]:
    """Return all agents scoped to the provided group."""
    try:
        query = "SELECT * FROM c WHERE c.group_id = @group_id"
        parameters = [
            {"name": "@group_id", "value": group_id},
        ]
        results = list(
            cosmos_group_agents_container.query_items(
                query=query,
                parameters=parameters,
                partition_key=group_id,
            )
        )
        return [_clean_agent(agent) for agent in results]
    except exceptions.CosmosResourceNotFoundError:
        return []
    except Exception as exc:
        current_app.logger.error(
            "Error fetching group agents for %s: %s", group_id, exc
        )
        return []


def get_group_agent(group_id: str, agent_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single group agent document."""
    try:
        agent = cosmos_group_agents_container.read_item(
            item=agent_id,
            partition_key=group_id,
        )
        return _clean_agent(agent)
    except exceptions.CosmosResourceNotFoundError:
        return None
    except Exception as exc:
        current_app.logger.error(
            "Error fetching group agent %s for %s: %s", agent_id, group_id, exc
        )
        return None


def save_group_agent(group_id: str, agent_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create or update a group agent entry."""
    agent_id = agent_data.get("id") or str(uuid.uuid4())
    payload = dict(agent_data)
    payload["id"] = agent_id
    payload["group_id"] = group_id
    payload["last_updated"] = datetime.utcnow().isoformat()
    payload["is_global"] = False
    payload["is_group"] = True

    # Required/defaulted fields
    payload.setdefault("name", "")
    payload.setdefault("display_name", payload.get("name", ""))
    payload.setdefault("description", "")
    payload.setdefault("instructions", "")
    payload.setdefault("actions_to_load", [])
    payload.setdefault("other_settings", {})
    payload.setdefault("max_completion_tokens", -1)
    payload.setdefault("enable_agent_gpt_apim", False)
    payload.setdefault("agent_type", "local")

    # Ensure optional Azure fields exist
    payload.setdefault("azure_openai_gpt_endpoint", "")
    payload.setdefault("azure_openai_gpt_key", "")
    payload.setdefault("azure_openai_gpt_deployment", "")
    payload.setdefault("azure_openai_gpt_api_version", "")
    payload.setdefault("azure_agent_apim_gpt_endpoint", "")
    payload.setdefault("azure_agent_apim_gpt_subscription_key", "")
    payload.setdefault("azure_agent_apim_gpt_deployment", "")
    payload.setdefault("azure_agent_apim_gpt_api_version", "")

    # Remove user-specific residue if present
    payload.pop("user_id", None)

    if payload.get("max_completion_tokens") is None:
        payload["max_completion_tokens"] = -1

    # Store sensitive values in Key Vault before persistence
    payload = keyvault_agent_save_helper(payload, payload["id"], scope="group")

    try:
        stored = cosmos_group_agents_container.upsert_item(body=payload)
        return _clean_agent(stored)
    except Exception as exc:
        current_app.logger.error(
            "Error saving group agent %s for %s: %s", agent_id, group_id, exc
        )
        raise


def delete_group_agent(group_id: str, agent_id: str) -> bool:
    """Remove a group agent entry if it exists."""
    try:
        agent = cosmos_group_agents_container.read_item(
            item=agent_id,
            partition_key=group_id,
        )
    except exceptions.CosmosResourceNotFoundError:
        return False

    try:
        keyvault_agent_delete_helper(agent, agent.get("id", agent_id), scope="group")
        cosmos_group_agents_container.delete_item(
            item=agent_id,
            partition_key=group_id,
        )
        return True
    except Exception as exc:
        current_app.logger.error(
            "Error deleting group agent %s for %s: %s", agent_id, group_id, exc
        )
        raise


def validate_group_agent_payload(payload: Dict[str, Any], partial: bool = False) -> None:
    """Validate incoming payload data for group agents."""
    if not isinstance(payload, dict):
        raise ValueError("Agent payload must be an object")

    required_fields = (
        "name",
        "display_name",
        "description",
        "instructions",
        "actions_to_load",
        "other_settings",
        "max_completion_tokens",
    )

    if not partial:
        missing = [field for field in required_fields if field not in payload]
        if missing:
            raise ValueError(f"Missing required agent fields: {', '.join(missing)}")

    if "name" in payload:
        name = payload["name"]
        if not isinstance(name, str) or not name or not _NAME_PATTERN.fullmatch(name):
            raise ValueError("Agent name must be alphanumeric with optional underscores or hyphens")

    if "display_name" in payload and not isinstance(payload["display_name"], str):
        raise ValueError("display_name must be a string")

    if "description" in payload and not isinstance(payload["description"], str):
        raise ValueError("description must be a string")

    if "instructions" in payload and not isinstance(payload["instructions"], str):
        raise ValueError("instructions must be a string")

    if "actions_to_load" in payload:
        actions = payload["actions_to_load"]
        if not isinstance(actions, list) or not all(isinstance(a, str) for a in actions):
            raise ValueError("actions_to_load must be a list of strings")

    if "other_settings" in payload and not isinstance(payload["other_settings"], dict):
        raise ValueError("other_settings must be an object")

    if "max_completion_tokens" in payload:
        tokens = payload["max_completion_tokens"]
        if not isinstance(tokens, int):
            raise ValueError("max_completion_tokens must be an integer")


def _clean_agent(agent: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = {k: v for k, v in agent.items() if not k.startswith("_")}
    cleaned = keyvault_agent_get_helper(
        cleaned,
        cleaned.get("id", ""),
        scope="group",
    )
    if cleaned.get("max_completion_tokens") is None:
        cleaned["max_completion_tokens"] = -1
    cleaned.setdefault("is_global", False)
    cleaned.setdefault("is_group", True)
    cleaned.setdefault("agent_type", "local")
    return cleaned
