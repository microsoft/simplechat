# functions_global_agents.py
"""
Global agents management functions.

This module provides functions for managing global agents stored in the
global_agents container with id partitioning.
"""

import uuid
import json
import traceback
from datetime import datetime


def get_global_agents():
    """
    Get all global agents.
    
    Returns:
        list: List of global agent dictionaries
    """
    try:
        from config import cosmos_global_agents_container
        
        agents = list(cosmos_global_agents_container.query_items(
            query="SELECT * FROM c",
            enable_cross_partition_query=True
        ))
        
        return agents
        
    except Exception as e:
        print(f"❌ Error getting global agents: {str(e)}")
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
        from config import cosmos_global_agents_container
        
        agent = cosmos_global_agents_container.read_item(
            item=agent_id,
            partition_key=agent_id
        )
        
        print(f"✅ Found global agent: {agent_id}")
        return agent
        
    except Exception as e:
        print(f"❌ Error getting global agent {agent_id}: {str(e)}")
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
        from config import cosmos_global_agents_container
        
        # Ensure required fields
        if 'id' not in agent_data:
            agent_data['id'] = str(uuid.uuid4())
        
        # Add metadata
        agent_data['is_global'] = True
        agent_data['created_at'] = datetime.utcnow().isoformat()
        agent_data['updated_at'] = datetime.utcnow().isoformat()
        
        print(f"💾 Saving global agent: {agent_data.get('name', 'Unknown')}")
        
        result = cosmos_global_agents_container.upsert_item(body=agent_data)
        
        print(f"✅ Global agent saved successfully: {result['id']}")
        return result
        
    except Exception as e:
        print(f"❌ Error saving global agent: {str(e)}")
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
        from config import cosmos_global_agents_container
        
        print(f"🗑️ Deleting global agent: {agent_id}")
        
        cosmos_global_agents_container.delete_item(
            item=agent_id,
            partition_key=agent_id
        )
        
        print(f"✅ Global agent deleted successfully: {agent_id}")
        return True
        
    except Exception as e:
        print(f"❌ Error deleting global agent {agent_id}: {str(e)}")
        traceback.print_exc()
        return False
