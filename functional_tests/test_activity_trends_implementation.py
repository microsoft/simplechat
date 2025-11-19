#!/usr/bin/env python3
"""
Functional test for Activity Trends implementation in Control Center.
Version: 0.230.003
Implemented in: 0.230.003

This test ensures that the Activity Trends functionality works correctly in the Control Center,
including API endpoint functionality, chart data generation, and frontend integration.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import requests
import json
from datetime import datetime, timedelta

def test_activity_trends_api():
    """Test the activity trends API endpoint."""
    print("🔍 Testing Activity Trends API endpoint...")
    
    try:
        # Test the API endpoint (assuming local development server)
        base_url = "http://localhost:5000"  # Adjust as needed for your setup
        
        # Try to get activity trends data
        response = requests.get(f"{base_url}/api/admin/control-center/activity-trends?days=30")
        
        if response.status_code == 401:
            print("⚠️  Authentication required - cannot test API directly")
            print("✅ API endpoint exists and requires proper authentication")
            return True
        elif response.status_code == 200:
            data = response.json()
            
            # Validate response structure
            required_keys = ['activity_trends', 'date_range']
            for key in required_keys:
                if key not in data:
                    print(f"❌ Missing key '{key}' in API response")
                    return False
                    
            # Validate activity trends data structure
            trends = data['activity_trends']
            if not isinstance(trends, list):
                print("❌ Activity trends should be a list")
                return False
                
            if len(trends) > 0:
                sample_day = trends[0]
                required_day_keys = ['date', 'chats', 'uploads', 'logins', 'document_actions', 'total']
                for key in required_day_keys:
                    if key not in sample_day:
                        print(f"❌ Missing key '{key}' in daily activity data")
                        return False
                        
            print("✅ API response structure validated")
            print(f"✅ Received {len(trends)} days of activity data")
            return True
        else:
            print(f"❌ Unexpected status code: {response.status_code}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("⚠️  Could not connect to server - testing route definition instead")
        return test_route_definition()
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_route_definition():
    """Test that the route is properly defined in the backend."""
    print("🔍 Testing Activity Trends route definition...")
    
    try:
        # Check if the route is defined in the backend file
        backend_file = "../application/single_app/route_backend_control_center.py"
        if os.path.exists(backend_file):
            with open(backend_file, 'r') as f:
                content = f.read()
                
            # Check for activity trends API endpoint
            if "/api/admin/control-center/activity-trends" in content:
                print("✅ Activity trends API endpoint found in backend routes")
            else:
                print("❌ Activity trends API endpoint not found in backend routes")
                return False
                
            # Check for required functions
            required_functions = [
                "api_get_activity_trends",
                "get_activity_trends_data", 
                "generate_sample_activity_data"
            ]
            
            for func in required_functions:
                if func in content:
                    print(f"✅ Function '{func}' found in backend")
                else:
                    print(f"❌ Function '{func}' not found in backend")
                    return False
                    
            return True
        else:
            print(f"❌ Backend route file not found: {backend_file}")
            return False
            
    except Exception as e:
        print(f"❌ Route definition test failed: {e}")
        return False

def test_frontend_integration():
    """Test that the frontend template includes the activity trends chart."""
    print("🔍 Testing frontend Activity Trends integration...")
    
    try:
        # Check the control center HTML template
        template_file = "../application/single_app/templates/control_center.html"
        if os.path.exists(template_file):
            with open(template_file, 'r') as f:
                content = f.read()
                
            # Check for activity trends chart canvas and container
            if "activityTrendsChart" in content and "<canvas" in content:
                print("✅ Activity trends chart canvas element found in template")
            else:
                print("❌ Activity trends chart canvas element not found in template")
                return False
                
            if "activityTrendsChartContainer" in content:
                print("✅ Activity trends chart container found in template")
            else:
                print("❌ Activity trends chart container not found in template")
                return False
                
            # Check for Chart.js inclusion (now local file)
            if "chart.min.js" in content:
                print("✅ Chart.js library (local file) included in template")
            else:
                print("❌ Chart.js library (local file) not found in template")
                return False
                
            # Check for trend period buttons
            trend_buttons = ["trend-7days", "trend-30days", "trend-90days"]
            for button_id in trend_buttons:
                if button_id in content:
                    print(f"✅ Trend button '{button_id}' found in template")
                else:
                    print(f"❌ Trend button '{button_id}' not found in template")
                    return False
                    
            return True
        else:
            print(f"❌ Template file not found: {template_file}")
            return False
            
    except Exception as e:
        print(f"❌ Frontend integration test failed: {e}")
        return False

def test_chartjs_local_file():
    """Test that the local Chart.js file exists and is properly configured."""
    print("🔍 Testing local Chart.js file...")
    
    try:
        # Check if Chart.js file exists locally
        chartjs_file = "../application/single_app/static/js/chart.min.js"
        if os.path.exists(chartjs_file):
            # Check file size (should be substantial for Chart.js)
            file_size = os.path.getsize(chartjs_file)
            if file_size > 100000:  # Should be > 100KB for minified Chart.js
                print(f"✅ Local Chart.js file exists and has proper size ({file_size} bytes)")
            else:
                print(f"❌ Local Chart.js file too small ({file_size} bytes)")
                return False
                
            # Check file content
            with open(chartjs_file, 'r') as f:
                content = f.read(200)  # Read first 200 chars
                if "chart" in content.lower() or "Chart" in content:
                    print("✅ Chart.js file contains expected content")
                else:
                    print("❌ Chart.js file content verification failed")
                    return False
                    
            return True
        else:
            print(f"❌ Local Chart.js file not found: {chartjs_file}")
            return False
            
    except Exception as e:
        print(f"❌ Chart.js local file test failed: {e}")
        return False

def test_javascript_functionality():
    """Test that the JavaScript includes activity trends functionality."""
    print("🔍 Testing JavaScript Activity Trends functionality...")
    
    try:
        # Check the control center JavaScript file
        js_file = "../application/single_app/static/js/control-center.js"
        if os.path.exists(js_file):
            with open(js_file, 'r') as f:
                content = f.read()
                
            # Check for activity trends methods
            required_methods = [
                "loadActivityTrends",
                "renderActivityChart",
                "changeTrendPeriod",
                "showActivityTrendsError"
            ]
            
            for method in required_methods:
                if method in content:
                    print(f"✅ JavaScript method '{method}' found")
                else:
                    print(f"❌ JavaScript method '{method}' not found")
                    return False
                    
            # Check for Chart.js usage
            if "new Chart(" in content:
                print("✅ Chart.js instantiation found in JavaScript")
            else:
                print("❌ Chart.js instantiation not found in JavaScript")
                return False
                
            # Check for activity trends properties
            if "activityChart" in content and "currentTrendDays" in content:
                print("✅ Activity trends properties found in ControlCenter class")
            else:
                print("❌ Activity trends properties not found in ControlCenter class")
                return False
                
            return True
        else:
            print(f"❌ JavaScript file not found: {js_file}")
            return False
            
    except Exception as e:
        print(f"❌ JavaScript functionality test failed: {e}")
        return False

def test_config_version_update():
    """Test that the config version was properly updated."""
    print("🔍 Testing config version update...")
    
    try:
        config_file = "../application/single_app/config.py"
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                content = f.read()
                
            if 'VERSION = "0.230.003"' in content:
                print("✅ Config version properly updated to 0.230.003")
                return True
            else:
                print("❌ Config version not updated or incorrect")
                return False
        else:
            print(f"❌ Config file not found: {config_file}")
            return False
            
    except Exception as e:
        print(f"❌ Config version test failed: {e}")
        return False

def test_real_data_containers():
    """Test that the real data containers are properly configured."""
    print("🔍 Testing real data containers configuration...")
    
    try:
        config_file = "../application/single_app/config.py"
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                content = f.read()
                
            # Check for required containers that provide real activity data
            required_containers = [
                "cosmos_conversations_container",
                "cosmos_messages_container", 
                "cosmos_user_documents_container",
                "cosmos_group_documents_container",
                "cosmos_public_documents_container",
                "cosmos_feedback_container",
                "cosmos_safety_container",
                "cosmos_user_settings_container"
            ]
            
            missing_containers = []
            for container in required_containers:
                if container in content:
                    print(f"✅ {container} found")
                else:
                    print(f"❌ {container} not found")
                    missing_containers.append(container)
            
            if missing_containers:
                print(f"❌ Missing containers: {missing_containers}")
                return False
                
            print("✅ All required containers for real activity data are configured")
            return True
        else:
            print(f"❌ Config file not found: {config_file}")
            return False
            
    except Exception as e:
        print(f"❌ Real data containers test failed: {e}")
        return False

def run_all_tests():
    """Run all activity trends tests."""
    print("🚀 Starting Activity Trends Implementation Tests")
    print("=" * 60)
    
    tests = [
        test_config_version_update,
        test_real_data_containers,
        test_route_definition,
        test_frontend_integration,
        test_chartjs_local_file,
        test_javascript_functionality,
        test_activity_trends_api
    ]
    
    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        result = test()
        results.append(result)
        if result:
            print("✅ PASSED")
        else:
            print("❌ FAILED")
    
    print("\n" + "=" * 60)
    print("📊 Test Results Summary:")
    passed = sum(results)
    total = len(results)
    
    for i, (test, result) in enumerate(zip(tests, results)):
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {i+1}. {test.__name__}: {status}")
    
    print(f"\n🎯 Overall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All Activity Trends implementation tests PASSED!")
        print("The Activity Trends feature has been successfully implemented.")
    else:
        print("⚠️  Some tests failed. Please review the implementation.")
        
    return passed == total

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)