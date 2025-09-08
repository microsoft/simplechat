# functions_personal_agents.py

"""
Personal Agents Management

This module handles all operations related to personal agents stored in the 
personal_agents container with user_id partitioning.
"""

import uuid
from datetime import datetime
from azure.cosmos import exceptions
from flask import current_app
import logging

def get_personal_agents(user_id):
    """
    Fetch all personal agents for a user.
    
    Args:
        user_id (str): The user's unique identifier
        
    Returns:
        list: List of agent dictionaries
    """
    try:
        from config import cosmos_personal_agents_container
        
        query = "SELECT * FROM c WHERE c.user_id = @user_id"
        parameters = [{"name": "@user_id", "value": user_id}]
        
        agents = list(cosmos_personal_agents_container.query_items(
            query=query,
            parameters=parameters,
            partition_key=user_id
        ))
        
        # Remove Cosmos metadata for cleaner response
        cleaned_agents = []
        for agent in agents:
            cleaned_agent = {k: v for k, v in agent.items() if not k.startswith('_')}
            cleaned_agents.append(cleaned_agent)
            
        return cleaned_agents
        
    except exceptions.CosmosResourceNotFoundError:
        return []
    except Exception as e:
        current_app.logger.error(f"Error fetching personal agents for user {user_id}: {e}")
        return []

def get_personal_agent(user_id, agent_id):
    """
    Fetch a specific personal agent.
    
    Args:
        user_id (str): The user's unique identifier
        agent_id (str): The agent's unique identifier
        
    Returns:
        dict: Agent dictionary or None if not found
    """
    try:
        from config import cosmos_personal_agents_container
        
        agent = cosmos_personal_agents_container.read_item(
            item=agent_id,
            partition_key=user_id
        )
        
        # Remove Cosmos metadata
        cleaned_agent = {k: v for k, v in agent.items() if not k.startswith('_')}
        return cleaned_agent
        
    except exceptions.CosmosResourceNotFoundError:
        return None
    except Exception as e:
        current_app.logger.error(f"Error fetching agent {agent_id} for user {user_id}: {e}")
        return None

def save_personal_agent(user_id, agent_data):
    """
    Save or update a personal agent.
    
    Args:
        user_id (str): The user's unique identifier
        agent_data (dict): Agent configuration data
        
    Returns:
        dict: Saved agent data with ID
    """
    try:
        from config import cosmos_personal_agents_container
        
        # Ensure required fields
        if 'id' not in agent_data:
            agent_data['id'] = str(f"{user_id}_{agent_data.get('name', 'default')}")
            
        agent_data['user_id'] = user_id
        agent_data['last_updated'] = datetime.utcnow().isoformat()
        
        # Validate required fields
        required_fields = ['name', 'display_name', 'description', 'instructions']
        for field in required_fields:
            if field not in agent_data:
                agent_data[field] = ''
                
        # Set defaults for optional fields
        agent_data.setdefault('azure_openai_gpt_deployment', '')
        agent_data.setdefault('azure_openai_gpt_api_version', '')
        agent_data.setdefault('azure_agent_apim_gpt_deployment', '')
        agent_data.setdefault('azure_agent_apim_gpt_api_version', '')
        agent_data.setdefault('enable_agent_gpt_apim', False)
        agent_data.setdefault('actions_to_load', [])
        agent_data.setdefault('other_settings', {})
        agent_data.setdefault('is_global', False)
        
        result = cosmos_personal_agents_container.upsert_item(body=agent_data)
        
        # Remove Cosmos metadata from response
        cleaned_result = {k: v for k, v in result.items() if not k.startswith('_')}
        return cleaned_result
        
    except Exception as e:
        current_app.logger.error(f"Error saving agent for user {user_id}: {e}")
        raise

def delete_personal_agent(user_id, agent_id):
    """
    Delete a personal agent.
    
    Args:
        user_id (str): The user's unique identifier
        agent_id (str): The agent's unique identifier OR name
        
    Returns:
        bool: True if deleted, False if not found
    """
    try:
        from config import cosmos_personal_agents_container
        
        # Try to find the agent first to get the correct ID
        # Check if agent_id is actually a name and we need to find the real ID
        agent = get_personal_agent(user_id, agent_id)
        if not agent:
            # Try to find by name if direct ID lookup failed
            agents = get_personal_agents(user_id)
            agent = next((a for a in agents if a['name'] == agent_id), None)
            
        if not agent:
            return False
            
        cosmos_personal_agents_container.delete_item(
            item=agent['id'],
            partition_key=user_id
        )
        return True
        
    except exceptions.CosmosResourceNotFoundError:
        return False
    except Exception as e:
        current_app.logger.error(f"Error deleting agent {agent_id} for user {user_id}: {e}")
        raise

def ensure_migration_complete(user_id):
    """
    Ensure that migration is complete by checking for and cleaning up any remaining legacy data.
    This is more thorough than just checking if personal container is empty.
    
    Args:
        user_id (str): The user's unique identifier
        
    Returns:
        int: Number of agents migrated (0 if already migrated)
    """
    try:
        from functions_settings import get_user_settings, update_user_settings
        
        user_settings = get_user_settings(user_id)
        agents = user_settings.get('settings', {}).get('agents', [])
        
        # If there are still legacy agents, migrate them
        if agents:
            # Check if we already have personal agents to avoid duplicate migration
            existing_personal_agents = get_personal_agents(user_id)
            
            # Only migrate if we don't already have personal agents or if legacy count is higher
            if not existing_personal_agents or len(agents) > len(existing_personal_agents):
                return migrate_agents_from_user_settings(user_id)
            else:
                # Clean up legacy data without migration (already migrated)
                settings_to_update = user_settings.get('settings', {})
                settings_to_update['agents'] = []  # Set to empty array instead of removing
                update_user_settings(user_id, settings_to_update)
                current_app.logger.info(f"Cleaned up legacy agent data for user {user_id} (already migrated)")
                return 0
        
        return 0
        
    except Exception as e:
        current_app.logger.error(f"Error ensuring agent migration complete for user {user_id}: {e}")
        return 0

def migrate_agents_from_user_settings(user_id):
    """
    Migrate agents from user settings to personal_agents container.
    
    Args:
        user_id (str): The user's unique identifier
        
    Returns:
        int: Number of agents migrated
    """
    try:
        from functions_settings import get_user_settings, update_user_settings
        
        user_settings = get_user_settings(user_id)
        agents = user_settings.get('settings', {}).get('agents', [])
        
        # Get existing personal agents to avoid duplicates
        existing_personal_agents = get_personal_agents(user_id)
        existing_agent_names = {agent['name'] for agent in existing_personal_agents}
        
        migrated_count = 0
        for agent in agents:
            try:
                # Skip if agent already exists in personal container
                if agent.get('name') in existing_agent_names:
                    current_app.logger.info(f"Skipping migration of agent '{agent.get('name')}' - already exists")
                    continue
                
                # Ensure agent has an ID
                if 'id' not in agent:
                    agent['id'] = str(uuid.uuid4())
                    
                save_personal_agent(user_id, agent)
                migrated_count += 1
                
            except Exception as e:
                current_app.logger.error(f"Error migrating agent {agent.get('name', 'unknown')} for user {user_id}: {e}")
                
        # Always remove agents from user settings after processing (even if no new ones migrated)
        settings_to_update = user_settings.get('settings', {})
        settings_to_update['agents'] = []  # Set to empty array instead of removing
        update_user_settings(user_id, settings_to_update)
            
        current_app.logger.info(f"Migrated {migrated_count} new agents for user {user_id}, cleaned up legacy data")
        return migrated_count
        
    except Exception as e:
        current_app.logger.error(f"Error during agent migration for user {user_id}: {e}")
        return 0

def get_selected_agent(user_id):
    """
    Get the user's selected agent preference.
    
    Args:
        user_id (str): The user's unique identifier
        
    Returns:
        dict: Selected agent info or None
    """
    try:
        from functions_settings import get_user_settings
        
        user_settings = get_user_settings(user_id)
        selected_agent = user_settings.get('settings', {}).get('selected_agent')
        
        return selected_agent
        
    except Exception as e:
        current_app.logger.error(f"Error getting selected agent for user {user_id}: {e}")
        return None

def set_selected_agent(user_id, agent_name, is_global=False):
    """
    Set the user's selected agent preference.
    
    Args:
        user_id (str): The user's unique identifier
        agent_name (str): Name of the selected agent
        is_global (bool): Whether the agent is global or personal
        
    Returns:
        bool: True if successful
    """
    try:
        from functions_settings import get_user_settings, update_user_settings
        
        user_settings = get_user_settings(user_id)
        settings_to_update = user_settings.get('settings', {})
        
        settings_to_update['selected_agent'] = {
            'name': agent_name,
            'is_global': is_global
        }
        
        update_user_settings(user_id, settings_to_update)
        return True
        
    except Exception as e:
        current_app.logger.error(f"Error setting selected agent for user {user_id}: {e}")
        return False
