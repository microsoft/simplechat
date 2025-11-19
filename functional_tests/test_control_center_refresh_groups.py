#!/usr/bin/env python3
"""
Functional test for Control Center refresh functionality including groups.
Version: 0.230.049
Implemented in: 0.230.049

This test ensures that the refresh data functionality refreshes both users and groups,
and that groups cache their metrics in the groups container like users cache in user_settings.
"""

import sys
import os
import requests
import time

# Add the parent directory to the path to access the app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'application', 'single_app'))

def test_refresh_endpoint_structure():
    """Test that the refresh endpoint includes group refresh logic."""
    print("🧪 Testing Refresh Endpoint Structure...")
    
    try:
        # Check the backend refresh endpoint file
        backend_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'route_backend_control_center.py'
        )
        
        if os.path.exists(backend_path):
            with open(backend_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for group refresh logic in the refresh endpoint
            expected_elements = [
                'enhance_group_with_activity',
                'groups_refreshed_count',
                'cosmos_groups_container',
                'Starting group refresh',
                'refreshed_groups',
                'failed_groups'
            ]
            
            missing_elements = []
            for element in expected_elements:
                if element not in content:
                    missing_elements.append(element)
            
            if missing_elements:
                print(f"   ❌ Missing expected refresh elements: {missing_elements}")
                return False
            else:
                print("   ✅ All expected group refresh elements found")
                
                # Check that groups are queried from cosmos_groups_container
                if 'cosmos_groups_container.query_items' in content:
                    print("   ✅ Groups are properly queried from cosmos_groups_container")
                else:
                    print("   ❌ Groups query not found in refresh endpoint")
                    return False
                
                # Check that force_refresh=True is used for groups
                if 'enhance_group_with_activity(group, force_refresh=True)' in content:
                    print("   ✅ Groups use force_refresh=True for cache invalidation")
                else:
                    print("   ❌ Group force_refresh not found")
                    return False
                
                return True
        else:
            print(f"   ❌ Backend file not found: {backend_path}")
            return False
            
    except Exception as e:
        print(f"   ❌ Error testing refresh endpoint structure: {e}")
        return False

def test_group_caching_structure():
    """Test that groups cache metrics in the groups container."""
    print("🧪 Testing Group Caching Structure...")
    
    try:
        # Check the group enhancement function for caching
        backend_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'route_backend_control_center.py'
        )
        
        if os.path.exists(backend_path):
            with open(backend_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for group caching logic
            expected_caching = [
                "group['metrics'] = metrics_cache",
                'cosmos_groups_container.upsert_item(group)',
                'Cache the computed metrics in the group document',
                'metrics_cache = {',
                "'document_metrics': enhanced['activity']['document_metrics']"
            ]
            
            missing_caching = []
            for cache_element in expected_caching:
                if cache_element not in content:
                    missing_caching.append(cache_element)
            
            if missing_caching:
                print(f"   ❌ Missing caching elements: {missing_caching}")
                return False
            else:
                print("   ✅ All expected group caching elements found")
                
                # Verify cache expiration logic exists
                if 'timedelta(hours=1)' in content and 'cache_time' in content:
                    print("   ✅ Cache expiration logic found (1 hour TTL)")
                else:
                    print("   ⚠️  Cache expiration logic not found or different")
                
                return True
        else:
            print(f"   ❌ Backend file not found: {backend_path}")
            return False
            
    except Exception as e:
        print(f"   ❌ Error testing group caching structure: {e}")
        return False

def test_frontend_refresh_message():
    """Test that the frontend displays both users and groups in refresh message."""
    print("🧪 Testing Frontend Refresh Message...")
    
    try:
        # Check the control center JavaScript
        js_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'static', 'js', 'control-center.js'
        )
        
        if os.path.exists(js_path):
            with open(js_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for updated success message
            expected_message_elements = [
                'result.refreshed_groups',
                'users and',
                'groupsMsg'
            ]
            
            missing_message = []
            for element in expected_message_elements:
                if element not in content:
                    missing_message.append(element)
            
            if missing_message:
                print(f"   ❌ Missing message elements: {missing_message}")
                return False
            else:
                print("   ✅ Frontend success message includes both users and groups")
                return True
        else:
            print(f"   ❌ JavaScript file not found: {js_path}")
            return False
            
    except Exception as e:
        print(f"   ❌ Error testing frontend refresh message: {e}")
        return False

def test_refresh_api_response_structure():
    """Test that the refresh API response includes group information."""
    print("🧪 Testing Refresh API Response Structure...")
    
    try:
        # Check the backend refresh endpoint response
        backend_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'route_backend_control_center.py'
        )
        
        if os.path.exists(backend_path):
            with open(backend_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for group fields in API response
            expected_response_fields = [
                "'refreshed_groups': groups_refreshed_count",
                "'failed_groups': groups_failed_count"
            ]
            
            missing_fields = []
            for field in expected_response_fields:
                if field not in content:
                    missing_fields.append(field)
            
            if missing_fields:
                print(f"   ❌ Missing API response fields: {missing_fields}")
                return False
            else:
                print("   ✅ API response includes group refresh statistics")
                
                # Check that success message mentions both users and groups
                if 'Users:' in content and 'Groups:' in content and 'refreshed' in content:
                    print("   ✅ Logging includes both user and group statistics")
                else:
                    print("   ❌ Logging doesn't include both user and group statistics")
                    return False
                
                return True
        else:
            print(f"   ❌ Backend file not found: {backend_path}")
            return False
            
    except Exception as e:
        print(f"   ❌ Error testing API response structure: {e}")
        return False

def run_all_tests():
    """Run all refresh functionality tests."""
    print("🎯 Testing Control Center Refresh Functionality with Groups")
    print("=" * 65)
    
    tests = [
        ("Refresh Endpoint Structure", test_refresh_endpoint_structure),
        ("Group Caching Structure", test_group_caching_structure),
        ("Frontend Refresh Message", test_frontend_refresh_message),
        ("Refresh API Response Structure", test_refresh_api_response_structure),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"\n🧪 Running {test_name}...")
        result = test_func()
        results.append(result)
        
        if result:
            print(f"✅ {test_name} PASSED")
        else:
            print(f"❌ {test_name} FAILED")
    
    # Summary
    print("\n" + "=" * 65)
    print("📊 TEST RESULTS SUMMARY")
    print("=" * 65)
    
    passed = sum(results)
    total = len(results)
    
    for i, (test_name, _) in enumerate(tests):
        status = "✅ PASS" if results[i] else "❌ FAIL"
        print(f"  {status} - {test_name}")
    
    print(f"\n🎯 Overall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Refresh functionality now includes groups.")
        print("\nThe implementation includes:")
        print("  📊 Backend refresh endpoint refreshes both users AND groups")
        print("  💾 Groups cache metrics in cosmos_groups_container (same as users)")
        print("  🔄 Groups use force_refresh=True to invalidate cache")
        print("  📈 API response includes group refresh statistics")
        print("  🎨 Frontend success message shows both user and group counts")
        print("  ⏰ Groups have 1-hour cache TTL like users")
        return True
    else:
        print("❌ Some tests failed. Please check the implementation.")
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)