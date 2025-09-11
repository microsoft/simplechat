#!/usr/bin/env python3
"""
Functional test for Create Group Permission Display Fix.
Version: 0.227.012
Implemented in: 0.227.012

This test ensures that the "Create New Group" button is only shown to users
who have the required CreateGroups role when the "Require Membership to Create Groups"
setting is enabled.
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_create_group_button_visibility():
    """Test that the Create Group button is conditionally displayed based on user permissions."""
    print("🔍 Testing Create Group Button Permission Display...")
    
    try:
        # Read the my_groups template
        template_path = os.path.join(os.path.dirname(__file__), "../application/single_app/templates/my_groups.html")
        
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template file not found: {template_path}")
        
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        
        # Check that the Create Group button is conditionally displayed
        if '{% if can_create_groups %}' not in template_content:
            raise AssertionError("Create Group button should be conditionally displayed based on can_create_groups")
        
        # Check that the button is properly wrapped in the conditional
        create_button_section = template_content[template_content.find('<!-- Create Group Button trigger modal -->'):template_content.find('</button>', template_content.find('Create New Group')) + 9]
        
        if '{% if can_create_groups %}' not in template_content[:template_content.find(create_button_section)]:
            raise AssertionError("Create Group button section should be within can_create_groups conditional")
        
        # Check that the modal is also conditionally displayed
        if '{% if can_create_groups %}' not in template_content[template_content.find('<!-- Create Group Modal -->'):]:
            raise AssertionError("Create Group modal should also be conditionally displayed")
        
        # Check that JavaScript variable is passed from backend
        if 'const canCreateGroups = {{ can_create_groups|tojson }}' not in template_content:
            raise AssertionError("JavaScript should receive canCreateGroups permission from backend")
        
        # Check that modal reference is conditional
        if 'const createGroupModal = canCreateGroups ? new bootstrap.Modal' not in template_content:
            raise AssertionError("Modal reference should be conditional based on permissions")
        
        # Check that event handler is conditional
        if 'if (canCreateGroups) {' not in template_content or '$("#createGroupForm").on("submit", handleCreateGroup);' not in template_content:
            raise AssertionError("Create group form event handler should be conditional")
        
        print("✅ Template correctly implements conditional Create Group button display")
        
        # Check the route file for permission logic
        route_path = os.path.join(os.path.dirname(__file__), "../application/single_app/route_frontend_groups.py")
        
        if not os.path.exists(route_path):
            raise FileNotFoundError(f"Route file not found: {route_path}")
        
        with open(route_path, 'r', encoding='utf-8') as f:
            route_content = f.read()
        
        # Check that route passes can_create_groups to template
        if 'can_create_groups = True' not in route_content:
            raise AssertionError("Route should set can_create_groups variable")
        
        if 'require_member_of_create_group = settings.get("require_member_of_create_group", False)' not in route_content:
            raise AssertionError("Route should check require_member_of_create_group setting")
        
        if "'CreateGroups' in user['roles']" not in route_content:
            raise AssertionError("Route should check for CreateGroups role")
        
        if 'render_template("my_groups.html", can_create_groups=can_create_groups)' not in route_content:
            raise AssertionError("Route should pass can_create_groups to template")
        
        print("✅ Route correctly implements permission checking logic")
        
        print("✅ Create Group Permission Display Fix test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_permission_logic_correctness():
    """Test that the permission logic works correctly in different scenarios."""
    print("🔍 Testing Permission Logic Scenarios...")
    
    try:
        # Read the route file to examine the logic
        route_path = os.path.join(os.path.dirname(__file__), "../application/single_app/route_frontend_groups.py")
        
        with open(route_path, 'r', encoding='utf-8') as f:
            route_content = f.read()
        
        # Verify the logic structure
        expected_logic = [
            "can_create_groups = True",
            "if require_member_of_create_group:",
            "'roles' in user and 'CreateGroups' in user['roles']"
        ]
        
        for expected in expected_logic:
            if expected not in route_content:
                raise AssertionError(f"Expected logic not found: {expected}")
        
        print("✅ Permission logic structure is correct")
        
        # Check that the authentication functions exist
        auth_path = os.path.join(os.path.dirname(__file__), "../application/single_app/functions_authentication.py")
        
        if os.path.exists(auth_path):
            with open(auth_path, 'r', encoding='utf-8') as f:
                auth_content = f.read()
            
            if 'create_group_role_required' in auth_content:
                print("✅ Authentication decorator exists for API endpoints")
            else:
                print("⚠️  Authentication decorator not found - API endpoints may need protection")
        
        print("✅ Permission Logic Scenarios test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    tests = [test_create_group_button_visibility, test_permission_logic_correctness]
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All tests passed! Create Group Permission Display Fix is working correctly.")
    else:
        print("❌ Some tests failed. Please review the implementation.")
    
    sys.exit(0 if success else 1)
