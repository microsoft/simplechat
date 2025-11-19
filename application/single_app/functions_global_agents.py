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


def ensure_default_global_agent_exists():
    """
    Ensure at least one global agent exists in the global_agents container.
    If none exist, create a default global agent (using the researcher agent template).
    """
    try:
        agents = get_global_agents() or []
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
                "agent_type": "local",
                "instructions": (
                    "You are a highly capable research assistant. Your role is to help the user investigate academic, technical, and real-world topics by finding relevant information, summarizing key points, identifying knowledge gaps, and suggesting credible sources for further study.\n\n"
                    "You must always:\n- Think step-by-step and work methodically.\n- Distinguish between fact, inference, and opinion.\n- Clearly state your assumptions when making inferences.\n- Cite authoritative sources when possible (e.g., peer-reviewed journals, academic publishers, government agencies).\n- Avoid speculation unless explicitly asked for.\n- When asked to summarize, preserve the intent, nuance, and technical accuracy of the original content.\n- When generating questions, aim for depth and clarity to guide rigorous inquiry.\n- Present answers in a clear, structured format using bullet points, tables, or headings when appropriate.\n\n"
                    "Use a professional, neutral tone. Do not anthropomorphize yourself or refer to yourself as an AI unless the user specifically asks you to reflect on your capabilities. Remain focused on delivering objective, actionable research insights.\n\n"
                    "If you encounter ambiguity or uncertainty, ask clarifying questions rather than assuming."
                ),
                "actions_to_load": [],
                "other_settings": {},
                "max_completion_tokens": 4096
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
        global_selected = settings.get("global_selected_agent") if settings else None
        if not isinstance(global_selected, dict):
            needs_default = True
        elif global_selected.get("name", "") == "":
            needs_default = True
        if settings and needs_default:
            settings["global_selected_agent"] = {
                "name": default_agent["name"],
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

def get_global_agents():
    """
    Get all global agents.
    
    Returns:
        list: List of global agent dictionaries
    """
    try:
        agents = list(cosmos_global_agents_container.query_items(
            query="SELECT * FROM c",
            enable_cross_partition_query=True
        ))
        # Mask or replace sensitive keys for UI display
        agents = [keyvault_agent_get_helper(agent, agent.get('id', ''), scope="global") for agent in agents]
        for agent in agents:
            if agent.get('max_completion_tokens') is None:
                agent['max_completion_tokens'] = -1
            agent.setdefault('is_global', True)
            agent.setdefault('is_group', False)
            agent.setdefault('agent_type', 'local')
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


def save_global_agent(agent_data):
    """
    Save or update a global agent.
    
    Args:
        agent_data (dict): Agent data to save
        
    Returns:
        dict: Saved agent data or None if failed
    """
    try:
        # Ensure required fields
        user_id = get_current_user_id()
        if 'id' not in agent_data:
            agent_data['id'] = str(uuid.uuid4())
        # Add metadata
        agent_data['is_global'] = True
        agent_data['is_group'] = False
        agent_data.setdefault('agent_type', 'local')
        agent_data['created_at'] = datetime.utcnow().isoformat()
        agent_data['updated_at'] = datetime.utcnow().isoformat()
        log_event(
            "Saving global agent.",
            extra={"agent_name": agent_data.get('name', 'Unknown')},
        )
        print(f"Saving global agent: {agent_data.get('name', 'Unknown')}")
        
        # Use the new helper to store sensitive agent keys in Key Vault
        agent_data = keyvault_agent_save_helper(agent_data, agent_data['id'], scope="global")
        if agent_data.get('max_completion_tokens') is None:
            agent_data['max_completion_tokens'] = -1  # Default value

        result = cosmos_global_agents_container.upsert_item(body=agent_data)
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
