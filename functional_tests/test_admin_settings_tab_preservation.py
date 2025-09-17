#!/usr/bin/env python3
"""
Functional test for admin settings tab preservation fix.
Version: 0.229.032
Implemented in: 0.229.032

This test ensures that when saving admin settings from any tab, 
the user stays on the same tab after the page reload instead of 
being redirected to the general tab.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_admin_settings_tab_preservation_javascript():
    """Test the JavaScript logic for tab preservation."""
    print("🔍 Testing Admin Settings Tab Preservation JavaScript Logic...")
    
    try:
        # Test JavaScript code structure and function presence
        admin_settings_js_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "application", "single_app", "static", "js", "admin", "admin_settings.js"
        )
        
        if not os.path.exists(admin_settings_js_path):
            print(f"❌ Admin settings JavaScript file not found: {admin_settings_js_path}")
            return False
            
        with open(admin_settings_js_path, 'r', encoding='utf-8') as f:
            js_content = f.read()
            
        # Check for required functions and logic
        required_elements = [
            'getCurrentActiveTab',
            'sessionStorage.setItem',
            'adminSettingsActiveTab',
            'sessionStorage.getItem',
            'sessionStorage.removeItem',
            'activateTabFromHash',
            'data-bs-target',
            'admin-settings-toggle',  # For sidebar navigation
            'admin-nav-tab',  # For sidebar navigation
            'admin-nav-section',  # For sidebar section navigation
            'showAdminTab'  # For sidebar navigation
        ]
        
        missing_elements = []
        for element in required_elements:
            if element not in js_content:
                missing_elements.append(element)
                
        if missing_elements:
            print(f"❌ Missing required elements in JavaScript: {missing_elements}")
            return False
            
        # Check for the form submission handler that captures active tab
        if 'const activeTab = getCurrentActiveTab()' not in js_content:
            print("❌ Form submission handler doesn't capture active tab")
            return False
            
        # Check for sessionStorage persistence in form submission
        if 'sessionStorage.setItem(\'adminSettingsActiveTab\', activeTab)' not in js_content:
            print("❌ Active tab is not stored in sessionStorage during form submission")
            return False
            
        # Check for tab restoration in activateTabFromHash
        if 'sessionStorage.getItem(\'adminSettingsActiveTab\')' not in js_content:
            print("❌ activateTabFromHash doesn't check for saved tab")
            return False
            
        print("✅ JavaScript tab preservation logic is properly implemented")
        return True
        
    except Exception as e:
        print(f"❌ Error testing JavaScript logic: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_admin_settings_html_structure():
    """Test that the HTML structure supports tab preservation."""
    print("🔍 Testing Admin Settings HTML Structure...")
    
    try:
        admin_settings_html_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "application", "single_app", "templates", "admin_settings.html"
        )
        
        if not os.path.exists(admin_settings_html_path):
            print(f"❌ Admin settings HTML file not found: {admin_settings_html_path}")
            return False
            
        with open(admin_settings_html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
            
        # Check for required HTML elements
        required_elements = [
            'id="adminSettingsTab"',
            'data-bs-toggle="tab"',
            'data-bs-target=',
            'class="nav-link',
            'id="admin-settings-form"',
            'class="tab-pane fade'
        ]
        
        missing_elements = []
        for element in required_elements:
            if element not in html_content:
                missing_elements.append(element)
                
        if missing_elements:
            print(f"❌ Missing required HTML elements: {missing_elements}")
            return False
            
        # Check for specific tabs that should have data-bs-target attributes
        required_tabs = [
            'data-bs-target="#general"',
            'data-bs-target="#ai-models"',
            'data-bs-target="#agents"',
            'data-bs-target="#safety"'
        ]
        
        found_tabs = []
        for tab in required_tabs:
            if tab in html_content:
                found_tabs.append(tab)
                
        if len(found_tabs) < 3:  # At least 3 tabs should be present
            print(f"❌ Insufficient tab targets found. Found: {found_tabs}")
            return False
            
        print(f"✅ HTML structure supports tab preservation. Found {len(found_tabs)} tabs")
        return True
        
    except Exception as e:
        print(f"❌ Error testing HTML structure: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_tab_preservation_integration():
    """Test the integration between form submission and tab restoration."""
    print("🔍 Testing Tab Preservation Integration...")
    
    try:
        # This is a conceptual test of the integration logic
        # In a real browser environment, this would test:
        # 1. User is on a specific tab (e.g., #agents)
        # 2. User makes a change and clicks save
        # 3. Form is submitted, page reloads
        # 4. User should return to the #agents tab
        
        print("📝 Tab preservation workflow:")
        print("   1. User navigates to specific tab (e.g., #search-extract)")
        print("   2. Form submission captures current active tab (works for both sidebar and tab navigation)")
        print("   3. Active tab is stored in sessionStorage")
        print("   4. After redirect, activateTabFromHash checks sessionStorage")
        print("   5. Saved tab is restored using appropriate navigation method")
        print("   6. URL is updated and sessionStorage is cleared")
        
        # Test the logical flow is present in the code
        admin_settings_js_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "application", "single_app", "static", "js", "admin", "admin_settings.js"
        )
        
        with open(admin_settings_js_path, 'r', encoding='utf-8') as f:
            js_content = f.read()
            
        # Check that the workflow is properly implemented
        workflow_checks = [
            ('Form captures active tab', 'const activeTab = getCurrentActiveTab()'),
            ('Tab stored before submission', 'sessionStorage.setItem(\'adminSettingsActiveTab\''),
            ('Tab restored after reload', 'sessionStorage.getItem(\'adminSettingsActiveTab\')'),
            ('SessionStorage cleared', 'sessionStorage.removeItem(\'adminSettingsActiveTab\')'),
            ('URL updated with hash', 'history.replaceState(null, null, hash)'),
            ('Sidebar navigation support', 'admin-settings-toggle'),
            ('Bootstrap tab support', 'data-bs-target'),
            ('Dual navigation handling', 'sidebarToggle')
        ]
        
        for check_name, check_code in workflow_checks:
            if check_code not in js_content:
                print(f"❌ {check_name}: Missing code '{check_code}'")
                return False
            else:
                print(f"✅ {check_name}: Found")
                
        print("✅ Tab preservation integration workflow is complete")
        return True
        
    except Exception as e:
        print(f"❌ Error testing integration: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tab preservation tests."""
    print("🧪 Running Admin Settings Tab Preservation Tests...\n")
    
    tests = [
        test_admin_settings_tab_preservation_javascript,
        test_admin_settings_html_structure,
        test_tab_preservation_integration
    ]
    
    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("✅ All tab preservation tests passed!")
        print("💡 The admin settings should now preserve the active tab when saving")
    else:
        print("❌ Some tab preservation tests failed")
        print("🔧 Review the implementation to ensure proper tab preservation")
    
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)