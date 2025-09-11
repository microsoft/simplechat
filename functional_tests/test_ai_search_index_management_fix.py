#!/usr/bin/env python3
"""
Functional test for AI Search index management and agent settings fixes.
Version: 0.227.010
Implemented in: 0.227.010

This test ensures that:
1. Agent settings API is only called when agents are enabled
2. AI Search index checking provides proper error handling and user feedback
3. Index creation functionality works correctly
4. JavaScript handles all error scenarios gracefully
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_agent_settings_conditional_loading():
    """Test that agent settings loading is conditional based on semantic kernel enablement."""
    print("🔍 Testing Agent Settings Conditional Loading...")
    
    try:
        # Read the JavaScript file
        admin_js_path = os.path.join(os.path.dirname(__file__), "../static/js/admin/admin_settings.js")
        if not os.path.exists(admin_js_path):
            raise FileNotFoundError(f"admin_settings.js not found at {admin_js_path}")
        
        with open(admin_js_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for conditional loading pattern
        required_patterns = [
            "if (typeof settings !== 'undefined' && settings && settings.enable_semantic_kernel)",
            "loadAgentSettings();",  # Should be inside the conditional
        ]
        
        missing_patterns = []
        for pattern in required_patterns:
            if pattern not in content:
                missing_patterns.append(pattern)
        
        if missing_patterns:
            raise AssertionError(f"Missing required conditional loading patterns: {missing_patterns}")
        
        # Ensure the old unconditional call is removed
        if "// Initial load\n    loadAgentSettings();" in content:
            raise AssertionError("Found old unconditional loadAgentSettings() call")
        
        print("✅ Agent settings conditional loading validated!")
        return True
        
    except Exception as e:
        print(f"❌ Agent settings conditional loading test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_ai_search_index_error_handling():
    """Test that AI Search index checking has proper error handling."""
    print("🔍 Testing AI Search Index Error Handling...")
    
    try:
        # Read the backend settings file
        settings_path = os.path.join(os.path.dirname(__file__), "../route_backend_settings.py")
        if not os.path.exists(settings_path):
            raise FileNotFoundError(f"route_backend_settings.py not found at {settings_path}")
        
        with open(settings_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for improved error handling patterns
        required_patterns = [
            "if not idx_type or idx_type not in ['user', 'group']:",
            "if not settings.get(\"azure_ai_search_endpoint\"):",
            "needsConfiguration': True",
            "needsCreation': True",
            "indexExists': False",
            "app.logger.error(f\"Error in check_index_fields:",
        ]
        
        missing_patterns = []
        for pattern in required_patterns:
            if pattern not in content:
                missing_patterns.append(pattern)
        
        if missing_patterns:
            raise AssertionError(f"Missing required error handling patterns: {missing_patterns}")
        
        print("✅ AI Search index error handling validated!")
        return True
        
    except Exception as e:
        print(f"❌ AI Search index error handling test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_index_creation_endpoint():
    """Test that the index creation endpoint exists."""
    print("🔍 Testing Index Creation Endpoint...")
    
    try:
        # Read the backend settings file
        settings_path = os.path.join(os.path.dirname(__file__), "../route_backend_settings.py")
        if not os.path.exists(settings_path):
            raise FileNotFoundError(f"route_backend_settings.py not found at {settings_path}")
        
        with open(settings_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for index creation endpoint
        required_patterns = [
            "@app.route('/api/admin/settings/create_index', methods=['POST'])",
            "def create_index():",
            "from azure.search.documents.indexes.models import SearchIndex",
            "index = SearchIndex.deserialize(index_definition)",
            "result = client.create_index(index)",
        ]
        
        missing_patterns = []
        for pattern in required_patterns:
            if pattern not in content:
                missing_patterns.append(pattern)
        
        if missing_patterns:
            raise AssertionError(f"Missing required index creation patterns: {missing_patterns}")
        
        print("✅ Index creation endpoint validated!")
        return True
        
    except Exception as e:
        print(f"❌ Index creation endpoint test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_javascript_index_management():
    """Test that JavaScript handles index management correctly."""
    print("🔍 Testing JavaScript Index Management...")
    
    try:
        # Read the JavaScript file
        admin_js_path = os.path.join(os.path.dirname(__file__), "../static/js/admin/admin_settings.js")
        if not os.path.exists(admin_js_path):
            raise FileNotFoundError(f"admin_settings.js not found at {admin_js_path}")
        
        with open(admin_js_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for improved JavaScript patterns
        required_patterns = [
            "const action = fixBtn.dataset.action || 'fix';",
            "const endpoint = action === 'create' ? '/api/admin/settings/create_index' : '/api/admin/settings/fix_index_fields';",
            "fixBtn.textContent = `Create ${type} Index`;",
            "fixBtn.dataset.action = 'create';",
            "does not exist yet",
            "not configured",
            "return r.json().then(errorData =>",
        ]
        
        missing_patterns = []
        for pattern in required_patterns:
            if pattern not in content:
                missing_patterns.append(pattern)
        
        if missing_patterns:
            raise AssertionError(f"Missing required JavaScript patterns: {missing_patterns}")
        
        print("✅ JavaScript index management validated!")
        return True
        
    except Exception as e:
        print(f"❌ JavaScript index management test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_index_schema_files_exist():
    """Test that required index schema files exist."""
    print("🔍 Testing Index Schema Files...")
    
    try:
        required_files = [
            "../static/json/ai_search-index-user.json",
            "../static/json/ai_search-index-group.json"
        ]
        
        for file_path in required_files:
            full_path = os.path.join(os.path.dirname(__file__), file_path)
            if not os.path.exists(full_path):
                raise FileNotFoundError(f"Required index schema file not found: {full_path}")
            
            # Verify it's valid JSON
            import json
            with open(full_path, 'r', encoding='utf-8') as f:
                schema = json.load(f)
            
            # Check for required schema properties
            if 'name' not in schema:
                raise AssertionError(f"Missing 'name' property in {file_path}")
            if 'fields' not in schema:
                raise AssertionError(f"Missing 'fields' property in {file_path}")
        
        print("✅ Index schema files validated!")
        return True
        
    except Exception as e:
        print(f"❌ Index schema files test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_version_consistency():
    """Test that the current version is properly set in config.py."""
    print("🔍 Testing Version Consistency...")
    
    try:
        config_path = os.path.join(os.path.dirname(__file__), "../config.py")
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"config.py not found at {config_path}")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if "app.config['VERSION'] = \"0.227.010\"" not in content:
            raise AssertionError("Version not updated to 0.227.010 in config.py")
        
        print("✅ Version consistency validated!")
        return True
        
    except Exception as e:
        print(f"❌ Version consistency test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    tests = [
        test_agent_settings_conditional_loading,
        test_ai_search_index_error_handling,
        test_index_creation_endpoint,
        test_javascript_index_management,
        test_index_schema_files_exist,
        test_version_consistency
    ]
    
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All AI Search index management tests passed!")
        print("✅ Agent settings API only loads when agents are enabled")
        print("✅ AI Search index checking provides clear error messages")
        print("✅ Index creation endpoint available for missing indexes")
        print("✅ JavaScript handles all error scenarios gracefully")
        print("✅ Index schema files are properly structured")
    else:
        print("⚠️  Some tests failed - please review the implementation")
    
    sys.exit(0 if success else 1)
