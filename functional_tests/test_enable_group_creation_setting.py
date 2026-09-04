#!/usr/bin/env python3
"""
Functional test for enable_group_creation setting implementation.
Version: 0.230.029
Implemented in: 0.230.029

This test ensures that the enable_group_creation setting works correctly across:
- Default settings configuration
- Admin settings interface
- Control center interface
- API endpoint protection
- Consistent behavior between interfaces
"""

import sys
import os
from test_support.versioning import assert_app_version_at_least
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_default_settings_include_enable_group_creation():
    """Test that default settings include enable_group_creation."""
    print("🔍 Testing Default Settings for enable_group_creation...")
    
    try:
        # Read the functions_settings.py file directly to check for enable_group_creation
        settings_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'functions_settings.py')
        with open(settings_path, 'r') as f:
            settings_content = f.read()
        
        # Verify enable_group_creation exists in default settings
        assert "'enable_group_creation': True" in settings_content, "enable_group_creation setting missing from defaults"
        
        # Verify it's in the right section (workspaces)
        assert "# Workspaces" in settings_content, "Workspaces section missing from default settings"
        
        print("  ✓ enable_group_creation exists in default settings")
        print("  ✓ enable_group_creation defaults to True")
        print("✅ Default settings test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Default settings test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_admin_settings_template_includes_toggle():
    """Test that admin settings template includes the enable_group_creation toggle."""
    print("🔍 Testing Admin Settings Template...")
    
    try:
        # Read the admin settings template
        template_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'templates', 'admin_settings.html')        
        with open(template_path, 'r') as f:
            template_content = f.read()
        
        # Check for enable_group_creation toggle
        assert 'id="enable_group_creation"' in template_content, "enable_group_creation toggle missing from admin settings"
        assert 'name="enable_group_creation"' in template_content, "enable_group_creation form name missing"
        assert 'Enable Group Creation' in template_content, "Enable Group Creation label missing"
        
        # Check that it's properly conditional on group workspaces
        assert 'enable_group_creation_setting' in template_content, "enable_group_creation_setting wrapper missing"
        
        print("  ✓ enable_group_creation toggle exists in admin settings")
        print("  ✓ Toggle is properly labeled")
        print("  ✓ Toggle is conditionally displayed")
        print("✅ Admin settings template test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Admin settings template test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_admin_settings_backend_processes_toggle():
    """Test that admin settings backend processes the enable_group_creation toggle."""
    print("🔍 Testing Admin Settings Backend...")
    
    try:
        # Read the admin settings route file
        backend_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'route_frontend_admin_settings.py')
        with open(backend_path, 'r') as f:
            backend_content = f.read()
        
        # Check that enable_group_creation is processed
        assert "'enable_group_creation': form_data.get('enable_group_creation') == 'on'" in backend_content, "enable_group_creation not processed in backend"
        
        print("  ✓ enable_group_creation is processed in admin settings backend")
        print("✅ Admin settings backend test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Admin settings backend test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_group_creation_api_has_required_decorator():
    """Test that the group creation API has the @enabled_required decorator."""
    print("🔍 Testing Group Creation API Protection...")
    
    try:
        # Read the groups backend route file
        backend_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'route_backend_groups.py')
        with open(backend_path, 'r') as f:
            backend_content = f.read()
        
        # Check that api_create_group has the enable_group_creation decorator
        api_create_section = False
        has_enable_group_creation = False
        
        lines = backend_content.split('\n')
        for i, line in enumerate(lines):
            if 'def api_create_group():' in line:
                api_create_section = True
                # Check previous 10 lines for decorators
                for j in range(max(0, i-10), i):
                    if '@enabled_required("enable_group_creation")' in lines[j]:
                        has_enable_group_creation = True
                        break
                break
        
        assert api_create_section, "api_create_group function not found"
        assert has_enable_group_creation, "@enabled_required('enable_group_creation') decorator missing from api_create_group"
        
        print("  ✓ api_create_group function found")
        print("  ✓ @enabled_required('enable_group_creation') decorator present")
        print("✅ Group creation API protection test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Group creation API protection test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_control_center_integration():
    """Test that control center properly integrates with enable_group_creation setting."""
    print("🔍 Testing Control Center Integration...")
    
    try:
        # Read the control center template
        template_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'templates', 'control_center.html')
        with open(template_path, 'r') as f:
            template_content = f.read()
        
        # Check for disable group creation toggle
        assert 'id="disableGroupCreation"' in template_content, "disableGroupCreation toggle missing"
        assert 'Disable Group Creation' in template_content, "Disable Group Creation label missing"
        
        # Check for save functionality
        assert 'saveGlobalGroupSettings' in template_content, "saveGlobalGroupSettings function missing"
        assert 'loadGlobalSettings' in template_content, "loadGlobalSettings function missing"
        
        # Check for API integration
        assert '/api/admin/agents/settings/enable_group_creation' in template_content, "API endpoint integration missing"
        
        print("  ✓ Disable Group Creation toggle exists")
        print("  ✓ Save and load functions present")
        print("  ✓ API integration implemented")
        print("✅ Control center integration test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Control center integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_admin_settings_javascript_visibility():
    """Test that admin settings JavaScript properly handles toggle visibility."""
    print("🔍 Testing Admin Settings JavaScript...")
    
    try:
        # Read the admin settings JavaScript file
        js_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'static', 'js', 'admin', 'admin_settings.js')
        with open(js_path, 'r') as f:
            js_content = f.read()
        
        # Check for enable_group_creation_setting visibility logic
        assert 'enable_group_creation_setting' in js_content, "enable_group_creation_setting visibility logic missing"
        assert 'enableGroupWorkspacesToggle.checked' in js_content, "Group workspaces toggle dependency missing"
        
        print("  ✓ enable_group_creation_setting visibility logic present")
        print("  ✓ Proper dependency on group workspaces toggle")
        print("✅ Admin settings JavaScript test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Admin settings JavaScript test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_version_updated():
    """Test that version has been updated in config.py."""
    print("🔍 Testing Version Update...")
    
    try:
        # Read config.py
        config_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'config.py')
        with open(config_path, 'r') as f:
            config_content = f.read()
        
        # Check for version update
        assert_app_version_at_least("0.230.029")
        
        print("  ✓ Version updated to 0.230.029")
        print("✅ Version update test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Version update test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    tests = [
        test_default_settings_include_enable_group_creation,
        test_admin_settings_template_includes_toggle,
        test_admin_settings_backend_processes_toggle,
        test_group_creation_api_has_required_decorator,
        test_control_center_integration,
        test_admin_settings_javascript_visibility,
        test_version_updated
    ]
    
    results = []
    
    print("🧪 Running Enable Group Creation Setting Tests...\n")
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    passed = sum(results)
    total = len(results)
    
    print(f"\n📊 Results: {passed}/{total} tests passed")
    
    if success:
        print("✅ All enable_group_creation setting tests passed!")
        print("\n🎯 Implementation Summary:")
        print("  • Default setting added with value True")
        print("  • Admin settings toggle and backend processing implemented")
        print("  • API endpoint protection added with @enabled_required decorator")
        print("  • Control center integration with save/load functionality")
        print("  • JavaScript visibility logic for admin settings")
        print("  • Version incremented to 0.230.029")
    else:
        print("❌ Some tests failed!")
    
    sys.exit(0 if success else 1)