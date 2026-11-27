#!/usr/bin/env python3
# test_bing_web_search_removal.py
"""
Functional test for Bing Web Search removal.
Version: 0.227.007
Implemented in: 0.227.007

This test ensures that Bing Web Search functionality has been completely removed
from the application and no references or dependencies remain.
"""

import sys
import os
import importlib.util

# Add the parent directory to the system path to import application modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_bing_functions_file_removed():
    """Test that functions_bing_search.py file has been removed."""
    print("🔍 Testing Bing functions file removal...")
    
    try:
        # Check if the functions_bing_search.py file exists
        functions_bing_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app',
            'functions_bing_search.py'
        )
        
        if os.path.exists(functions_bing_path):
            print("❌ Test failed: functions_bing_search.py file still exists")
            return False
        
        # Try to import the module (should fail)
        try:
            import functions_bing_search
            print("❌ Test failed: functions_bing_search module can still be imported")
            return False
        except ImportError:
            print("✅ functions_bing_search module is not importable (as expected)")
        
        print("✅ Bing functions file removal test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_config_bing_removal():
    """Test that Bing endpoint has been removed from config.py."""
    print("🔍 Testing Bing configuration removal...")
    
    try:
        # Read config.py file
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app',
            'config.py'
        )
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config_content = f.read()
        
        # Check for Bing references
        if 'bing_search_endpoint' in config_content:
            print("❌ Test failed: bing_search_endpoint still found in config.py")
            return False
        
        if 'api.bing.microsoft.com' in config_content:
            print("❌ Test failed: Bing API endpoint still found in config.py")
            return False
        
        print("✅ Bing configuration removal test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_settings_bing_removal():
    """Test that Bing settings have been removed from functions_settings.py."""
    print("🔍 Testing Bing settings removal...")
    
    try:
        # Read functions_settings.py file
        settings_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app',
            'functions_settings.py'
        )
        
        with open(settings_path, 'r', encoding='utf-8') as f:
            settings_content = f.read()
        
        # Check for Bing-related settings
        bing_settings = [
            'enable_web_search',
            'bing_search_key',
            'enable_web_search_apim',
            'azure_apim_web_search_endpoint',
            'azure_apim_web_search_subscription_key'
        ]
        
        for setting in bing_settings:
            if f"'{setting}'" in settings_content:
                print(f"❌ Test failed: {setting} still found in functions_settings.py")
                return False
        
        print("✅ Bing settings removal test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_route_backend_bing_removal():
    """Test that Bing imports and processing have been removed from route_backend_chats.py."""
    print("🔍 Testing Bing backend code removal...")
    
    try:
        # Read route_backend_chats.py file
        route_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app',
            'route_backend_chats.py'
        )
        
        with open(route_path, 'r', encoding='utf-8') as f:
            route_content = f.read()
        
        # Check for Bing imports
        if 'from functions_bing_search import' in route_content:
            print("❌ Test failed: Bing import still found in route_backend_chats.py")
            return False
        
        # Check for Bing function calls
        if 'process_query_with_bing_and_llm' in route_content:
            print("❌ Test failed: Bing function call still found in route_backend_chats.py")
            return False
        
        # Check that bing_search_enabled variable is no longer extracted from request
        if "bing_search_enabled = data.get('bing_search')" in route_content:
            print("❌ Test failed: bing_search_enabled extraction still found in route_backend_chats.py")
            return False
        
        print("✅ Bing backend code removal test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_template_bing_removal():
    """Test that Bing Web Search UI elements have been removed from templates."""
    print("🔍 Testing Bing template removal...")
    
    try:
        # Check admin_settings.html
        admin_settings_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app',
            'templates',
            'admin_settings.html'
        )
        
        with open(admin_settings_path, 'r', encoding='utf-8') as f:
            admin_content = f.read()
        
        # Check for Bing-related UI elements
        if 'Bing Web Search' in admin_content:
            print("❌ Test failed: 'Bing Web Search' text still found in admin_settings.html")
            return False
        
        if 'enable_web_search' in admin_content:
            print("❌ Test failed: enable_web_search control still found in admin_settings.html")
            return False
        
        # Check chats.html
        chats_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app',
            'templates',
            'chats.html'
        )
        
        with open(chats_path, 'r', encoding='utf-8') as f:
            chats_content = f.read()
        
        # Check for web search button
        if 'search-web-btn' in chats_content:
            print("❌ Test failed: search-web-btn still found in chats.html")
            return False
        
        if 'Search the web using Bing' in chats_content:
            print("❌ Test failed: Bing search tooltip still found in chats.html")
            return False
        
        print("✅ Bing template removal test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_version_updated():
    """Test that the version has been updated to 0.227.007."""
    print("🔍 Testing version update...")
    
    try:
        # Read config.py file
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app',
            'config.py'
        )
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config_content = f.read()
        
        # Check for correct version
        if "app.config['VERSION'] = \"0.227.007\"" not in config_content:
            print("❌ Test failed: Version not updated to 0.227.007 in config.py")
            return False
        
        print("✅ Version update test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 Running Bing Web Search Removal Validation Tests")
    print("=" * 50)
    
    tests = [
        test_bing_functions_file_removed,
        test_config_bing_removal,
        test_settings_bing_removal,
        test_route_backend_bing_removal,
        test_template_bing_removal,
        test_version_updated
    ]
    
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All tests passed! Bing Web Search has been successfully removed.")
    else:
        print("❌ Some tests failed. Please review the issues above.")
    
    sys.exit(0 if success else 1)
