#!/usr/bin/env python3
"""
Test Plugin Duplication Fix

This test ensures that saving plugins doesn't create duplicates
when the same plugin name is saved multiple times.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_plugin_duplication_fix():
    """Test that saving plugins with same name doesn't create duplicates."""
    print("🔍 Testing Plugin Duplication Fix...")
    
    try:
        # Import required functions
        from functions_personal_actions import save_personal_action, get_personal_actions, delete_personal_action
        
        test_user_id = "test-user-duplication-fix"
        
        # Clean up any existing test data
        existing_actions = get_personal_actions(test_user_id)
        for action in existing_actions:
            if action['name'].startswith('test_duplication'):
                delete_personal_action(test_user_id, action['name'])
        
        # Test plugin data
        test_plugin = {
            'name': 'test_duplication_plugin',
            'displayName': 'Test Duplication Plugin',
            'type': 'sql_schema',
            'description': 'Test plugin for duplication fix',
            'endpoint': 'sql://sql_schema',
            'auth': {'type': 'identity'},
            'metadata': {},
            'additionalFields': {}
        }
        
        print("📝 Saving plugin for the first time...")
        result1 = save_personal_action(test_user_id, test_plugin.copy())
        first_id = result1['id']
        print(f"   First save ID: {first_id}")
        
        # Check there's only one plugin
        actions_after_first = get_personal_actions(test_user_id)
        duplication_plugins = [a for a in actions_after_first if a['name'] == 'test_duplication_plugin']
        assert len(duplication_plugins) == 1, f"Expected 1 plugin, found {len(duplication_plugins)}"
        print(f"✅ After first save: Found {len(duplication_plugins)} plugin(s)")
        
        print("📝 Saving same plugin again (simulating update)...")
        test_plugin['description'] = 'Updated description'
        result2 = save_personal_action(test_user_id, test_plugin.copy())
        second_id = result2['id']
        print(f"   Second save ID: {second_id}")
        
        # Check ID is preserved and no duplicates
        assert first_id == second_id, f"ID should be preserved: {first_id} != {second_id}"
        print(f"✅ ID preserved: {first_id} == {second_id}")
        
        actions_after_second = get_personal_actions(test_user_id)
        duplication_plugins = [a for a in actions_after_second if a['name'] == 'test_duplication_plugin']
        assert len(duplication_plugins) == 1, f"Expected 1 plugin after update, found {len(duplication_plugins)}"
        print(f"✅ After second save: Found {len(duplication_plugins)} plugin(s)")
        
        # Verify the description was updated
        updated_plugin = duplication_plugins[0]
        assert updated_plugin['description'] == 'Updated description', "Description should be updated"
        print("✅ Plugin data was updated correctly")
        
        print("📝 Saving multiple different plugins...")
        # Save a different plugin to ensure new plugins still work
        different_plugin = {
            'name': 'test_duplication_different',
            'displayName': 'Different Plugin',
            'type': 'sql_query',
            'description': 'Different test plugin',
            'endpoint': 'sql://sql_query',
            'auth': {'type': 'identity'},
            'metadata': {},
            'additionalFields': {}
        }
        
        result3 = save_personal_action(test_user_id, different_plugin.copy())
        third_id = result3['id']
        print(f"   Different plugin ID: {third_id}")
        
        # Verify we now have 2 different plugins
        final_actions = get_personal_actions(test_user_id)
        test_plugins = [a for a in final_actions if a['name'].startswith('test_duplication')]
        assert len(test_plugins) == 2, f"Expected 2 test plugins, found {len(test_plugins)}"
        print(f"✅ Final check: Found {len(test_plugins)} test plugin(s)")
        
        # Verify all IDs are different
        plugin_ids = [p['id'] for p in test_plugins]
        assert len(set(plugin_ids)) == len(plugin_ids), "All plugin IDs should be unique"
        print("✅ All plugin IDs are unique")
        
        # Clean up test data
        for action in test_plugins:
            delete_personal_action(test_user_id, action['name'])
        print("🧹 Cleaned up test data")
        
        print("✅ Plugin duplication fix test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_plugin_duplication_fix()
    sys.exit(0 if success else 1)
