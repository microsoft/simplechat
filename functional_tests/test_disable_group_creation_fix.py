# test_disable_group_creation_fix.py
#!/usr/bin/env python3
"""
Functional test for Disable Group Creation setting fix.
Version: 0.235.005
Implemented in: 0.235.004, 0.235.005

This test ensures that the "Disable Group Creation" toggle in admin_settings.html
correctly saves and inverts to the enable_group_creation setting.

Issue 1 (0.235.004): The form field was named "disable_group_creation" but the backend was
reading "enable_group_creation", causing the setting to never be saved properly.

Issue 2 (0.235.005): The Control Center save button had no onclick handler because
GroupManager.init() was never called to bind the event listener.

Fix 1: Changed backend to read "disable_group_creation" and invert the value.
Fix 2: Added onclick="GroupManager.saveGlobalSettings()" to the save button.
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_form_field_name_matches_backend():
    """Test that the form field name matches what the backend expects."""
    print("🔍 Testing form field name consistency...")
    
    try:
        # Read the admin_settings.html template
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'templates', 'admin_settings.html'
        )
        
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        
        # Verify the form field exists with name="disable_group_creation"
        assert 'name="disable_group_creation"' in template_content, \
            "Form field name='disable_group_creation' not found in template"
        
        print("  ✓ Form field 'disable_group_creation' exists in admin_settings.html")
        
        # Read the backend route file
        route_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'route_frontend_admin_settings.py'
        )
        
        with open(route_path, 'r', encoding='utf-8') as f:
            route_content = f.read()
        
        # Verify the backend reads 'disable_group_creation' and inverts it
        assert "form_data.get('disable_group_creation')" in route_content, \
            "Backend does not read 'disable_group_creation' from form data"
        
        print("  ✓ Backend reads 'disable_group_creation' from form data")
        
        # Verify the inversion logic exists
        assert "!= 'on'" in route_content or "form_data.get('disable_group_creation') != 'on'" in route_content, \
            "Backend does not properly invert the disable_group_creation value"
        
        print("  ✓ Backend inverts disable_group_creation to enable_group_creation")
        
        print("✅ Form field name consistency test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_control_center_toggle_exists():
    """Test that the Control Center also has the toggle with correct binding."""
    print("\n🔍 Testing Control Center toggle configuration...")
    
    try:
        # Read the control_center.html template
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'templates', 'control_center.html'
        )
        
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        
        # Verify the toggle exists
        assert 'id="disableGroupCreation"' in template_content, \
            "disableGroupCreation toggle not found in control_center.html"
        
        print("  ✓ Toggle 'disableGroupCreation' exists in control_center.html")
        
        # Verify the toggle is checked when enable_group_creation is False
        assert '{% if not settings.enable_group_creation %}checked{% endif %}' in template_content, \
            "Toggle not properly bound to enable_group_creation setting"
        
        print("  ✓ Toggle correctly inverted (checked when enable_group_creation is False)")
        
        # Verify the save function inverts the value
        assert "const enableCreation = !disableCreation" in template_content, \
            "Save function does not invert the disable toggle value"
        
        print("  ✓ Save function correctly inverts disable to enable")
        
        # Verify the save button has onclick handler (fix for 0.235.005)
        assert 'onclick="GroupManager.saveGlobalSettings()"' in template_content, \
            "Save button missing onclick handler for GroupManager.saveGlobalSettings()"
        
        print("  ✓ Save button has onclick handler bound to GroupManager.saveGlobalSettings()")
        
        print("✅ Control Center toggle test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_default_setting_exists():
    """Test that enable_group_creation has a default value."""
    print("\n🔍 Testing default setting exists...")
    
    try:
        # Read the functions_settings.py file
        settings_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'functions_settings.py'
        )
        
        with open(settings_path, 'r', encoding='utf-8') as f:
            settings_content = f.read()
        
        # Verify enable_group_creation exists in defaults
        assert "'enable_group_creation':" in settings_content, \
            "enable_group_creation not found in default settings"
        
        print("  ✓ enable_group_creation exists in default settings")
        
        # Verify it defaults to True
        assert "'enable_group_creation': True" in settings_content, \
            "enable_group_creation should default to True"
        
        print("  ✓ enable_group_creation defaults to True (groups can be created by default)")
        
        print("✅ Default setting test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_api_endpoint_exists():
    """Test that the API endpoint for updating the setting exists."""
    print("\n🔍 Testing API endpoint exists...")
    
    try:
        # Read the route_backend_agents.py file
        route_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'route_backend_agents.py'
        )
        
        with open(route_path, 'r', encoding='utf-8') as f:
            route_content = f.read()
        
        # Verify the generic settings update endpoint exists
        assert "/api/admin/agents/settings/<setting_name>" in route_content, \
            "Generic settings update endpoint not found"
        
        print("  ✓ Generic settings update endpoint exists")
        
        # Verify it supports POST method
        assert "@bpa.route('/api/admin/agents/settings/<setting_name>', methods=['POST'])" in route_content, \
            "POST method not supported for settings endpoint"
        
        print("  ✓ POST method supported for settings endpoint")
        
        print("✅ API endpoint test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Functional Test: Disable Group Creation Setting Fix")
    print("Version: 0.235.005")
    print("=" * 60)
    
    tests = [
        test_form_field_name_matches_backend,
        test_control_center_toggle_exists,
        test_default_setting_exists,
        test_api_endpoint_exists,
    ]
    
    results = []
    for test in tests:
        results.append(test())
    
    print("\n" + "=" * 60)
    success_count = sum(results)
    total_count = len(results)
    
    if all(results):
        print(f"✅ All {total_count} tests passed!")
        sys.exit(0)
    else:
        print(f"❌ {total_count - success_count}/{total_count} tests failed")
        sys.exit(1)
