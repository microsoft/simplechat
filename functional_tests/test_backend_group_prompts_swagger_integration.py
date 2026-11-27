#!/usr/bin/env python3
# test_backend_group_prompts_swagger_integration.py
"""
Functional test for Group Prompts Backend Swagger Integration.
Version: 0.229.071
Implemented in: 0.229.071

This test ensures that all group prompts backend endpoints have proper swagger 
decorators integrated and that the authentication security is correctly configured.
Tests group prompt management including CRUD operations.
"""

import sys
import os
from test_support.versioning import app_version_is_at_least  # noqa: E402
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_swagger_route_imports():
    """Test that swagger imports are correctly added to the group prompts route file."""
    print("🔍 Testing swagger imports for group prompts routes...")
    
    try:
        # Read the route file to check for swagger imports
        route_file_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'route_backend_group_prompts.py')
        
        with open(route_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for swagger imports
        required_imports = [
            'from swagger_wrapper import swagger_route, get_auth_security'
        ]
        
        for import_line in required_imports:
            if import_line not in content:
                print(f"❌ Missing import: {import_line}")
                return False
        
        print("✅ Swagger imports are correctly configured")
        return True
        
    except Exception as e:
        print(f"❌ Error checking swagger imports: {e}")
        return False

def test_swagger_decorators_on_endpoints():
    """Test that all group prompts endpoints have swagger decorators in correct order."""
    print("🔍 Testing swagger decorators on group prompts endpoints...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'route_backend_group_prompts.py')
        
        with open(route_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Expected endpoints that should have swagger decorators
        expected_endpoints = [
            # Prompt CRUD operations
            '/api/group_prompts',  # GET and POST
            '/api/group_prompts/<prompt_id>',  # GET, PATCH, DELETE
        ]
        
        # Check for proper decorator pattern: @app.route -> @swagger_route -> auth decorators
        pattern_violations = []
        lines = content.split('\n')
        
        for i, line in enumerate(lines):
            if '@app.route(' in line and '/api/group_prompts' in line:
                # Check if the next non-empty line is @swagger_route
                next_line_idx = i + 1
                while next_line_idx < len(lines) and lines[next_line_idx].strip() == '':
                    next_line_idx += 1
                
                if next_line_idx < len(lines):
                    next_line = lines[next_line_idx].strip()
                    if not next_line.startswith('@swagger_route(security=get_auth_security())'):
                        pattern_violations.append(f"Line {i+1}: Missing or incorrect swagger decorator after {line.strip()}")
        
        if pattern_violations:
            print("❌ Swagger decorator pattern violations found:")
            for violation in pattern_violations:
                print(f"   {violation}")
            return False
        
        print("✅ All group prompts endpoints have correct swagger decorator patterns")
        return True
        
    except Exception as e:
        print(f"❌ Error checking swagger decorators: {e}")
        return False

def test_group_prompts_endpoint_coverage():
    """Test that all group prompts endpoints are covered with swagger decorators."""
    print("🔍 Testing endpoint coverage for group prompts...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'route_backend_group_prompts.py')
        
        with open(route_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Count @app.route decorators
        app_route_count = content.count('@app.route(\'/api/group_prompts')
        
        # Count @swagger_route decorators
        swagger_route_count = content.count('@swagger_route(security=get_auth_security())')
        
        print(f"📊 Found {app_route_count} group prompts endpoints")
        print(f"📊 Found {swagger_route_count} swagger decorators")
        
        if app_route_count != swagger_route_count:
            print(f"❌ Mismatch: {app_route_count} endpoints but {swagger_route_count} swagger decorators")
            return False
        
        # Expected endpoint count (5 total endpoints)
        expected_count = 5
        if app_route_count != expected_count:
            print(f"⚠️ Expected {expected_count} endpoints but found {app_route_count}")
            print("   This might indicate endpoints were added/removed")
        
        print("✅ All group prompts endpoints have swagger decorators")
        return True
        
    except Exception as e:
        print(f"❌ Error checking endpoint coverage: {e}")
        return False

def test_authentication_security_configuration():
    """Test that authentication security is properly configured."""
    print("🔍 Testing authentication security configuration...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'route_backend_group_prompts.py')
        
        with open(route_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that all swagger decorators use get_auth_security()
        swagger_decorators = []
        for line in content.split('\n'):
            if '@swagger_route(' in line:
                swagger_decorators.append(line.strip())
        
        for decorator in swagger_decorators:
            if 'security=get_auth_security()' not in decorator:
                print(f"❌ Missing auth security in decorator: {decorator}")
                return False
        
        # Check that login_required and user_required decorators are preserved
        if '@login_required' not in content:
            print("❌ Missing @login_required decorators")
            return False
        
        if '@user_required' not in content:
            print("❌ Missing @user_required decorators")
            return False
            
        # Check that enable_group_workspaces feature toggle is preserved
        if '@enabled_required("enable_group_workspaces")' not in content:
            print("❌ Missing @enabled_required group workspaces decorators")
            return False
        
        print("✅ Authentication security is properly configured")
        return True
        
    except Exception as e:
        print(f"❌ Error checking authentication security: {e}")
        return False

def test_group_prompts_endpoints_functionality():
    """Test that group prompts endpoints maintain their core functionality."""
    print("🔍 Testing group prompts endpoints functionality preservation...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'route_backend_group_prompts.py')
        
        with open(route_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Key functionality patterns that should be preserved
        functionality_checks = [
            # Prompt CRUD operations
            ('get_group_prompts', 'Group prompts listing'),
            ('create_group_prompt', 'Group prompt creation'),
            ('get_group_prompt', 'Single group prompt retrieval'),
            ('update_group_prompt', 'Group prompt updates'),
            ('delete_group_prompt', 'Group prompt deletion'),
            
            # Core prompt functionality
            ('list_prompts', 'Prompt listing function'),
            ('create_prompt_doc', 'Prompt creation function'),
            ('get_prompt_doc', 'Prompt retrieval function'),
            ('update_prompt_doc', 'Prompt update function'),
            ('delete_prompt_doc', 'Prompt deletion function'),
            
            # Group context and access control
            ('get_current_user_id', 'User ID retrieval'),
            ('get_user_settings', 'User settings access'),
            ('activeGroupOid', 'Active group validation'),
            ('prompt_type="group_prompt"', 'Group prompt type specification'),
            ('group_id=active_group', 'Group-based access control'),
            
            # Validation and error handling
            ('No active group selected', 'Group validation error handling'),
            ('name', 'Prompt name validation'),
            ('content', 'Prompt content validation'),
            ('Prompt not found or access denied', 'Access control error handling')
        ]
        
        missing_functionality = []
        for pattern, description in functionality_checks:
            if pattern not in content:
                missing_functionality.append(f"{description} (pattern: {pattern})")
        
        if missing_functionality:
            print("❌ Missing core functionality:")
            for func in missing_functionality:
                print(f"   {func}")
            return False
        
        print("✅ All core group prompts functionality is preserved")
        return True
        
    except Exception as e:
        print(f"❌ Error checking functionality preservation: {e}")
        return False

def test_group_prompts_crud_operations():
    """Test that all CRUD operations are properly implemented."""
    print("🔍 Testing group prompts CRUD operations...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'route_backend_group_prompts.py')
        
        with open(route_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # CRUD operations that should be present
        crud_operations = [
            # Create (POST)
            ("methods=['POST']", "create_group_prompt", "POST /api/group_prompts"),
            
            # Read (GET)
            ("methods=['GET']", "get_group_prompts", "GET /api/group_prompts"),
            ("methods=['GET']", "get_group_prompt", "GET /api/group_prompts/<prompt_id>"),
            
            # Update (PATCH)
            ("methods=['PATCH']", "update_group_prompt", "PATCH /api/group_prompts/<prompt_id>"),
            
            # Delete (DELETE)
            ("methods=['DELETE']", "delete_group_prompt", "DELETE /api/group_prompts/<prompt_id>")
        ]
        
        missing_operations = []
        for method, function, description in crud_operations:
            if method not in content or function not in content:
                missing_operations.append(f"{description} ({function})")
        
        if missing_operations:
            print("❌ Missing CRUD operations:")
            for op in missing_operations:
                print(f"   {op}")
            return False
        
        print("✅ All group prompts CRUD operations are properly implemented")
        return True
        
    except Exception as e:
        print(f"❌ Error checking CRUD operations: {e}")
        return False

def test_version_consistency():
    """Test that version is properly updated in config.py."""
    print("🔍 Testing version consistency...")
    
    try:
        # Read config.py to check version
        config_file_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'config.py')
        
        with open(config_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for version 0.229.071
        if not app_version_is_at_least("0.229.071"):
            print("❌ Version not updated to 0.229.071 in config.py")
            return False
        
        print("✅ Version correctly updated to 0.229.071")
        return True
        
    except Exception as e:
        print(f"❌ Error checking version: {e}")
        return False

def run_all_tests():
    """Run all group prompts swagger integration tests."""
    print("🧪 Running Group Prompts Backend Swagger Integration Tests...")
    print("=" * 70)
    
    tests = [
        test_swagger_route_imports,
        test_swagger_decorators_on_endpoints,
        test_group_prompts_endpoint_coverage,
        test_authentication_security_configuration,
        test_group_prompts_endpoints_functionality,
        test_group_prompts_crud_operations,
        test_version_consistency
    ]
    
    results = []
    for test in tests:
        print(f"\n🔬 Running {test.__name__}...")
        result = test()
        results.append(result)
        print("-" * 50)
    
    # Summary
    passed = sum(results)
    total = len(results)
    
    print(f"\n📊 TEST SUMMARY")
    print(f"{'='*50}")
    print(f"✅ Passed: {passed}/{total}")
    print(f"❌ Failed: {total-passed}/{total}")
    
    if passed == total:
        print(f"🎉 ALL TESTS PASSED! Group prompts swagger integration is complete.")
        print(f"📋 Summary:")
        print(f"   • All 5 group prompts endpoints have swagger decorators")
        print(f"   • Authentication security properly configured")
        print(f"   • Core CRUD functionality preserved")
        print(f"   • Version updated to 0.229.071")
        print(f"   • Feature toggles and permissions maintained")
        print(f"   • Group workspace validation preserved")
    else:
        print(f"⚠️ Some tests failed. Please review the issues above.")
    
    return passed == total

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)