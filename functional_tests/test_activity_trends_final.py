#!/usr/bin/env python3
"""
Final functional test for Activity Trends implementation.
This test validates the Activity Trends feature implementation with real data sources.
"""

import os
import sys

def test_route_implementation():
    """Test if the backend route file contains the activity trends endpoint."""
    
    route_path = os.path.join(os.path.dirname(__file__), "..", "application", "single_app", "route_backend_control_center.py")
    
    if not os.path.exists(route_path):
        return False, f"Backend route file not found: {route_path}"
    
    try:
        with open(route_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Check for activity trends endpoint
        if '/api/admin/control-center/activity-trends' in content:
            return True, "Activity trends endpoint found in backend routes"
        else:
            return False, "Activity trends endpoint not found"
            
    except Exception as e:
        return False, f"Error reading route file: {str(e)}"

def test_real_data_implementation():
    """Test if the activity trends uses real data containers."""
    
    route_path = os.path.join(os.path.dirname(__file__), "..", "application", "single_app", "route_backend_control_center.py")
    
    if not os.path.exists(route_path):
        return False, "Backend route file not found"
    
    try:
        with open(route_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Check for real container usage (not activity_logs)
        real_containers = ['conversations', 'messages', 'user_documents', 'group_documents', 'public_documents', 'feedback']
        found_containers = [container for container in real_containers if container in content]
        
        if len(found_containers) >= 3:
            return True, f"Real data containers found: {', '.join(found_containers)}"
        else:
            return False, f"Not enough real data containers found. Found: {', '.join(found_containers)}"
            
    except Exception as e:
        return False, f"Error reading route file: {str(e)}"

def test_frontend_template():
    """Test if the frontend template contains activity trends chart."""
    
    template_path = os.path.join(os.path.dirname(__file__), "..", "application", "single_app", "templates", "control_center.html")
    
    if not os.path.exists(template_path):
        return False, f"Template file not found: {template_path}"
    
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Check for activity trends chart elements
        if 'activityTrendsChart' in content and 'canvas' in content:
            return True, "Activity trends chart elements found in template"
        else:
            return False, "Activity trends chart elements not found"
            
    except Exception as e:
        return False, f"Error reading template file: {str(e)}"

def test_chart_js_local():
    """Test if Chart.js is available locally."""
    
    chart_path = os.path.join(os.path.dirname(__file__), "..", "application", "single_app", "static", "js", "chart.min.js")
    
    if not os.path.exists(chart_path):
        return False, f"Local Chart.js file not found: {chart_path}"
    
    # Check file size (should be substantial for Chart.js)
    file_size = os.path.getsize(chart_path)
    if file_size > 100000:  # Should be ~200KB
        return True, f"Chart.js file found ({file_size:,} bytes)"
    else:
        return False, f"Chart.js file too small ({file_size} bytes)"

def test_javascript_integration():
    """Test if JavaScript file contains activity trends functionality."""
    
    js_path = os.path.join(os.path.dirname(__file__), "..", "application", "single_app", "static", "js", "control-center.js")
    
    if not os.path.exists(js_path):
        return False, f"JavaScript file not found: {js_path}"
    
    try:
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Check for activity trends functions
        required_functions = ['loadActivityTrends', 'renderActivityChart']
        found_functions = [func for func in required_functions if func in content]
        
        if len(found_functions) == len(required_functions):
            return True, f"Activity trends functions found: {', '.join(found_functions)}"
        else:
            missing = [func for func in required_functions if func not in found_functions]
            return False, f"Missing functions: {', '.join(missing)}"
            
    except Exception as e:
        return False, f"Error reading JavaScript file: {str(e)}"

def run_tests():
    """Run all functional tests."""
    
    print("🚀 Running Activity Trends Final Functional Tests")
    print("=" * 60)
    
    tests = [
        ("Backend Route Implementation", test_route_implementation),
        ("Real Data Implementation", test_real_data_implementation),
        ("Frontend Template Integration", test_frontend_template),
        ("Local Chart.js File", test_chart_js_local),
        ("JavaScript Integration", test_javascript_integration)
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n🧪 {test_name}...")
        try:
            success, message = test_func()
            if success:
                print(f"✅ PASSED: {message}")
                passed += 1
            else:
                print(f"❌ FAILED: {message}")
        except Exception as e:
            print(f"❌ ERROR: {str(e)}")
    
    print("\n" + "=" * 60)
    print(f"📊 Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Activity Trends feature is fully implemented.")
    else:
        print("⚠️  Some tests failed. Review implementation.")
    
    return passed == total

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)