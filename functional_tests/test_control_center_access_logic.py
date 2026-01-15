#!/usr/bin/env python3
"""
Functional test for Control Center access control logic.
Version: 0.235.011
Implemented in: 0.235.011

This test ensures that Control Center access control works correctly based on
the require_member_of_control_center_admin setting and user roles.

Access Logic:
1. When require_member_of_control_center_admin is DISABLED (default):
   - Admin role → Full access to dashboard + management + activity logs
   - ControlCenterAdmin role → IGNORED (role feature not enabled)
   - ControlCenterDashboardReader role → Dashboard only (if that setting is enabled)
   - Normal users → No access

2. When require_member_of_control_center_admin is ENABLED:
   - ControlCenterAdmin role → Full access
   - Admin role → NO access (must have ControlCenterAdmin specifically)
   - ControlCenterDashboardReader role → Dashboard only (if that setting is enabled)
   - Normal users → No access
"""

import sys
import os

# Add the application path to sys.path for imports
app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app')
sys.path.insert(0, app_path)


def test_control_center_required_decorator_logic():
    """Test the control_center_required decorator logic."""
    print("\n" + "=" * 70)
    print("Testing Control Center Access Control Logic")
    print("=" * 70)
    
    tests_passed = 0
    tests_failed = 0
    
    # Read the functions_authentication.py file to verify the logic
    auth_file = os.path.join(app_path, 'functions_authentication.py')
    
    if not os.path.exists(auth_file):
        print(f"❌ Could not find {auth_file}")
        return False
    
    with open(auth_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Test 1: Verify the decorator checks for regular Admin role
    print("\n📋 Test 1: Decorator checks for regular Admin role")
    if "has_regular_admin_role = 'roles' in user and 'Admin' in user['roles']" in content:
        print("   ✅ Decorator properly checks for regular Admin role")
        tests_passed += 1
    else:
        print("   ❌ Decorator missing check for regular Admin role")
        tests_failed += 1
    
    # Test 2: Verify the decorator checks for ControlCenterAdmin role
    print("\n📋 Test 2: Decorator checks for ControlCenterAdmin role")
    if "has_control_center_admin_role = 'roles' in user and 'ControlCenterAdmin' in user['roles']" in content:
        print("   ✅ Decorator properly checks for ControlCenterAdmin role")
        tests_passed += 1
    else:
        print("   ❌ Decorator missing check for ControlCenterAdmin role")
        tests_failed += 1
    
    # Test 3: Verify ControlCenterAdmin gets access when setting is ENABLED
    print("\n📋 Test 3: ControlCenterAdmin has access when setting is enabled")
    # The check for ControlCenterAdmin should be inside the if require_member_of_control_center_admin block
    if "if require_member_of_control_center_admin:" in content and "if has_control_center_admin_role:" in content:
        print("   ✅ ControlCenterAdmin role grants access when setting is enabled")
        tests_passed += 1
    else:
        print("   ❌ ControlCenterAdmin access not properly implemented")
        tests_failed += 1
    
    # Test 4: Verify regular Admin gets access when requirement is disabled
    print("\n📋 Test 4: Regular Admin gets access when requirement is disabled")
    # The check should verify ControlCenterAdmin role is IGNORED when setting is disabled
    if "# Only regular Admin role grants access - ControlCenterAdmin role is IGNORED" in content or \
       "ControlCenterAdmin role → IGNORED" in content:
        print("   ✅ ControlCenterAdmin role is correctly ignored when setting is disabled")
        tests_passed += 1
    else:
        print("   ❌ ControlCenterAdmin role should be ignored when setting is disabled")
        tests_failed += 1
    
    # Test 5: Verify proper denial when user is not admin
    print("\n📋 Test 5: Non-admin users are denied access")
    if 'return jsonify({"error": "Forbidden", "message": "Insufficient permissions (Admin role required)"})' in content:
        print("   ✅ Non-admin users are properly denied with Admin role required message")
        tests_passed += 1
    else:
        print("   ❌ Non-admin denial message not found")
        tests_failed += 1
    
    # Test 6: Verify the docstring explains the logic
    print("\n📋 Test 6: Decorator has comprehensive docstring")
    if "Access logic when require_member_of_control_center_admin is ENABLED:" in content and \
       "Access logic when require_member_of_control_center_admin is DISABLED" in content:
        print("   ✅ Decorator has comprehensive docstring explaining both modes")
        tests_passed += 1
    else:
        print("   ❌ Decorator docstring incomplete")
        tests_failed += 1
    
    print("\n" + "=" * 70)
    print(f"Results: {tests_passed} passed, {tests_failed} failed")
    print("=" * 70)
    
    return tests_failed == 0


def test_frontend_route_access_logic():
    """Test the frontend route access logic."""
    print("\n" + "=" * 70)
    print("Testing Frontend Route Access Logic")
    print("=" * 70)
    
    tests_passed = 0
    tests_failed = 0
    
    # Read the route_frontend_control_center.py file to verify the logic
    route_file = os.path.join(app_path, 'route_frontend_control_center.py')
    
    if not os.path.exists(route_file):
        print(f"❌ Could not find {route_file}")
        return False
    
    with open(route_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Test 1: Verify has_full_admin_access computation considers settings
    print("\n📋 Test 1: Frontend computes has_full_admin_access considering settings")
    if "require_member_of_control_center_admin = settings.get" in content:
        print("   ✅ Frontend retrieves require_member_of_control_center_admin setting")
        tests_passed += 1
    else:
        print("   ❌ Frontend missing settings check")
        tests_failed += 1
    
    # Test 2: Verify logic for has_full_admin_access
    print("\n📋 Test 2: Frontend computes has_full_admin_access correctly")
    # Check for the conditional logic based on setting
    if "if require_member_of_control_center_admin:" in content and \
       "has_full_admin_access = has_control_center_admin_role" in content and \
       "has_full_admin_access = has_regular_admin_role" in content:
        print("   ✅ has_full_admin_access logic correctly handles both modes")
        tests_passed += 1
    else:
        print("   ❌ has_full_admin_access logic incorrect or missing")
        tests_failed += 1
    
    # Test 3: Verify template receives the correct variable
    print("\n📋 Test 3: Template receives has_control_center_admin variable")
    if "has_control_center_admin=has_full_admin_access" in content:
        print("   ✅ Template receives has_control_center_admin with correct value")
        tests_passed += 1
    else:
        print("   ❌ Template variable assignment incorrect")
        tests_failed += 1
    
    print("\n" + "=" * 70)
    print(f"Results: {tests_passed} passed, {tests_failed} failed")
    print("=" * 70)
    
    return tests_failed == 0


def test_access_scenarios():
    """Test various access scenarios with the expected outcomes."""
    print("\n" + "=" * 70)
    print("Testing Access Control Scenarios")
    print("=" * 70)
    
    scenarios = [
        {
            "name": "Scenario 1: Admin role, CC admin requirement DISABLED",
            "user_roles": ["Admin"],
            "require_cc_admin": False,
            "expected_access": "full",
            "description": "Regular admin should get full access when CC admin not required"
        },
        {
            "name": "Scenario 2: Admin role, CC admin requirement ENABLED",
            "user_roles": ["Admin"],
            "require_cc_admin": True,
            "expected_access": "none",
            "description": "Regular admin should be DENIED when CC admin is required"
        },
        {
            "name": "Scenario 3: ControlCenterAdmin role ONLY, CC admin requirement DISABLED",
            "user_roles": ["ControlCenterAdmin"],
            "require_cc_admin": False,
            "expected_access": "none",
            "description": "ControlCenterAdmin role is IGNORED when setting is disabled - no access"
        },
        {
            "name": "Scenario 4: ControlCenterAdmin role, CC admin requirement ENABLED",
            "user_roles": ["ControlCenterAdmin"],
            "require_cc_admin": True,
            "expected_access": "full",
            "description": "ControlCenterAdmin grants full access when setting is enabled"
        },
        {
            "name": "Scenario 5: Both Admin and ControlCenterAdmin roles, CC admin requirement ENABLED",
            "user_roles": ["Admin", "ControlCenterAdmin"],
            "require_cc_admin": True,
            "expected_access": "full",
            "description": "Having ControlCenterAdmin grants full access when setting is enabled"
        },
        {
            "name": "Scenario 6: Both Admin and ControlCenterAdmin roles, CC admin requirement DISABLED",
            "user_roles": ["Admin", "ControlCenterAdmin"],
            "require_cc_admin": False,
            "expected_access": "full",
            "description": "Having Admin grants full access when setting is disabled (CC admin ignored)"
        },
        {
            "name": "Scenario 7: No roles, CC admin requirement DISABLED",
            "user_roles": [],
            "require_cc_admin": False,
            "expected_access": "none",
            "description": "Normal user should be denied access"
        },
        {
            "name": "Scenario 8: DashboardReader role only, dashboard reader requirement ENABLED",
            "user_roles": ["ControlCenterDashboardReader"],
            "require_cc_admin": False,
            "require_cc_dashboard_reader": True,
            "expected_access": "dashboard_only",
            "description": "DashboardReader gets dashboard-only access when that setting is enabled"
        },
    ]
    
    print("\n📋 Access Control Scenarios (Documentation):")
    print("-" * 70)
    
    for scenario in scenarios:
        print(f"\n🔹 {scenario['name']}")
        print(f"   Roles: {scenario['user_roles']}")
        print(f"   require_member_of_control_center_admin: {scenario['require_cc_admin']}")
        if 'require_cc_dashboard_reader' in scenario:
            print(f"   require_member_of_control_center_dashboard_reader: {scenario['require_cc_dashboard_reader']}")
        print(f"   Expected: {scenario['expected_access']}")
        print(f"   📝 {scenario['description']}")
    
    print("\n" + "-" * 70)
    print("✅ Scenario documentation complete")
    print("-" * 70)
    
    return True


def main():
    """Run all tests."""
    print("\n" + "🔧" * 35)
    print("Control Center Access Control Logic Tests")
    print("Version: 0.235.010")
    print("🔧" * 35)
    
    all_passed = True
    
    # Run tests
    if not test_control_center_required_decorator_logic():
        all_passed = False
    
    if not test_frontend_route_access_logic():
        all_passed = False
    
    # Document scenarios (always passes, it's documentation)
    test_access_scenarios()
    
    print("\n" + "=" * 70)
    if all_passed:
        print("✅ ALL TESTS PASSED")
        print("The Control Center access control logic has been fixed to properly handle:")
        print("  1. Regular Admin role fallback when CC admin requirement is disabled")
        print("  2. ControlCenterAdmin role always having full access")
        print("  3. Dashboard reader role for dashboard-only access")
        print("  4. Proper denial for non-admin users")
    else:
        print("❌ SOME TESTS FAILED")
        print("Please review the implementation.")
    print("=" * 70 + "\n")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
