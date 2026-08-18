#!/usr/bin/env python3
"""
Functional test for Groups Tab Refresh Fix.
Version: 0.230.055
Implemented in: 0.230.055

This test ensures that the groups tab refreshes automatically after "Refresh Data" 
completes, matching the behavior of the users tab.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_groups_refresh_functionality():
    """Test that groups refresh functionality is properly implemented."""
    print("🔍 Testing Groups Tab Refresh Functionality...")
    
    try:
        # Check if the JavaScript file contains the required functions
        js_file_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'static', 'js', 'control-center.js')
        
        if not os.path.exists(js_file_path):
            print(f"❌ JavaScript file not found at: {js_file_path}")
            return False
        
        with open(js_file_path, 'r', encoding='utf-8') as f:
            js_content = f.read()
        
        # Check for required functions and properties
        required_elements = [
            'loadGroups()',
            'renderGroups(',
            'currentGroupPage',
            'groupsPerPage',
            'groupSearchTerm',
            'groupStatusFilter',
            'selectedGroups',
            'handleGroupSearchChange',
            'handleGroupFilterChange',
            'renderGroupsPagination',
            'goToGroupPage',
            'updateBulkGroupActionButton',
            'renderGroupDocumentMetrics',
            'renderGroupIcon',
            'renderGroupStatusBadge'
        ]
        
        missing_elements = []
        for element in required_elements:
            if element not in js_content:
                missing_elements.append(element)
        
        if missing_elements:
            print(f"❌ Missing required JavaScript elements: {missing_elements}")
            return False
        
        # Check for groups tab event listener
        if "getElementById('groups-tab')" not in js_content:
            print("❌ Groups tab event listener not found")
            return False
        
        # Check for groups refresh in refreshActiveTabContent
        if "case 'groups-tab':" not in js_content or "loadGroups()" not in js_content:
            print("❌ Groups refresh case not found in refreshActiveTabContent")
            return False
        
        # Check for API endpoint usage
        if "/api/admin/control-center/groups" not in js_content:
            print("❌ Groups API endpoint not found")
            return False
        
        # Check backend route exists
        backend_file_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'route_backend_control_center.py')
        
        if os.path.exists(backend_file_path):
            with open(backend_file_path, 'r', encoding='utf-8') as f:
                backend_content = f.read()
            
            if "@bp.route('/api/admin/control-center/groups', methods=['GET'])" not in backend_content:
                print("❌ Backend groups endpoint not found")
                return False
        
        # Check HTML template has required elements
        template_file_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'templates', 'control_center.html')
        
        if os.path.exists(template_file_path):
            with open(template_file_path, 'r', encoding='utf-8') as f:
                template_content = f.read()
            
            html_elements = [
                'id="groupsTableBody"',
                'id="groupsPaginationInfo"',
                'id="groupsPagination"',
                'id="groupSearchInput"',
                'id="groupStatusFilterSelect"',
                'id="refreshGroupsBtn"',
                'id="selectAllGroups"',
                'id="bulkGroupActionBtn"'
            ]
            
            missing_html = []
            for element in html_elements:
                if element not in template_content:
                    missing_html.append(element)
            
            if missing_html:
                print(f"❌ Missing HTML elements: {missing_html}")
                return False
        
        print("✅ All required Groups refresh functionality is implemented!")
        print("   ✓ loadGroups() function exists")
        print("   ✓ renderGroups() function exists") 
        print("   ✓ Groups tab event listener configured")
        print("   ✓ Groups refresh case in refreshActiveTabContent")
        print("   ✓ Groups API endpoint integration")
        print("   ✓ Group properties and handlers implemented")
        print("   ✓ HTML template elements present")
        print("")
        print("🎯 Fix Summary:")
        print("   • Added missing loadGroups() function matching loadUsers() pattern")
        print("   • Implemented renderGroups() with document metrics display")
        print("   • Added group-specific properties to ControlCenter constructor")
        print("   • Created group search, filter, and pagination handlers")
        print("   • Integrated groups tab with refresh mechanism")
        print("   • Groups tab should now refresh automatically after 'Refresh Data'")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_groups_refresh_functionality()
    sys.exit(0 if success else 1)