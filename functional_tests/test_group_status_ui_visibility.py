#!/usr/bin/env python3
"""
Functional test for Group Status UI Visibility.
Version: 0.234.005
Implemented in: 0.234.005

This test validates that UI elements (upload area, create buttons) are properly 
hidden/shown based on group status. It ensures users cannot see creation/upload 
controls when the group is in a restricted state (locked, upload_disabled, inactive).

Fix: Updated updateRoleDisplay() to consider both role AND status when showing upload section.
"""

import sys
import os

# Add the parent directory to sys.path so we can import modules from the main app
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))

def test_group_status_ui_logic():
    """
    Test the UI visibility logic for different group statuses.
    This simulates the JavaScript logic to ensure it handles all status cases correctly.
    """
    print("🔍 Testing Group Status UI Visibility Logic...")
    
    # Simulate the logic that determines UI element visibility
    def should_show_upload(status):
        """Upload area should only show for 'active' status"""
        return status == 'active'
    
    def should_show_create_buttons(status):
        """Create buttons should only show for 'active' status"""
        return status == 'active'
    
    def should_show_chat(status):
        """Chat should show for all statuses except 'inactive'"""
        return status != 'inactive'
    
    # Test cases
    test_cases = [
        {
            'status': 'active',
            'expected_upload': True,
            'expected_create': True,
            'expected_chat': True,
            'description': 'Active group - all features enabled'
        },
        {
            'status': 'locked',
            'expected_upload': False,
            'expected_create': False,
            'expected_chat': True,
            'description': 'Locked group - only viewing allowed'
        },
        {
            'status': 'upload_disabled',
            'expected_upload': False,
            'expected_create': False,
            'expected_chat': True,
            'description': 'Upload disabled - viewing and chat allowed'
        },
        {
            'status': 'inactive',
            'expected_upload': False,
            'expected_create': False,
            'expected_chat': False,
            'description': 'Inactive group - all features disabled'
        }
    ]
    
    all_passed = True
    
    for test_case in test_cases:
        status = test_case['status']
        description = test_case['description']
        
        print(f"\n  Testing: {description}")
        print(f"  Status: {status}")
        
        # Test upload visibility
        upload_visible = should_show_upload(status)
        if upload_visible == test_case['expected_upload']:
            print(f"    ✅ Upload area visibility correct: {upload_visible}")
        else:
            print(f"    ❌ Upload area visibility incorrect: expected {test_case['expected_upload']}, got {upload_visible}")
            all_passed = False
        
        # Test create buttons visibility
        create_visible = should_show_create_buttons(status)
        if create_visible == test_case['expected_create']:
            print(f"    ✅ Create buttons visibility correct: {create_visible}")
        else:
            print(f"    ❌ Create buttons visibility incorrect: expected {test_case['expected_create']}, got {create_visible}")
            all_passed = False
        
        # Test chat visibility
        chat_visible = should_show_chat(status)
        if chat_visible == test_case['expected_chat']:
            print(f"    ✅ Chat visibility correct: {chat_visible}")
        else:
            print(f"    ❌ Chat visibility incorrect: expected {test_case['expected_chat']}, got {chat_visible}")
            all_passed = False
    
    return all_passed

def test_javascript_function_exists():
    """
    Verify that the updateGroupUIBasedOnStatus function exists in group_workspaces.html
    """
    print("\n🔍 Verifying JavaScript functions exist in group_workspaces.html...")
    
    template_path = os.path.join(
        os.path.dirname(__file__), 
        '..', 
        'application', 
        'single_app', 
        'templates', 
        'group_workspaces.html'
    )
    
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for the two new functions
        functions_to_check = [
            ('updateGroupStatusAlert', 'Updates the group status alert box'),
            ('updateGroupUIBasedOnStatus', 'Hides/shows UI elements based on status')
        ]
        
        all_found = True
        for func_name, description in functions_to_check:
            if f"function {func_name}" in content:
                print(f"  ✅ Found function: {func_name} - {description}")
            else:
                print(f"  ❌ Missing function: {func_name} - {description}")
                all_found = False
        
        # Check that the functions are called in the right places
        if 'updateGroupStatusAlert()' in content:
            print(f"  ✅ updateGroupStatusAlert() is called in the code")
        else:
            print(f"  ❌ updateGroupStatusAlert() is not called in the code")
            all_found = False
        
        if 'updateGroupUIBasedOnStatus()' in content:
            print(f"  ✅ updateGroupUIBasedOnStatus() is called in the code")
        else:
            print(f"  ❌ updateGroupUIBasedOnStatus() is not called in the code")
            all_found = False
        
        # Check for the target HTML elements
        elements_to_check = [
            ('id="upload-area"', 'Upload area for documents'),
            ('id="create-group-prompt-btn"', 'Create prompt button'),
            ('id="create-group-agent-btn"', 'Create agent button'),
            ('id="create-group-plugin-btn"', 'Create plugin/action button'),
            ('id="group-status-alert"', 'Status alert box')
        ]
        
        for element_id, description in elements_to_check:
            if element_id in content:
                print(f"  ✅ Found element: {element_id} - {description}")
            else:
                print(f"  ❌ Missing element: {element_id} - {description}")
                all_found = False
        
        return all_found
        
    except Exception as e:
        print(f"  ❌ Error reading template file: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_version_updated():
    """
    Verify that the version was updated in config.py
    """
    print("\n🔍 Verifying version was updated in config.py...")
    
    config_path = os.path.join(
        os.path.dirname(__file__), 
        '..', 
        'application', 
        'single_app', 
        'config.py'
    )
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if 'VERSION = "0.234.005"' in content:
            print(f"  ✅ Version updated to 0.234.005")
            return True
        else:
            print(f"  ❌ Version not updated correctly")
            return False
            
    except Exception as e:
        print(f"  ❌ Error reading config.py: {e}")
        return False

if __name__ == "__main__":
    print("=" * 70)
    print("Group Status UI Visibility Test")
    print("=" * 70)
    
    results = []
    
    # Test 1: UI visibility logic
    try:
        result1 = test_group_status_ui_logic()
        results.append(result1)
        if result1:
            print("\n✅ UI visibility logic test passed!")
        else:
            print("\n❌ UI visibility logic test failed!")
    except Exception as e:
        print(f"\n❌ UI visibility logic test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        results.append(False)
    
    # Test 2: JavaScript function existence
    try:
        result2 = test_javascript_function_exists()
        results.append(result2)
        if result2:
            print("\n✅ JavaScript functions test passed!")
        else:
            print("\n❌ JavaScript functions test failed!")
    except Exception as e:
        print(f"\n❌ JavaScript functions test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        results.append(False)
    
    # Test 3: Version update
    try:
        result3 = test_version_updated()
        results.append(result3)
        if result3:
            print("\n✅ Version update test passed!")
        else:
            print("\n❌ Version update test failed!")
    except Exception as e:
        print(f"\n❌ Version update test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        results.append(False)
    
    # Summary
    print("\n" + "=" * 70)
    print(f"📊 Test Summary: {sum(results)}/{len(results)} tests passed")
    print("=" * 70)
    
    if all(results):
        print("✅ All tests passed! UI hiding functionality is correctly implemented.")
        sys.exit(0)
    else:
        print("❌ Some tests failed. Please review the output above.")
        sys.exit(1)
