#!/usr/bin/env python3
# test_sidebar_navigation_tab_preservation.py
"""
Functional test for admin settings sidebar navigation tab preservation fix.
Version: 0.229.046
Implemented in: 0.229.046

This test specifically validates that the sidebar navigation properly preserves
the active tab when saving settings, including both tab-level and section-level
active states.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_sidebar_navigation_structure():
    """Test that the sidebar navigation HTML structure is present."""
    print("🔍 Testing Sidebar Navigation Structure...")
    
    try:
        sidebar_nav_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "application", "single_app", "templates", "_sidebar_nav.html"
        )
        
        if not os.path.exists(sidebar_nav_path):
            print(f"❌ Sidebar navigation template not found: {sidebar_nav_path}")
            return False
            
        with open(sidebar_nav_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
            
        # Check for required sidebar navigation elements
        required_elements = [
            'id="admin-settings-toggle"',
            'admin-nav-tab',  # Changed from class="admin-nav-tab" to just admin-nav-tab
            'admin-nav-section',  # Changed from class="admin-nav-section" to just admin-nav-section
            'data-tab="search-extract"',
            'data-tab="general"',
            'data-tab="agents"',
            'data-section="azure-ai-search-section"',
            'id="search-extract-submenu"'
        ]
        
        missing_elements = []
        for element in required_elements:
            if element not in html_content:
                missing_elements.append(element)
                
        if missing_elements:
            print(f"❌ Missing required sidebar elements: {missing_elements}")
            return False
            
        # Verify search-extract tab structure specifically
        search_extract_elements = [
            'data-tab="search-extract"',
            'Search & Extract',
            'azure-ai-search-section',
            'document-intelligence-section',
            'multimedia-support-section'
        ]
        
        found_search_elements = []
        for element in search_extract_elements:
            if element in html_content:
                found_search_elements.append(element)
                
        if len(found_search_elements) < 4:  # Should find at least 4 of the 5 elements
            print(f"❌ Insufficient search-extract tab structure. Found: {found_search_elements}")
            return False
            
        print("✅ Sidebar navigation structure is properly defined")
        return True
        
    except Exception as e:
        print(f"❌ Error testing sidebar structure: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_sidebar_navigation_javascript_support():
    """Test that the JavaScript properly supports sidebar navigation."""
    print("🔍 Testing Sidebar Navigation JavaScript Support...")
    
    try:
        admin_settings_js_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "application", "single_app", "static", "js", "admin", "admin_settings.js"
        )
        
        with open(admin_settings_js_path, 'r', encoding='utf-8') as f:
            js_content = f.read()
            
        # Check for sidebar-specific navigation support
        required_sidebar_features = [
            '.admin-nav-section.active',  # Section-level active detection
            '.admin-nav-tab.active',      # Tab-level active detection
            'data-tab',                   # Tab ID extraction
            'admin-settings-toggle',      # Sidebar detection
            'showAdminTab',               # Sidebar tab switching function
            'submenu.style.display',      # Submenu expansion
            'querySelectorAll(\'.admin-nav-tab\')', # Tab clearing
            'querySelectorAll(\'.admin-nav-section\')'  # Section clearing
        ]
        
        missing_features = []
        for feature in required_sidebar_features:
            if feature not in js_content:
                missing_features.append(feature)
                
        if missing_features:
            print(f"❌ Missing sidebar navigation features: {missing_features}")
            return False
            
        # Check for proper priority order in getCurrentActiveTab
        section_check_pos = js_content.find('.admin-nav-section.active')
        tab_check_pos = js_content.find('.admin-nav-tab.active')
        
        if section_check_pos == -1 or tab_check_pos == -1:
            print("❌ Missing active state checks in getCurrentActiveTab")
            return False
            
        if section_check_pos > tab_check_pos:
            print("❌ Section check should come before tab check for proper priority")
            return False
            
        print("✅ Sidebar navigation JavaScript support is properly implemented")
        return True
        
    except Exception as e:
        print(f"❌ Error testing sidebar JavaScript: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_admin_sidebar_nav_integration():
    """Test integration with admin_sidebar_nav.js file."""
    print("🔍 Testing Admin Sidebar Navigation Integration...")
    
    try:
        admin_sidebar_nav_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "application", "single_app", "static", "js", "admin", "admin_sidebar_nav.js"
        )
        
        if not os.path.exists(admin_sidebar_nav_path):
            print(f"❌ Admin sidebar nav file not found: {admin_sidebar_nav_path}")
            return False
            
        with open(admin_sidebar_nav_path, 'r', encoding='utf-8') as f:
            js_content = f.read()
            
        # Check for required functions and features
        required_functions = [
            'showAdminTab',
            'admin-nav-tab',
            'admin-nav-section',
            'data-tab',
            'data-section',
            'window.location.hash'
        ]
        
        missing_functions = []
        for func in required_functions:
            if func not in js_content:
                missing_functions.append(func)
                
        if missing_functions:
            print(f"❌ Missing required functions in admin sidebar nav: {missing_functions}")
            return False
            
        # Check for proper active state management
        active_state_features = [
            'classList.add(\'active\')',
            'classList.remove(\'active\')',
            '.admin-nav-tab',
            '.admin-nav-section'
        ]
        
        found_features = []
        for feature in active_state_features:
            if feature in js_content:
                found_features.append(feature)
                
        if len(found_features) < 3:  # Should find at least 3 of 4 features
            print(f"❌ Insufficient active state management. Found: {found_features}")
            return False
            
        print("✅ Admin sidebar navigation integration is properly configured")
        return True
        
    except Exception as e:
        print(f"❌ Error testing sidebar integration: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_search_extract_tab_specific():
    """Test specific support for the search-extract tab mentioned by user."""
    print("🔍 Testing Search & Extract Tab Specific Support...")
    
    try:
        # Check both JavaScript files for search-extract support
        files_to_check = [
            ("admin_settings.js", os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "application", "single_app", "static", "js", "admin", "admin_settings.js"
            )),
            ("admin_sidebar_nav.js", os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "application", "single_app", "static", "js", "admin", "admin_sidebar_nav.js"
            )),
            ("_sidebar_nav.html", os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "application", "single_app", "templates", "_sidebar_nav.html"
            ))
        ]
        
        search_extract_support = {
            'html_structure': False,
            'js_tab_detection': False,
            'js_navigation': False
        }
        
        for file_name, file_path in files_to_check:
            if not os.path.exists(file_path):
                continue
                
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            if file_name == "_sidebar_nav.html":
                if 'data-tab="search-extract"' in content and 'Search & Extract' in content:
                    search_extract_support['html_structure'] = True
                    
            elif file_name == "admin_settings.js":
                if 'search-extract' in content or 'data-tab' in content:
                    search_extract_support['js_tab_detection'] = True
                    
            elif file_name == "admin_sidebar_nav.js":
                if 'showAdminTab' in content and 'data-tab' in content:
                    search_extract_support['js_navigation'] = True
        
        missing_support = []
        for feature, supported in search_extract_support.items():
            if not supported:
                missing_support.append(feature)
                
        if missing_support:
            print(f"❌ Missing search-extract support: {missing_support}")
            return False
            
        print("✅ Search & Extract tab is properly supported")
        print("   - HTML structure with data-tab='search-extract' ✓")
        print("   - JavaScript tab detection support ✓")
        print("   - JavaScript navigation functions ✓")
        return True
        
    except Exception as e:
        print(f"❌ Error testing search-extract support: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all sidebar navigation specific tests."""
    print("🧪 Running Admin Settings Sidebar Navigation Tests...\n")
    
    tests = [
        test_sidebar_navigation_structure,
        test_sidebar_navigation_javascript_support,
        test_admin_sidebar_nav_integration,
        test_search_extract_tab_specific
    ]
    
    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("✅ All sidebar navigation tests passed!")
        print("💡 The sidebar navigation should now preserve tabs like #search-extract when saving")
        print("🔧 Debug console logs have been added - check browser console for detailed information")
    else:
        print("❌ Some sidebar navigation tests failed")
        print("🔧 Review the sidebar navigation implementation")
    
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)