#!/usr/bin/env python3
"""
Functional test for agent-related JavaScript loading fixes.
Version: 0.227.007
Implemented in: 0.227.007

This test validates that agent/plugin JavaScript files are only loaded when agents are enabled,
and that error handling is improved for Azure AI Search index checking.
"""

import sys
import os
import re

# Add the parent directory to the system path to import application modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_conditional_js_loading():
    """Test that agent JS files are conditionally loaded based on settings."""
    print("🔍 Testing conditional JavaScript loading...")
    
    try:
        # Read admin_settings.html file
        admin_settings_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'templates',
            'admin_settings.html'
        )
        
        with open(admin_settings_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that admin_plugins.js is conditionally loaded
        plugin_js_pattern = r'{% if settings\.enable_semantic_kernel %}.*admin_plugins\.js.*{% endif %}'
        if not re.search(plugin_js_pattern, content, re.DOTALL):
            print("❌ Test failed: admin_plugins.js is not conditionally loaded")
            return False
        
        # Check that admin_agents.js is conditionally loaded
        agents_js_pattern = r'{% if settings\.enable_semantic_kernel %}.*admin_agents\.js.*{% endif %}'
        if not re.search(agents_js_pattern, content, re.DOTALL):
            print("❌ Test failed: admin_agents.js is not conditionally loaded")
            return False
        
        # Verify that admin_settings.js is still loaded unconditionally
        if 'admin_settings.js' not in content:
            print("❌ Test failed: admin_settings.js should still be loaded")
            return False
        
        # Check that the conditional block exists properly
        conditional_block = '{% if settings.enable_semantic_kernel %}'
        if conditional_block not in content:
            print("❌ Test failed: Conditional block for semantic kernel not found")
            return False
        
        print("✅ Conditional JavaScript loading test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_improved_error_handling():
    """Test that error handling has been improved in admin_settings.js."""
    print("🔍 Testing improved error handling...")
    
    try:
        # Read admin_settings.js file
        admin_js_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'static',
            'js',
            'admin',
            'admin_settings.js'
        )
        
        with open(admin_js_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for proper response status checking
        if '.then(r => {' not in content or 'if (!r.ok)' not in content:
            print("❌ Test failed: Proper response status checking not found")
            return False
        
        # Check for proper error handling in index checking
        if 'Unable to check' not in content or 'this is normal if Azure AI Search is not configured' not in content:
            print("❌ Test failed: Improved error message for index checking not found")
            return False
        
        # Check that we're not calling r.json() directly on potentially failed responses
        direct_json_pattern = r'\.then\(r => r\.json\(\)\)'
        if re.search(direct_json_pattern, content):
            print("❌ Test failed: Direct .json() call on response still exists")
            return False
        
        # Check for proper error message handling
        if 'err.message || err' not in content:
            print("❌ Test failed: Proper error message handling not found")
            return False
        
        print("✅ Improved error handling test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_no_unconditional_agent_calls():
    """Test that no unconditional agent-related calls remain in templates."""
    print("🔍 Testing for unconditional agent calls...")
    
    try:
        # Read admin_settings.html file
        admin_settings_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'templates',
            'admin_settings.html'
        )
        
        with open(admin_settings_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that there are no direct calls to agent functions outside conditionals
        problematic_calls = [
            'loadAllAdminAgentData',
            'initializeAdminAgentUI',
            'loadOrchestrationSettings',
            'loadPlugins'
        ]
        
        for call in problematic_calls:
            if call in content:
                print(f"❌ Test failed: Unconditional call to {call} found in template")
                return False
        
        print("✅ No unconditional agent calls test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_js_file_structure():
    """Test that JavaScript files are properly structured."""
    print("🔍 Testing JavaScript file structure...")
    
    try:
        # Check that agent JS files exist (they should exist but only be loaded conditionally)
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        admin_plugins_path = os.path.join(base_path, 'static', 'js', 'admin', 'admin_plugins.js')
        admin_agents_path = os.path.join(base_path, 'static', 'js', 'admin', 'admin_agents.js')
        admin_settings_path = os.path.join(base_path, 'static', 'js', 'admin', 'admin_settings.js')
        
        if not os.path.exists(admin_plugins_path):
            print("❌ Test failed: admin_plugins.js file does not exist")
            return False
        
        if not os.path.exists(admin_agents_path):
            print("❌ Test failed: admin_agents.js file does not exist")
            return False
        
        if not os.path.exists(admin_settings_path):
            print("❌ Test failed: admin_settings.js file does not exist")
            return False
        
        print("✅ JavaScript file structure test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 Running Agent JavaScript Loading Fix Validation Tests")
    print("=" * 60)
    
    tests = [
        test_conditional_js_loading,
        test_improved_error_handling,
        test_no_unconditional_agent_calls,
        test_js_file_structure
    ]
    
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All tests passed! Agent JavaScript loading fixes are working correctly.")
        print("\n📋 Summary of fixes:")
        print("   ✅ Agent JS files only load when agents are enabled")
        print("   ✅ Improved error handling for Azure AI Search calls")
        print("   ✅ No more 'Failed to load actions' popup when agents disabled")
        print("   ✅ Graceful handling of 500 errors from unconfigured services")
    else:
        print("❌ Some tests failed. Please review the issues above.")
    
    sys.exit(0 if success else 1)
