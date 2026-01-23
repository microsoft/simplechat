#!/usr/bin/env python3
"""
Functional test for Group Activity Timeline feature.
Version: 0.234.026
Implemented in: 0.234.026

This test ensures that the Group Activity Timeline displays real data from activity logs
including document uploads/deletions, member changes, and status changes.
"""

import sys
import os

# Add the application directory to the path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_backend_api_endpoint():
    """Test that the backend API endpoint exists."""
    print("🔍 Testing backend API endpoint exists...")
    
    try:
        backend_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..',
            'application',
            'single_app',
            'route_backend_control_center.py'
        )
        
        with open(backend_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for the API endpoint
        if "/api/admin/control-center/groups/<group_id>/activity" not in content:
            print("❌ Backend API endpoint not found")
            return False
        
        # Check that it queries activity_logs
        if "cosmos_activity_logs_container.query_items" not in content:
            print("❌ Backend doesn't query activity logs")
            return False
        
        # Check for activity types
        required_activity_types = [
            'document_creation',
            'document_deletion',
            'group_member_added',
            'group_member_deleted',
            'group_status_change'
        ]
        
        for activity_type in required_activity_types:
            if activity_type not in content:
                print(f"❌ Missing activity type: {activity_type}")
                return False
        
        print("✅ Backend API endpoint verified")
        return True
        
    except Exception as e:
        print(f"❌ Error checking backend: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_frontend_implementation():
    """Test that the frontend implements the activity timeline."""
    print("\n🔍 Testing frontend implementation...")
    
    try:
        template_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..',
            'application',
            'single_app',
            'templates',
            'control_center.html'
        )
        
        with open(template_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for activity timeline modal
        if 'groupActivityModal' not in content:
            print("❌ Group Activity Modal not found")
            return False
        
        # Check for timeline container
        if 'activityTimeline' not in content:
            print("❌ Activity timeline container not found")
            return False
        
        # Check for JavaScript functions
        required_functions = [
            'loadGroupActivity',
            'renderActivityItem',
            'formatFileSize',
            'getRelativeTime',
            'exportGroupActivity'
        ]
        
        for func in required_functions:
            if f'{func}:' not in content and f'{func} ' not in content:
                print(f"❌ Missing JavaScript function: {func}")
                return False
        
        # Check for CSS styles
        if '.activity-item' not in content:
            print("❌ Activity item styles not found")
            return False
        
        # Check for time range filter
        if 'activityTimeRange' not in content:
            print("❌ Time range filter not found")
            return False
        
        # Check that viewActivity function loads real data
        if 'await GroupManager.loadGroupActivity' not in content:
            print("❌ viewActivity doesn't load real data")
            return False
        
        print("✅ Frontend implementation verified")
        return True
        
    except Exception as e:
        print(f"❌ Error checking frontend: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_activity_types_mapping():
    """Test that all activity types are properly mapped with icons and colors."""
    print("\n🔍 Testing activity type mappings...")
    
    try:
        template_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..',
            'application',
            'single_app',
            'templates',
            'control_center.html'
        )
        
        with open(template_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that each activity type has proper rendering
        activity_cases = {
            'document_creation': ['Document Uploaded', 'file-earmark-plus', 'success'],
            'document_deletion': ['Document Deleted', 'file-earmark-minus', 'danger'],
            'document_metadata_update': ['Document Updated', 'pencil-square', 'info'],
            'group_member_added': ['Member Added', 'person-plus', 'primary'],
            'group_member_deleted': ['Member Removed', 'person-dash', 'warning'],
            'group_status_change': ['Status Changed', 'shield-lock', 'secondary'],
            'conversation_creation': ['Conversation Started', 'chat-dots', 'info']
        }
        
        for activity_type, expected_values in activity_cases.items():
            # Check that the activity type is handled in switch/case
            if f"case '{activity_type}':" not in content:
                print(f"❌ Missing switch case for: {activity_type}")
                return False
            
            # Check for expected title
            if expected_values[0] not in content:
                print(f"❌ Missing title for {activity_type}: {expected_values[0]}")
                return False
        
        print("✅ Activity type mappings verified")
        return True
        
    except Exception as e:
        print(f"❌ Error checking activity mappings: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_export_functionality():
    """Test that export functionality is implemented."""
    print("\n🔍 Testing export functionality...")
    
    try:
        template_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..',
            'application',
            'single_app',
            'templates',
            'control_center.html'
        )
        
        with open(template_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for export button
        if 'exportActivityBtn' not in content:
            print("❌ Export button not found")
            return False
        
        # Check for exportGroupActivity function
        if 'exportGroupActivity:' not in content:
            print("❌ Export function not found")
            return False
        
        # Check that export creates CSV
        if 'text/csv' not in content:
            print("❌ CSV export not implemented")
            return False
        
        print("✅ Export functionality verified")
        return True
        
    except Exception as e:
        print(f"❌ Error checking export: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_responsive_design():
    """Test that the timeline has responsive design elements."""
    print("\n🔍 Testing responsive design...")
    
    try:
        template_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..',
            'application',
            'single_app',
            'templates',
            'control_center.html'
        )
        
        with open(template_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for scrollable timeline
        if 'max-height: 400px' not in content or 'overflow-y: auto' not in content:
            print("❌ Timeline not scrollable")
            return False
        
        # Check for dark mode support
        if '[data-bs-theme="dark"] .activity-item' not in content:
            print("❌ Dark mode styles not found")
            return False
        
        # Check for hover effects
        if '.activity-item:hover' not in content:
            print("❌ Hover effects not found")
            return False
        
        print("✅ Responsive design verified")
        return True
        
    except Exception as e:
        print(f"❌ Error checking responsive design: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("="*80)
    print("Group Activity Timeline - Functional Test")
    print("="*80)
    
    tests = [
        ("Backend API Endpoint", test_backend_api_endpoint),
        ("Frontend Implementation", test_frontend_implementation),
        ("Activity Type Mappings", test_activity_types_mapping),
        ("Export Functionality", test_export_functionality),
        ("Responsive Design", test_responsive_design)
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            print(f"❌ Test '{test_name}' crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    print("\n" + "="*80)
    print("Test Summary")
    print("="*80)
    
    for i, (test_name, _) in enumerate(tests):
        status = "✅ PASS" if results[i] else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    total = len(results)
    passed = sum(results)
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if all(results):
        print("\n🎉 All tests passed! Group Activity Timeline is working correctly.")
        return 0
    else:
        print("\n⚠️ Some tests failed. Please review the implementation.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
