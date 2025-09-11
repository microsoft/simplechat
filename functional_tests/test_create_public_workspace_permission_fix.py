#!/usr/bin/env python3
"""
Functional test for Create Public Workspace Permission Display Fix.
Version: 0.227.013
Implemented in: 0.227.013

This test ensures that the "Create New Public Workspace" button is only shown to users
who have the required CreatePublicWorkspaces role when the "Require Membership to Create Public Workspaces"
setting is enabled.
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_create_public_workspace_button_visibility():
    """Test that the Create Public Workspace button is conditionally displayed based on user permissions."""
    print("🔍 Testing Create Public Workspace Button Permission Display...")
    
    try:
        # Read the my_public_workspaces template
        template_path = os.path.join(os.path.dirname(__file__), "../application/single_app/templates/my_public_workspaces.html")
        
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template file not found: {template_path}")
        
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        
        # Check that the Create Public Workspace button is conditionally displayed
        if '{% if can_create_public_workspaces %}' not in template_content:
            raise AssertionError("Create Public Workspace button should be conditionally displayed based on can_create_public_workspaces")
        
        # Check that the button is properly wrapped in the conditional
        create_button_section = template_content[template_content.find('Create New Public Workspace'):template_content.find('</button>', template_content.find('Create New Public Workspace')) + 9]
        
        if '{% if can_create_public_workspaces %}' not in template_content[:template_content.find(create_button_section)]:
            raise AssertionError("Create Public Workspace button section should be within can_create_public_workspaces conditional")
        
        # Check that the modal is also conditionally displayed
        if '{% if can_create_public_workspaces %}' not in template_content[template_content.find('<!-- Create Public Workspace Modal -->'):]:
            raise AssertionError("Create Public Workspace modal should also be conditionally displayed")
        
        # Check that JavaScript variable is passed from backend
        if 'window.canCreatePublicWorkspaces = {{ can_create_public_workspaces|tojson }}' not in template_content:
            raise AssertionError("JavaScript should receive canCreatePublicWorkspaces permission from backend")
        
        print("✅ Template correctly implements conditional Create Public Workspace button display")
        
        # Check the route file for permission logic
        route_path = os.path.join(os.path.dirname(__file__), "../application/single_app/route_frontend_public_workspaces.py")
        
        if not os.path.exists(route_path):
            raise FileNotFoundError(f"Route file not found: {route_path}")
        
        with open(route_path, 'r', encoding='utf-8') as f:
            route_content = f.read()
        
        # Check that route passes can_create_public_workspaces to template
        if 'can_create_public_workspaces = True' not in route_content:
            raise AssertionError("Route should set can_create_public_workspaces variable")
        
        if 'require_member_of_create_public_workspace = settings.get("require_member_of_create_public_workspace", False)' not in route_content:
            raise AssertionError("Route should check require_member_of_create_public_workspace setting")
        
        if "'CreatePublicWorkspaces' in user['roles']" not in route_content:
            raise AssertionError("Route should check for CreatePublicWorkspaces role")
        
        if 'can_create_public_workspaces=can_create_public_workspaces' not in route_content:
            raise AssertionError("Route should pass can_create_public_workspaces to template")
        
        # Check that the problematic decorator was removed from my_public_workspaces route
        my_workspaces_start = route_content.find('def my_public_workspaces')
        next_function_start = route_content.find('@app.route', my_workspaces_start + 10)  # Find next route after my_public_workspaces
        
        if my_workspaces_start == -1:
            raise AssertionError("my_public_workspaces function not found")
        
        if next_function_start == -1:
            # If no next function, check from my_public_workspaces to end
            my_workspaces_section = route_content[my_workspaces_start:]
        else:
            # Check only the my_public_workspaces section up to the next route
            my_workspaces_section = route_content[my_workspaces_start:next_function_start]
        
        if '@create_public_workspace_role_required' in my_workspaces_section:
            raise AssertionError("@create_public_workspace_role_required decorator should be removed from my_public_workspaces route")
        
        print("✅ Route correctly implements permission checking logic")
        
        print("✅ Create Public Workspace Permission Display Fix test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_javascript_permission_handling():
    """Test that the JavaScript correctly handles permissions."""
    print("🔍 Testing JavaScript Permission Handling...")
    
    try:
        # Read the JavaScript file
        js_path = os.path.join(os.path.dirname(__file__), "../application/single_app/static/js/public/my_public_workspaces.js")
        
        if not os.path.exists(js_path):
            raise FileNotFoundError(f"JavaScript file not found: {js_path}")
        
        with open(js_path, 'r', encoding='utf-8') as f:
            js_content = f.read()
        
        # Check that modal initialization is conditional
        if 'window.canCreatePublicWorkspaces ? new bootstrap.Modal' not in js_content:
            raise AssertionError("Modal initialization should be conditional based on permissions")
        
        # Check that form event handler is conditional
        if 'if (window.canCreatePublicWorkspaces) {' not in js_content:
            raise AssertionError("Form event handler should be conditional")
        
        if '$("#createPublicWorkspaceForm").on("submit", handleCreateForm);' not in js_content:
            raise AssertionError("Form submission handler should be present within conditional")
        
        # Check that createModal.hide() is safely handled
        if 'if (createModal) {' not in js_content or 'createModal.hide();' not in js_content:
            raise AssertionError("Modal hide should be safely handled for null modal")
        
        print("✅ JavaScript correctly handles permission-based functionality")
        
        print("✅ JavaScript Permission Handling test passed!")
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
        route_path = os.path.join(os.path.dirname(__file__), "../application/single_app/route_frontend_public_workspaces.py")
        
        with open(route_path, 'r', encoding='utf-8') as f:
            route_content = f.read()
        
        # Verify the logic structure
        expected_logic = [
            "can_create_public_workspaces = True",
            "if require_member_of_create_public_workspace:",
            "'roles' in user and 'CreatePublicWorkspaces' in user['roles']"
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
            
            if 'create_public_workspace_role_required' in auth_content:
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
    tests = [test_create_public_workspace_button_visibility, test_javascript_permission_handling, test_permission_logic_correctness]
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All tests passed! Create Public Workspace Permission Display Fix is working correctly.")
    else:
        print("❌ Some tests failed. Please review the implementation.")
    
    sys.exit(0 if success else 1)
