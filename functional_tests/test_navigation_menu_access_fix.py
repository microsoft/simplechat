#!/usr/bin/env python3
"""
Functional test for Navigation Menu Access Fix.
Version: 0.227.015
Implemented in: 0.227.015

This test ensures that the "My Groups" and "My Public Workspaces" navigation menu items
are visible to ALL users when the respective features are enabled, regardless of their
CreateGroups or CreatePublicWorkspaces role membership.
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_sidebar_navigation_menu_access():
    """Test that navigation menu items are not restricted by create permissions."""
    print("🔍 Testing Sidebar Navigation Menu Access...")
    
    try:
        # Read the sidebar navigation template
        template_path = os.path.join(os.path.dirname(__file__), "../application/single_app/templates/_sidebar_nav.html")
        
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template file not found: {template_path}")
        
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        
        # Check that My Groups menu item only depends on feature being enabled
        my_groups_section = template_content[template_content.find('My Groups'):]
        my_groups_section = my_groups_section[:my_groups_section.find('</li>') + 5]
        
        # Look backwards to find the conditional
        before_my_groups = template_content[:template_content.find('My Groups')]
        my_groups_conditional_start = before_my_groups.rfind('{% if')
        my_groups_conditional = template_content[my_groups_conditional_start:template_content.find('My Groups') + len('My Groups')]
        
        # Should only check for enable_group_workspaces, not create permissions
        if 'require_member_of_create_group' in my_groups_conditional:
            raise AssertionError("My Groups menu item should not check create group permissions")
        
        if 'CreateGroups' in my_groups_conditional:
            raise AssertionError("My Groups menu item should not check CreateGroups role")
        
        if 'app_settings.enable_group_workspaces' not in my_groups_conditional:
            raise AssertionError("My Groups menu item should check if group workspaces are enabled")
        
        # Check that My Public Workspaces menu item only depends on feature being enabled
        my_public_workspaces_section = template_content[template_content.find('My Public Workspaces'):]
        my_public_workspaces_section = my_public_workspaces_section[:my_public_workspaces_section.find('</li>') + 5]
        
        # Look backwards to find the conditional
        before_my_public_workspaces = template_content[:template_content.find('My Public Workspaces')]
        my_public_workspaces_conditional_start = before_my_public_workspaces.rfind('{% if')
        my_public_workspaces_conditional = template_content[my_public_workspaces_conditional_start:template_content.find('My Public Workspaces') + len('My Public Workspaces')]
        
        # Should only check for enable_public_workspaces, not create permissions
        if 'require_member_of_create_public_workspace' in my_public_workspaces_conditional:
            raise AssertionError("My Public Workspaces menu item should not check create public workspace permissions")
        
        if 'CreatePublicWorkspaces' in my_public_workspaces_conditional:
            raise AssertionError("My Public Workspaces menu item should not check CreatePublicWorkspaces role")
        
        if 'app_settings.enable_public_workspaces' not in my_public_workspaces_conditional:
            raise AssertionError("My Public Workspaces menu item should check if public workspaces are enabled")
        
        print("✅ Sidebar navigation correctly shows menu items based only on feature enablement")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_top_navigation_menu_access():
    """Test that top navigation menu items are not restricted by create permissions."""
    print("🔍 Testing Top Navigation Menu Access...")
    
    try:
        # Read the top navigation template
        template_path = os.path.join(os.path.dirname(__file__), "../application/single_app/templates/_top_nav.html")
        
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template file not found: {template_path}")
        
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        
        # Check that My Groups menu item only depends on feature being enabled
        my_groups_section = template_content[template_content.find('My Groups'):]
        my_groups_section = my_groups_section[:my_groups_section.find('</li>') + 5]
        
        # Look backwards to find the conditional
        before_my_groups = template_content[:template_content.find('My Groups')]
        my_groups_conditional_start = before_my_groups.rfind('{% if')
        my_groups_conditional = template_content[my_groups_conditional_start:template_content.find('My Groups') + len('My Groups')]
        
        # Should only check for enable_group_workspaces, not create permissions
        if 'require_member_of_create_group' in my_groups_conditional:
            raise AssertionError("Top nav My Groups menu item should not check create group permissions")
        
        if 'CreateGroups' in my_groups_conditional:
            raise AssertionError("Top nav My Groups menu item should not check CreateGroups role")
        
        if 'app_settings.enable_group_workspaces' not in my_groups_conditional:
            raise AssertionError("Top nav My Groups menu item should check if group workspaces are enabled")
        
        # Check that My Public Workspaces menu item only depends on feature being enabled
        my_public_workspaces_section = template_content[template_content.find('My Public Workspaces'):]
        my_public_workspaces_section = my_public_workspaces_section[:my_public_workspaces_section.find('</li>') + 5]
        
        # Look backwards to find the conditional
        before_my_public_workspaces = template_content[:template_content.find('My Public Workspaces')]
        my_public_workspaces_conditional_start = before_my_public_workspaces.rfind('{% if')
        my_public_workspaces_conditional = template_content[my_public_workspaces_conditional_start:template_content.find('My Public Workspaces') + len('My Public Workspaces')]
        
        # Should only check for enable_public_workspaces, not create permissions
        if 'require_member_of_create_public_workspace' in my_public_workspaces_conditional:
            raise AssertionError("Top nav My Public Workspaces menu item should not check create public workspace permissions")
        
        if 'CreatePublicWorkspaces' in my_public_workspaces_conditional:
            raise AssertionError("Top nav My Public Workspaces menu item should not check CreatePublicWorkspaces role")
        
        if 'app_settings.enable_public_workspaces' not in my_public_workspaces_conditional:
            raise AssertionError("Top nav My Public Workspaces menu item should check if public workspaces are enabled")
        
        print("✅ Top navigation correctly shows menu items based only on feature enablement")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_navigation_consistency():
    """Test that both navigation templates have consistent behavior."""
    print("🔍 Testing Navigation Template Consistency...")
    
    try:
        # Read both navigation templates
        sidebar_path = os.path.join(os.path.dirname(__file__), "../application/single_app/templates/_sidebar_nav.html")
        top_nav_path = os.path.join(os.path.dirname(__file__), "../application/single_app/templates/_top_nav.html")
        
        with open(sidebar_path, 'r', encoding='utf-8') as f:
            sidebar_content = f.read()
        
        with open(top_nav_path, 'r', encoding='utf-8') as f:
            top_nav_content = f.read()
        
        # Both should have the same conditional logic for My Groups
        expected_groups_condition = "{% if app_settings.enable_group_workspaces %}"
        if expected_groups_condition not in sidebar_content:
            raise AssertionError("Sidebar should have correct My Groups conditional")
        
        if expected_groups_condition not in top_nav_content:
            raise AssertionError("Top nav should have correct My Groups conditional")
        
        # Both should have the same conditional logic for My Public Workspaces
        expected_public_condition = "{% if app_settings.enable_public_workspaces %}"
        if expected_public_condition not in sidebar_content:
            raise AssertionError("Sidebar should have correct My Public Workspaces conditional")
        
        if expected_public_condition not in top_nav_content:
            raise AssertionError("Top nav should have correct My Public Workspaces conditional")
        
        print("✅ Both navigation templates have consistent conditional logic")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    tests = [test_sidebar_navigation_menu_access, test_top_navigation_menu_access, test_navigation_consistency]
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All tests passed! Navigation Menu Access Fix is working correctly.")
        print("🎯 Users can now access 'My Groups' and 'My Public Workspaces' regardless of create permissions!")
    else:
        print("❌ Some tests failed. Please review the implementation.")
    
    sys.exit(0 if success else 1)
