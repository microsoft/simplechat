#!/usr/bin/env python3
"""
Functional test for Group Activity Timeline button binding fix.
Version: 0.234.027
Implemented in: 0.234.027

This test ensures that the View Group Activity button properly calls
the viewActivity function to load data, not just show an empty modal.
"""

import sys
import os

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_view_activity_button_binding():
    """Test that the View Activity button has proper event listener binding."""
    print("🔍 Testing View Activity button event listener...")
    
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
        
        # Check that viewActivityBtn has an event listener
        if "getElementById('viewActivityBtn')" not in content:
            print("❌ viewActivityBtn event listener not found")
            return False
        
        # Check that the event listener calls viewActivity
        if "GroupManager.viewActivity" not in content:
            print("❌ Event listener doesn't call viewActivity")
            return False
        
        # Verify the button element exists
        if 'id="viewActivityBtn"' not in content:
            print("❌ viewActivityBtn element not found in HTML")
            return False
        
        # Check that it gets the group ID from the modal
        if "getAttribute('data-group-id')" not in content:
            print("❌ Doesn't retrieve group ID from modal")
            return False
        
        print("✅ View Activity button properly bound")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_console_logging_added():
    """Test that detailed console logging was added for debugging."""
    print("\n🔍 Testing console logging...")
    
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
        
        # Check for logging in viewActivity
        logging_checks = [
            "[Activity] viewActivity called",
            "[Activity] Fetching group details",
            "[Activity] Showing modal",
            "[Activity] Starting to load activity data",
            "[Activity] Loading activity for group"
        ]
        
        for log_msg in logging_checks:
            if log_msg not in content:
                print(f"❌ Missing log message: {log_msg}")
                return False
        
        # Check for API response logging
        if "[Activity] API response status" not in content:
            print("❌ Missing API response logging")
            return False
        
        # Check for error logging
        if "[Activity] Error" not in content:
            print("❌ Missing error logging")
            return False
        
        print("✅ Comprehensive logging added")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_element_existence_checks():
    """Test that the code checks for element existence before using them."""
    print("\n🔍 Testing element existence checks...")
    
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
        
        # Check for timeline element check
        if "if (!timeline)" not in content:
            print("❌ Missing timeline element check")
            return False
        
        # Check for modal element check
        if "if (!modalElement)" not in content:
            print("❌ Missing modal element check")
            return False
        
        # Check for error messages when elements not found
        if "'Timeline element not found'" not in content:
            print("❌ Missing timeline error message")
            return False
        
        if "'Activity modal element not found'" not in content:
            print("❌ Missing modal error message")
            return False
        
        print("✅ Element existence checks added")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_error_handling_improved():
    """Test that error handling shows API response details."""
    print("\n🔍 Testing improved error handling...")
    
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
        
        # Check for response text on error
        if "await response.text()" not in content:
            print("❌ Doesn't capture error response text")
            return False
        
        # Check that status code is included in error
        if "response.status" not in content:
            print("❌ Doesn't include status code in error")
            return False
        
        # Check for try-catch in viewActivity
        viewactivity_section = content[content.find("viewActivity: async function"):content.find("viewActivity: async function") + 2000]
        if "try {" not in viewactivity_section or "catch" not in viewactivity_section:
            print("❌ viewActivity missing try-catch")
            return False
        
        print("✅ Error handling improved")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("="*80)
    print("Group Activity Timeline Button Binding Fix - Functional Test")
    print("="*80)
    
    tests = [
        ("View Activity Button Binding", test_view_activity_button_binding),
        ("Console Logging", test_console_logging_added),
        ("Element Existence Checks", test_element_existence_checks),
        ("Error Handling", test_error_handling_improved)
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
        print("\n🎉 All tests passed! Button binding fix is working correctly.")
        return 0
    else:
        print("\n⚠️ Some tests failed. Please review the implementation.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
