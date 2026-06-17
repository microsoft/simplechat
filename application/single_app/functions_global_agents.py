# functions_global_agents.py
"""
Global agents management functions.

This module provides functions for managing global agents stored in the
global_agents container with id partitioning.
"""

import uuid
import json
import traceback
import logging
from functions_appinsights import log_event
from functions_authentication import get_current_user_id
from datetime import datetime
from config import cosmos_global_agents_container
from functions_keyvault import keyvault_agent_save_helper, keyvault_agent_get_helper, keyvault_agent_delete_helper
from functions_settings import *
from functions_agent_payload import sanitize_agent_payload, AgentPayloadError


def ensure_default_global_agent_exists():
    """
    Ensure at least one global agent exists in the global_agents container.
    If none exist, create a default global agent (using the researcher agent template).
    """
    try:
        agents = get_global_agents(include_disabled=True) or []
        default_agent = None
        if not agents:
            default_agent = {
                "name": "researcher",
                "display_name": "researcher",
                "description": "This agent is detailed to provide researcher capabilities and uses a reasoning and research focused model.",
                "azure_openai_gpt_endpoint": "",
                "azure_openai_gpt_key": "",
                "azure_openai_gpt_deployment": "",
                "azure_openai_gpt_api_version": "",
                "azure_agent_apim_gpt_endpoint": "",
                "azure_agent_apim_gpt_subscription_key": "",
                "azure_agent_apim_gpt_deployment": "",
                "azure_agent_apim_gpt_api_version": "",
                "enable_agent_gpt_apim": False,
                "is_global": True,
                "is_group": False,
                "is_enabled": True,
                "agent_type": "local",
                "instructions": (
                    "You are a highly capable research assistant. Your role is to help the user investigate academic, technical, and real-world topics by finding relevant information, summarizing key points, identifying knowledge gaps, and suggesting credible sources for further study.\n\n"
                    "You must always:\n- Think step-by-step and work methodically.\n- Distinguish between fact, inference, and opinion.\n- Clearly state your assumptions when making inferences.\n- Cite authoritative sources when possible (e.g., peer-reviewed journals, academic publishers, government agencies).\n- Avoid speculation unless explicitly asked for.\n- When asked to summarize, preserve the intent, nuance, and technical accuracy of the original content.\n- When generating questions, aim for depth and clarity to guide rigorous inquiry.\n- Present answers in a clear, structured format using bullet points, tables, or headings when appropriate.\n\n"
                    "Use a professional, neutral tone. Do not anthropomorphize yourself or refer to yourself as an AI unless the user specifically asks you to reflect on your capabilities. Remain focused on delivering objective, actionable research insights.\n\n"
                    "If you encounter ambiguity or uncertainty, ask clarifying questions rather than assuming."
                ),
                "actions_to_load": [],
                "other_settings": {},
                "max_completion_tokens": -1
            }
            save_global_agent(default_agent)
            log_event(
                "Default global agent created.",
                extra={
                    "agent_name": default_agent["name"]
                },
            )
            print("Default global agent created.")
        else:
            log_event(
                "At least one global agent already exists.",
                extra={"existing_agents_count": len(agents)},
            )
            print("At least one global agent already exists.")

        settings = get_settings()
        needs_default = False
        enabled_agents = [agent for agent in agents if agent.get('is_enabled', True)]
        global_selected = settings.get("global_selected_agent") if settings else None
        if not isinstance(global_selected, dict):
            needs_default = True
        elif global_selected.get("name", "") == "":
            needs_default = True
        if settings and needs_default:
            selected_agent = default_agent or (enabled_agents[0] if enabled_agents else agents[0])
            settings["global_selected_agent"] = {
                "name": selected_agent["name"],
                "is_global": True
            }
            save_settings(settings)
    except Exception as e:
        log_event(
            f"Error ensuring default global agent exists: {e}",
            extra={"exception": str(e)},
            level=logging.ERROR,
            exceptionTraceback=True
        )
        print(f"Error ensuring default global agent exists: {e}")
        traceback.print_exc()

def get_global_agents(include_disabled=False):
    """
    Get all global agents.

    Args:
        include_disabled (bool): When True, include disabled agents for admin management.
    
    Returns:
        list: List of global agent dictionaries
    """
    try:
        query = "SELECT * FROM c"
        if not include_disabled:
            query = "SELECT * FROM c WHERE NOT IS_DEFINED(c.is_enabled) OR c.is_enabled = true"

        agents = list(cosmos_global_agents_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        # Mask or replace sensitive keys for UI display
        agents = [keyvault_agent_get_helper(agent, agent.get('id', ''), scope="global") for agent in agents]
        for agent in agents:
            if agent.get('max_completion_tokens') is None:
                agent['max_completion_tokens'] = -1
            agent.setdefault('is_global', True)
            agent.setdefault('is_group', False)
            agent.setdefault('is_enabled', True)
            agent.setdefault('agent_type', 'local')
            agent.setdefault('model_endpoint_id', '')
            agent.setdefault('model_id', '')
            agent.setdefault('model_provider', '')
            agent.setdefault('tags', [])
            agent.setdefault('icon', {})
            # Remove empty reasoning_effort to prevent validation errors
            if agent.get('reasoning_effort') == '':
                agent.pop('reasoning_effort', None)
        return agents
    except Exception as e:
        log_event(
            f"Error getting global agents: {e}",
            extra={"exception": str(e)},
            exceptionTraceback=True
        )
        print(f"Error getting global agents: {str(e)}")
        traceback.print_exc()
        return []


def get_global_agent(agent_id):
    """
    Get a specific global agent by ID.
    
    Args:
        agent_id (str): The agent ID
        
    Returns:
        dict: Agent data or None if not found
    """
    try:
        agent = cosmos_global_agents_container.read_item(
            item=agent_id,
            partition_key=agent_id
        )
        agent = keyvault_agent_get_helper(agent, agent_id, scope="global")
        if agent.get('max_completion_tokens') is None:
            agent['max_completion_tokens'] = -1
        agent.setdefault('is_global', True)
        agent.setdefault('is_group', False)
        agent.setdefault('agent_type', 'local')
        agent.setdefault('model_endpoint_id', '')
        agent.setdefault('model_id', '')
        agent.setdefault('model_provider', '')
        agent.setdefault('tags', [])
        agent.setdefault('icon', {})
        # Remove empty reasoning_effort to prevent validation errors
        if agent.get('reasoning_effort') == '':
            agent.pop('reasoning_effort', None)
        print(f"Found global agent: {agent_id}")
        return agent
    except Exception as e:
        log_event(
            f"Error getting global agent {agent_id}: {e}",
            extra={"agent_id": agent_id, "exception": str(e)},
            level=logging.ERROR,
            exceptionTraceback=True
        )
        print(f"Error getting global agent {agent_id}: {str(e)}")
        return None


def save_global_agent(agent_data, user_id=None):
    """
    Save or update a global agent.
    
    Args:
        agent_data (dict): Agent data to save
        user_id (str, optional): The user ID of the person performing the action
        
    Returns:
        dict: Saved agent data or None if failed
    """
    try:
        if user_id is None:
            user_id = get_current_user_id()
        cleaned_agent = sanitize_agent_payload(agent_data)
        if 'id' not in cleaned_agent:
            cleaned_agent['id'] = str(uuid.uuid4())
        cleaned_agent['is_global'] = True
        cleaned_agent['is_group'] = False
        cleaned_agent.setdefault('tags', [])
        cleaned_agent.setdefault('icon', {})
        now = datetime.utcnow().isoformat()

        # Check if this is a new agent or an update to preserve created_by/created_at
        existing_agent = None
        try:
            existing_agent = cosmos_global_agents_container.read_item(
                item=cleaned_agent['id'],
                partition_key=cleaned_agent['id']
            )
        except Exception:
            pass

        if existing_agent:
            cleaned_agent['created_by'] = existing_agent.get('created_by', user_id)
            cleaned_agent['created_at'] = existing_agent.get('created_at', now)
        else:
            cleaned_agent['created_by'] = user_id
            cleaned_agent['created_at'] = now
        if 'is_enabled' in cleaned_agent:
            cleaned_agent['is_enabled'] = bool(cleaned_agent.get('is_enabled'))
        elif existing_agent is not None:
            cleaned_agent['is_enabled'] = bool(existing_agent.get('is_enabled', True))
        else:
            cleaned_agent['is_enabled'] = True
        cleaned_agent['modified_by'] = user_id
        cleaned_agent['modified_at'] = now
        cleaned_agent['updated_at'] = now
        cleaned_agent.setdefault('model_endpoint_id', '')
        cleaned_agent.setdefault('model_id', '')
        cleaned_agent.setdefault('model_provider', '')
        log_event(
            "Saving global agent.",
            extra={"agent_name": cleaned_agent.get('name', 'Unknown')},
        )
        print(f"Saving global agent: {cleaned_agent.get('name', 'Unknown')}")
        
        # Use the new helper to store sensitive agent keys in Key Vault
        cleaned_agent = keyvault_agent_save_helper(cleaned_agent, cleaned_agent['id'], scope="global", existing_agent=existing_agent)
        if cleaned_agent.get('max_completion_tokens') is None:
            cleaned_agent['max_completion_tokens'] = -1  # Default value
        
        # Remove empty reasoning_effort to avoid schema validation errors
        if cleaned_agent.get('reasoning_effort') == '':
            cleaned_agent.pop('reasoning_effort', None)

        result = cosmos_global_agents_container.upsert_item(body=cleaned_agent)
        log_event(
            "Global agent saved successfully.",
            extra={"agent_id": result['id'], "user_id": user_id},
        )
        print(f"Global agent saved successfully: {result['id']}")
        return result
    except Exception as e:
        log_event(
            f"Error saving global agent: {e}",
            extra={"agent_name": agent_data.get('name', 'Unknown'), "exception": str(e)},
            level=logging.ERROR,
            exceptionTraceback=True
        )
        print(f"Error saving global agent: {str(e)}")
        traceback.print_exc()
        return None


def delete_global_agent(agent_id):
    """
    Delete a global agent.
    
    Args:
        agent_id (str): The agent ID to delete
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        user_id = get_current_user_id()
        print(f"Deleting global agent: {agent_id}")
        agent_dict = get_global_agent(agent_id)
        keyvault_agent_delete_helper(agent_dict, agent_id, scope="global")
        cosmos_global_agents_container.delete_item(
            item=agent_id,
            partition_key=agent_id
        )
        log_event(
            "Global agent deleted successfully.",
            extra={"agent_id": agent_id, "user_id": user_id},
        )
        print(f"Global agent deleted successfully: {agent_id}")
        return True
    except Exception as e:
        log_event(
            f"Error deleting global agent {agent_id}: {e}",
            extra={"agent_id": agent_id, "exception": str(e)},
            level=logging.ERROR,
            exceptionTraceback=True
        )
        print(f"Error deleting global agent {agent_id}: {str(e)}")
        traceback.print_exc()
        return False


def update_global_agent_enabled(agent_id, is_enabled, user_id=None):
    """
    Enable or disable a global agent without rewriting stored secret references.

    Args:
        agent_id (str): The agent ID to update.
        is_enabled (bool): The desired enabled state.
        user_id (str, optional): The user performing the change.

    Returns:
        dict: Updated agent document or None if the operation fails.
    """
    try:
        if user_id is None:
            user_id = get_current_user_id()
        if not user_id:
            user_id = "system"

        agent = cosmos_global_agents_container.read_item(
            item=agent_id,
            partition_key=agent_id
        )
        now = datetime.utcnow().isoformat()
        agent['is_enabled'] = bool(is_enabled)
        agent['modified_by'] = user_id
        agent['modified_at'] = now
        agent['updated_at'] = now
        result = cosmos_global_agents_container.upsert_item(body=agent)
        return result
    except Exception as e:
        log_event(
            f"Error updating enabled state for global agent {agent_id}: {e}",
            extra={"agent_id": agent_id, "exception": str(e), "is_enabled": bool(is_enabled)},
            level=logging.ERROR,
            exceptionTraceback=True
        )
        print(f"Error updating enabled state for global agent {agent_id}: {str(e)}")
        traceback.print_exc()
        return None
