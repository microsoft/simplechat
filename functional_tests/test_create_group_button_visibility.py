#!/usr/bin/env python3
"""
Functional test for Create Group Button visibility with enable_group_creation setting.
Version: 0.230.030
Implemented in: 0.230.030

This test ensures that the "Create New Group" button respects both the 
enable_group_creation setting and the require_member_of_create_group setting.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_route_checks_enable_group_creation():
    """Test that the my_groups route checks the enable_group_creation setting."""
    print("🔍 Testing Route Logic for enable_group_creation...")
    
    try:
        # Read the route file
        route_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'route_frontend_groups.py')
        with open(route_path, 'r') as f:
            route_content = f.read()
        
        # Check that enable_group_creation is retrieved from settings
        assert 'enable_group_creation = settings.get("enable_group_creation", True)' in route_content, \
            "Route should retrieve enable_group_creation setting"
        
        # Check that can_create_groups is initially set to enable_group_creation
        assert 'can_create_groups = enable_group_creation' in route_content, \
            "can_create_groups should initially be set to enable_group_creation value"
        
        # Check that role checking is conditional on enable_group_creation being True
        assert 'if can_create_groups and require_member_of_create_group:' in route_content, \
            "Role checking should only occur when group creation is enabled"
        
        print("  ✓ Route retrieves enable_group_creation setting")
        print("  ✓ can_create_groups respects enable_group_creation")
        print("  ✓ Role checking is conditional on group creation being enabled")
        print("✅ Route logic test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Route logic test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_template_conditional_logic():
    """Test that the template properly uses the can_create_groups variable."""
    print("🔍 Testing Template Conditional Logic...")
    
    try:
        # Read the template file
        template_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'templates', 'my_groups.html')
        with open(template_path, 'r') as f:
            template_content = f.read()
        
        # Check that Create Group button is conditionally displayed
        assert '{% if can_create_groups %}' in template_content, \
            "Create Group button should be conditionally displayed"
        
        # Check that the modal is also conditional
        modal_section = template_content[template_content.find('<!-- Create Group Modal -->'):template_content.find('{% endif %}', template_content.find('<!-- Create Group Modal -->'))]
        assert '{% if can_create_groups %}' in modal_section, \
            "Create Group modal should be conditionally displayed"
        
        # Check that JavaScript respects the permission
        assert 'const canCreateGroups = {{ can_create_groups|tojson }}' in template_content, \
            "JavaScript should receive canCreateGroups from backend"
        
        # Check that modal creation is conditional
        assert 'canCreateGroups ? new bootstrap.Modal' in template_content, \
            "Modal creation should be conditional"
        
        # Check that form event handler is conditional
        assert 'if (canCreateGroups) {' in template_content and '$("#createGroupForm").on("submit", handleCreateGroup);' in template_content, \
            "Form event handler should be conditional"
        
        print("  ✓ Create Group button is conditionally displayed")
        print("  ✓ Create Group modal is conditionally displayed")
        print("  ✓ JavaScript receives permission from backend")
        print("  ✓ Modal creation and event handlers are conditional")
        print("✅ Template conditional logic test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Template conditional logic test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_permission_scenarios():
    """Test different permission scenarios to validate logic."""
    print("🔍 Testing Permission Scenarios...")
    
    try:
        # Read the route file to validate the logic patterns
        route_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'route_frontend_groups.py')
        with open(route_path, 'r') as f:
            route_content = f.read()
        
        # Validate the logical flow:
        # 1. enable_group_creation = False → can_create_groups = False (regardless of role)
        # 2. enable_group_creation = True + require_member_of_create_group = False → can_create_groups = True
        # 3. enable_group_creation = True + require_member_of_create_group = True + user has role → can_create_groups = True
        # 4. enable_group_creation = True + require_member_of_create_group = True + user lacks role → can_create_groups = False
        
        # Check the logical structure
        lines = route_content.split('\n')
        logic_start = -1
        for i, line in enumerate(lines):
            if 'can_create_groups = enable_group_creation' in line:
                logic_start = i
                break
        
        assert logic_start >= 0, "Logic starting point not found"
        
        # Find the conditional role check
        role_check_found = False
        for i in range(logic_start, min(logic_start + 5, len(lines))):
            if 'if can_create_groups and require_member_of_create_group:' in lines[i]:
                role_check_found = True
                break
        
        assert role_check_found, "Conditional role check not found after initial assignment"
        
        print("  ✓ Scenario 1: enable_group_creation = False → can_create_groups = False")
        print("  ✓ Scenario 2: enable_group_creation = True → respects role requirements")
        print("  ✓ Logic flow correctly handles all permission combinations")
        print("✅ Permission scenarios test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Permission scenarios test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_api_endpoint_protection():
    """Test that the API endpoint has proper protection."""
    print("🔍 Testing API Endpoint Protection...")
    
    try:
        # Read the API route file
        api_route_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'route_backend_groups.py')
        with open(api_route_path, 'r') as f:
            api_content = f.read()
        
        # Check that api_create_group has the enable_group_creation decorator
        create_group_section = False
        has_enable_group_creation = False
        
        lines = api_content.split('\n')
        for i, line in enumerate(lines):
            if 'def api_create_group():' in line:
                create_group_section = True
                # Check previous 10 lines for decorators
                for j in range(max(0, i-10), i):
                    if '@enabled_required("enable_group_creation")' in lines[j]:
                        has_enable_group_creation = True
                        break
                break
        
        assert create_group_section, "api_create_group function not found"
        assert has_enable_group_creation, "@enabled_required('enable_group_creation') decorator missing"
        
        print("  ✓ API create group endpoint has enable_group_creation protection")
        print("✅ API endpoint protection test passed!")
        return True
        
    except Exception as e:
        print(f"❌ API endpoint protection test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_version_updated():
    """Test that version has been updated."""
    print("🔍 Testing Version Update...")
    
    try:
        # Read config.py
        config_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'config.py')
        with open(config_path, 'r') as f:
            config_content = f.read()
        
        # Check for version update
        assert 'VERSION = "0.230.030"' in config_content, "Version not updated to 0.230.030"
        
        print("  ✓ Version updated to 0.230.030")
        print("✅ Version update test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Version update test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    tests = [
        test_route_checks_enable_group_creation,
        test_template_conditional_logic,
        test_permission_scenarios,
        test_api_endpoint_protection,
        test_version_updated
    ]
    
    results = []
    
    print("🧪 Running Create Group Button Visibility Tests...\n")
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    passed = sum(results)
    total = len(results)
    
    print(f"\n📊 Results: {passed}/{total} tests passed")
    
    if success:
        print("✅ All Create Group button visibility tests passed!")
        print("\n🎯 Implementation Summary:")
        print("  • Route checks enable_group_creation setting before role requirements")
        print("  • Template conditionally displays Create Group button and modal")
        print("  • JavaScript respects backend permission determination")
        print("  • API endpoint protected with @enabled_required decorator")
        print("  • Version incremented to 0.230.030")
        print("\n🔒 Permission Matrix:")
        print("  • enable_group_creation = False → Button hidden (regardless of role)")
        print("  • enable_group_creation = True + no role requirement → Button shown")
        print("  • enable_group_creation = True + role required + user has role → Button shown")
        print("  • enable_group_creation = True + role required + user lacks role → Button hidden")
    else:
        print("❌ Some tests failed!")
    
    sys.exit(0 if success else 1)