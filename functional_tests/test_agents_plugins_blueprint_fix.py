#!/usr/bin/env python3
# test_agents_plugins_blueprint_fix.py
"""
Functional test for agents and plugins blueprint registration fix.
Version: 0.228.002
Implemented in: 0.228.002

This test ensures that the Flask app blueprint registration issue is resolved
and that agent and plugin API endpoints are properly accessible.
"""

import sys
import os
import requests
from urllib3.exceptions import InsecureRequestWarning

# Suppress SSL warnings for self-signed certificates
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_agents_plugins_endpoints():
    """Test that agent and plugin API endpoints return proper responses."""
    print("🔍 Testing Agent and Plugin API Endpoints...")
    
    base_url = "https://127.0.0.1:5000"
    
    # List of endpoints that were previously returning 404 but should now work
    endpoints_to_test = [
        "/api/orchestration_types",
        "/api/orchestration_settings", 
        "/api/admin/agents",
        "/api/admin/agent/settings",
        "/api/user/plugins",
        "/api/admin/plugins/settings",
        "/api/admin/plugins"
    ]
    
    failed_endpoints = []
    success_count = 0
    
    try:
        for endpoint in endpoints_to_test:
            url = f"{base_url}{endpoint}"
            print(f"  Testing: {endpoint}")
            
            try:
                response = requests.get(url, verify=False, timeout=10)
                
                # We expect either:
                # - 401 (Unauthorized) - endpoint exists but requires auth
                # - 200 (OK) - endpoint works and returns data
                # We should NOT get 404 (Not Found)
                
                if response.status_code == 404:
                    print(f"    ❌ {endpoint} returned 404 (Not Found)")
                    failed_endpoints.append(endpoint)
                elif response.status_code == 401:
                    print(f"    ✅ {endpoint} returned 401 (Unauthorized - endpoint exists)")
                    success_count += 1
                elif response.status_code == 200:
                    print(f"    ✅ {endpoint} returned 200 (OK)")
                    success_count += 1
                else:
                    print(f"    ⚠️ {endpoint} returned {response.status_code}")
                    success_count += 1  # Any non-404 is considered success for this test
                    
            except requests.exceptions.RequestException as e:
                print(f"    ❌ {endpoint} failed with error: {e}")
                failed_endpoints.append(endpoint)
        
        print(f"\n📊 Results: {success_count}/{len(endpoints_to_test)} endpoints working correctly")
        
        if failed_endpoints:
            print(f"❌ Failed endpoints: {failed_endpoints}")
            return False
        else:
            print("✅ All agent and plugin API endpoints are properly registered!")
            return True
            
    except Exception as e:
        print(f"❌ Test failed with unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_flask_app_structure():
    """Test that the Flask app structure is correct by importing the app module."""
    print("\n🔍 Testing Flask App Structure...")
    
    try:
        # Import the app module
        sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))
        import app
        
        # Check that app is a Flask instance
        from flask import Flask
        if not isinstance(app.app, Flask):
            print("❌ app.app is not a Flask instance")
            return False
            
        # Check that blueprints are registered
        expected_blueprints = [
            'admin_plugins',
            'dynamic_plugins', 
            'admin_agents',
            'plugin_validation',
            'migration',
            'plugin_logging'
        ]
        
        registered_blueprints = list(app.app.blueprints.keys())
        print(f"  Registered blueprints: {registered_blueprints}")
        
        missing_blueprints = []
        for bp in expected_blueprints:
            if bp not in registered_blueprints:
                missing_blueprints.append(bp)
        
        if missing_blueprints:
            print(f"❌ Missing blueprints: {missing_blueprints}")
            return False
        
        # Check that routes are registered
        agent_routes = []
        plugin_routes = []
        
        for rule in app.app.url_map.iter_rules():
            rule_str = str(rule.rule)
            if 'agents' in rule_str or 'orchestration' in rule_str:
                agent_routes.append(rule_str)
            elif 'plugins' in rule_str and 'semantic-kernel' not in rule_str:
                plugin_routes.append(rule_str)
        
        print(f"  Agent routes found: {len(agent_routes)}")
        print(f"  Plugin routes found: {len(plugin_routes)}")
        
        if len(agent_routes) == 0:
            print("❌ No agent routes found")
            return False
            
        if len(plugin_routes) == 0:
            print("❌ No plugin routes found") 
            return False
            
        print("✅ Flask app structure is correct!")
        return True
        
    except Exception as e:
        print(f"❌ Flask app structure test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 Running Agent and Plugin Blueprint Registration Fix Test")
    print("=" * 60)
    
    # Test Flask app structure
    structure_test = test_flask_app_structure()
    
    # Test API endpoints
    endpoint_test = test_agents_plugins_endpoints()
    
    # Overall result
    success = structure_test and endpoint_test
    
    print("\n" + "=" * 60)
    if success:
        print("🎉 All tests passed! Agent and plugin blueprints are working correctly.")
    else:
        print("💥 Some tests failed. Check the output above for details.")
    
    print(f"📋 Test Summary:")
    print(f"  Flask Structure: {'✅ PASS' if structure_test else '❌ FAIL'}")
    print(f"  API Endpoints: {'✅ PASS' if endpoint_test else '❌ FAIL'}")
    
    sys.exit(0 if success else 1)
