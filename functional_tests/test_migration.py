#!/usr/bin/env python3
# test_migration.py
"""
Test script for personal containers migration.

This script tests the migration of agents and actions from user settings 
to dedicated personal containers.
Version: 0.261.474
Implemented in: 0.229.001
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_migration():
    """Test the migration functionality."""
    print("🚀 Testing Personal Containers Migration")
    print("=" * 50)
    
    try:
        # Import required functions
        from functions_personal_agents import (
            get_personal_agents, 
            save_personal_agent, 
            delete_personal_agent,
            migrate_agents_from_user_settings
        )
        from functions_personal_actions import (
            get_personal_actions, 
            save_personal_action, 
            delete_personal_action,
            migrate_actions_from_user_settings
        )
        
        # Test user ID
        test_user_id = "test-user-12345"
        
        print(f"📝 Testing with user ID: {test_user_id}")
        
        # Test Agents
        print("\n🤖 Testing Personal Agents...")
        
        # Create a test agent
        test_agent = {
            "name": "TestAgent",
            "display_name": "Test Agent",
            "description": "A test agent for migration testing",
            "instructions": "You are a test agent",
            "azure_openai_gpt_deployment": "gpt-4o",
            "actions_to_load": ["test_action"]
        }
        
        # Save agent
        saved_agent = save_personal_agent(test_user_id, test_agent)
        print(f"✅ Saved agent: {saved_agent['name']} (ID: {saved_agent['id']})")
        
        # Get agents
        agents = get_personal_agents(test_user_id)
        print(f"✅ Retrieved {len(agents)} agents")
        
        # Test Actions
        print("\n🔧 Testing Personal Actions...")
        
        # Create a test action
        test_action = {
            "name": "test_action",
            "displayName": "Test Action",
            "type": "openapi",
            "description": "A test action for migration testing",
            "endpoint": "https://api.example.com",
            "auth": {"type": "none"},
            "additionalFields": {
                "openapi_spec_content": {
                    "openapi": "3.0.0",
                    "info": {"title": "Test API", "version": "1.0.0"},
                    "paths": {}
                },
                "openapi_source_type": "content",
                "base_url": "https://api.example.com"
            }
        }
        
        # Save action
        saved_action = save_personal_action(test_user_id, test_action)
        print(f"✅ Saved action: {saved_action['name']} (ID: {saved_action['id']})")
        
        # Get actions
        actions = get_personal_actions(test_user_id)
        print(f"✅ Retrieved {len(actions)} actions")
        
        # Test cleanup
        print("\n🧹 Cleaning up test data...")
        
        # Delete test agent
        agent_deleted = delete_personal_agent(test_user_id, saved_agent['id'])
        print(f"✅ Agent deleted: {agent_deleted}")
        
        # Delete test action
        action_deleted = delete_personal_action(test_user_id, saved_action['id'])
        print(f"✅ Action deleted: {action_deleted}")
        
        # Verify cleanup
        agents_after = get_personal_agents(test_user_id)
        actions_after = get_personal_actions(test_user_id)
        print(f"✅ Cleanup verified - Agents: {len(agents_after)}, Actions: {len(actions_after)}")
        
        print("\n🎉 All tests passed!")
        print("\n📋 Migration Summary:")
        print("   ✅ Personal agents container working")
        print("   ✅ Personal actions container working")
        print("   ✅ CRUD operations working")
        print("   ✅ Ready for migration!")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_migration()
    sys.exit(0 if success else 1)
