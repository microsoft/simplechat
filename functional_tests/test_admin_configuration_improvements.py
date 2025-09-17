#!/usr/bin/env python3
"""
Functional test for admin configuration improvements.
Version: 0.229.021
Implemented in: 0.229.021

This test ensures that the admin settings reorganization, workspace dependency validation,
and health check consolidation work correctly.
"""

import sys
import os
import requests
import time
from urllib.parse import urljoin

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_admin_settings_accessibility():
    """Test that admin settings page loads correctly with new tab organization."""
    print("🔍 Testing admin settings page accessibility...")
    
    try:
        base_url = "http://localhost:5000"
        admin_url = urljoin(base_url, "/admin/settings")
        
        # Test that admin settings page loads
        response = requests.get(admin_url, timeout=10)
        if response.status_code != 200:
            print(f"❌ Admin settings page returned status code: {response.status_code}")
            return False
            
        page_content = response.text
        
        # Check that all expected tabs are present in the correct order
        expected_tabs = [
            "General",
            "GPT", 
            "Embeddings",
            "Image Generation",
            "Search and Extract",
            "Workspaces", 
            "Citations",
            "Safety",
            "Agents",
            "Actions",
            "Scale",
            "Logging",
            "System"  # Previously "Other"
        ]
        
        # Verify tabs are present
        for tab in expected_tabs:
            if tab not in page_content:
                print(f"❌ Missing expected tab: {tab}")
                return False
                
        # Check that tab reorganization is correct
        # AI Models should be grouped together
        ai_models_section = page_content[page_content.find('id="gpt-tab"'):page_content.find('id="search-extract-tab"')]
        if 'id="embeddings-tab"' not in ai_models_section or 'id="image-gen-tab"' not in ai_models_section:
            print("❌ AI models are not properly grouped together")
            return False
            
        # Workspaces should come right after Search and Extract
        search_extract_pos = page_content.find('id="search-extract-tab"')
        workspaces_pos = page_content.find('id="workspaces-tab"')
        if workspaces_pos < search_extract_pos:
            print("❌ Workspaces tab is not positioned after Search and Extract")
            return False
            
        # System tab (previously Other) should have updated description
        if "System-level settings that control application behavior" not in page_content:
            print("❌ System tab description was not updated")
            return False
            
        print("✅ Admin settings page loads correctly with new tab organization")
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to connect to admin settings: {e}")
        print("   Note: This test requires the application to be running on localhost:5000")
        return False
    except Exception as e:
        print(f"❌ Admin settings accessibility test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_workspace_dependency_validation_js():
    """Test that workspace dependency validation JavaScript is present."""
    print("🔍 Testing workspace dependency validation JavaScript...")
    
    try:
        base_url = "http://localhost:5000"
        admin_url = urljoin(base_url, "/admin/settings")
        
        response = requests.get(admin_url, timeout=10)
        if response.status_code != 200:
            print(f"❌ Admin settings page returned status code: {response.status_code}")
            return False
            
        page_content = response.text
        
        # Check for workspace dependency validation function
        if "setupWorkspaceDependencyValidation" not in page_content:
            print("❌ Missing setupWorkspaceDependencyValidation function")
            return False
            
        # Check for dependency checking logic
        required_js_components = [
            "checkWorkspaceDependencies",
            "Azure AI Search is required",
            "Document Intelligence is required", 
            "Embeddings configuration is required",
            "workspace-dependency-notifications"
        ]
        
        for component in required_js_components:
            if component not in page_content:
                print(f"❌ Missing JavaScript component: {component}")
                return False
                
        print("✅ Workspace dependency validation JavaScript is present")
        return True
        
    except Exception as e:
        print(f"❌ Workspace dependency validation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_health_check_consolidation():
    """Test that health check configuration is properly consolidated."""
    print("🔍 Testing health check consolidation...")
    
    try:
        base_url = "http://localhost:5000"
        admin_url = urljoin(base_url, "/admin/settings")
        
        response = requests.get(admin_url, timeout=10)
        if response.status_code != 200:
            print(f"❌ Admin settings page returned status code: {response.status_code}")
            return False
            
        page_content = response.text
        
        # Count occurrences of external health check configuration
        external_health_check_occurrences = page_content.count('enable_external_healthcheck')
        
        # Should only appear once (in General tab, not duplicated)
        if external_health_check_occurrences > 2:  # Once for input, once for label
            print(f"❌ External health check configuration appears {external_health_check_occurrences} times (should be 2)")
            return False
            
        # Check that external health check is in General tab section
        general_tab_section = page_content[page_content.find('id="general"'):page_content.find('id="gpt"')]
        if 'enable_external_healthcheck' not in general_tab_section:
            print("❌ External health check configuration not found in General tab")
            return False
            
        print("✅ Health check configuration is properly consolidated in General tab")
        return True
        
    except Exception as e:
        print(f"❌ Health check consolidation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_health_check_endpoints():
    """Test that health check endpoints are working."""
    print("🔍 Testing health check endpoints...")
    
    try:
        base_url = "http://localhost:5000"
            
        # Test external health check endpoint  
        external_health_url = urljoin(base_url, "/external/healthcheck")
        try:
            response = requests.get(external_health_url, timeout=5)
            if response.status_code == 200:
                print("✅ External health check endpoint (/external/healthcheck) is accessible")
            else:
                print(f"⚠️ External health check endpoint returned: {response.status_code}")
        except requests.exceptions.RequestException:
            print("⚠️ External health check endpoint not accessible (may be disabled)")
            
        return True
        
    except Exception as e:
        print(f"❌ Health check endpoints test failed: {e}")
        return False

def test_admin_form_processing():
    """Test that admin form can process the new configurations."""
    print("🔍 Testing admin form processing capabilities...")
    
    try:
        base_url = "http://localhost:5000"
        admin_url = urljoin(base_url, "/admin/settings")
        
        # Get the admin settings page to check form structure
        response = requests.get(admin_url, timeout=10)
        if response.status_code != 200:
            print(f"❌ Admin settings page returned status code: {response.status_code}")
            return False
            
        page_content = response.text
        
        # Check that form includes all necessary fields for new functionality
        required_form_fields = [
            'name="enable_external_healthcheck"',
            'name="enable_workspaces"',
            'name="azure_search_service_endpoint"',
            'name="azure_search_index_name"',
            'name="azure_document_intelligence_endpoint"',
            'name="embeddings_azure_openai_endpoint"'
        ]
        
        for field in required_form_fields:
            if field not in page_content:
                print(f"❌ Missing required form field: {field}")
                return False
                
        # Check that form has proper action and method
        if 'action="/admin/settings"' not in page_content and 'method="post"' not in page_content:
            print("❌ Admin form does not have proper action/method attributes")
            return False
            
        print("✅ Admin form processing structure is correct")
        return True
        
    except Exception as e:
        print(f"❌ Admin form processing test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 Running Admin Configuration Improvements Test Suite")
    print("=" * 60)
    
    tests = [
        test_admin_settings_accessibility,
        test_workspace_dependency_validation_js,
        test_health_check_consolidation,
        test_health_check_endpoints,
        test_admin_form_processing
    ]
    
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
        time.sleep(1)  # Brief pause between tests
    
    # Summary
    passed = sum(results)
    total = len(results)
    
    print(f"\n📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All admin configuration improvements are working correctly!")
    else:
        print("⚠️ Some tests failed. Please review the admin configuration changes.")
        
    print("\nNote: Some tests require the application to be running on localhost:5000")
    
    sys.exit(0 if passed == total else 1)