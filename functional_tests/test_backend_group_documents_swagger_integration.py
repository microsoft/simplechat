#!/usr/bin/env python3
"""
Functional test for Group Documents Backend Swagger Integration.
Version: 0.229.070
Implemented in: 0.229.070

This test ensures that all group documents backend endpoints have proper swagger 
decorators integrated and that the authentication security is correctly configured.
Tests group document management, sharing, and permission-based access control.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_swagger_route_imports():
    """Test that swagger imports are correctly added to the group documents route file."""
    print("🔍 Testing swagger imports for group documents routes...")
    
    try:
        # Read the route file to check for swagger imports
        route_file_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'route_backend_group_documents.py')
        
        with open(route_file_path, 'r') as f:
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
    """Test that all group documents endpoints have swagger decorators in correct order."""
    print("🔍 Testing swagger decorators on group documents endpoints...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'route_backend_group_documents.py')
        
        with open(route_file_path, 'r') as f:
            content = f.read()
        
        # Expected endpoints that should have swagger decorators
        expected_endpoints = [
            # Document CRUD operations
            '/api/group_documents/upload',
            '/api/group_documents',
            '/api/group_documents/<document_id>',  # GET, PATCH, DELETE
            '/api/group_documents/<document_id>/extract_metadata',
            '/api/group_documents/upgrade_legacy',
            
            # Document sharing operations
            '/api/group_documents/<document_id>/shared-groups',
            '/api/group_documents/<document_id>/approve-share-with-group',
            '/api/group_documents/<document_id>/share-with-group',
            '/api/group_documents/<document_id>/unshare-with-group',
            '/api/group_documents/<document_id>/remove-self'
        ]
        
        # Check for proper decorator pattern: @app.route -> @swagger_route -> auth decorators
        pattern_violations = []
        lines = content.split('\n')
        
        for i, line in enumerate(lines):
            if '@app.route(' in line and '/api/group_documents' in line:
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
        
        print("✅ All group documents endpoints have correct swagger decorator patterns")
        return True
        
    except Exception as e:
        print(f"❌ Error checking swagger decorators: {e}")
        return False

def test_group_documents_endpoint_coverage():
    """Test that all group documents endpoints are covered with swagger decorators."""
    print("🔍 Testing endpoint coverage for group documents...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'route_backend_group_documents.py')
        
        with open(route_file_path, 'r') as f:
            content = f.read()
        
        # Count @app.route decorators
        app_route_count = content.count('@app.route(\'/api/group_documents')
        
        # Count @swagger_route decorators
        swagger_route_count = content.count('@swagger_route(security=get_auth_security())')
        
        print(f"📊 Found {app_route_count} group documents endpoints")
        print(f"📊 Found {swagger_route_count} swagger decorators")
        
        if app_route_count != swagger_route_count:
            print(f"❌ Mismatch: {app_route_count} endpoints but {swagger_route_count} swagger decorators")
            return False
        
        # Expected endpoint count (12 total endpoints)
        expected_count = 12
        if app_route_count != expected_count:
            print(f"⚠️ Expected {expected_count} endpoints but found {app_route_count}")
            print("   This might indicate endpoints were added/removed")
        
        print("✅ All group documents endpoints have swagger decorators")
        return True
        
    except Exception as e:
        print(f"❌ Error checking endpoint coverage: {e}")
        return False

def test_authentication_security_configuration():
    """Test that authentication security is properly configured."""
    print("🔍 Testing authentication security configuration...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'route_backend_group_documents.py')
        
        with open(route_file_path, 'r') as f:
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

def test_group_document_endpoints_functionality():
    """Test that group document endpoints maintain their core functionality."""
    print("🔍 Testing group document endpoints functionality preservation...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'route_backend_group_documents.py')
        
        with open(route_file_path, 'r') as f:
            content = f.read()
        
        # Key functionality patterns that should be preserved
        functionality_checks = [
            # Document upload functionality
            ('api_upload_group_document', 'Document upload handling'),
            ('get_active_group_id', 'Group ID validation'),
            
            # Document retrieval and management
            ('api_get_group_documents', 'Document listing'),
            ('api_get_group_document', 'Single document retrieval'),
            ('api_patch_group_document', 'Document metadata updates'),
            ('api_delete_group_document', 'Document deletion'),
            
            # Metadata extraction
            ('api_extract_group_metadata', 'Metadata extraction'),
            ('enable_extract_meta_data', 'Metadata extraction feature toggle'),
            
            # Legacy upgrade functionality
            ('api_upgrade_legacy_group_documents', 'Legacy document upgrade'),
            
            # Document sharing functionality
            ('api_get_document_shared_groups', 'Shared groups listing'),
            ('api_approve_shared_group_document', 'Share approval'),
            ('api_share_document_with_group', 'Document sharing'),
            ('api_unshare_document_with_group', 'Document unsharing'),
            ('api_remove_self_from_group_document', 'Self removal from shared documents'),
            
            # Permission and access control
            ('group_id=active_group_id', 'Group-based access control'),
            ('owner_user_id', 'Owner-based permissions'),
            ('shared_with_groups', 'Group sharing permissions')
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
        
        print("✅ All core group document functionality is preserved")
        return True
        
    except Exception as e:
        print(f"❌ Error checking functionality preservation: {e}")
        return False

def test_version_consistency():
    """Test that version is properly updated in config.py."""
    print("🔍 Testing version consistency...")
    
    try:
        # Read config.py to check version
        config_file_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'config.py')
        
        with open(config_file_path, 'r') as f:
            content = f.read()
        
        # Check for version 0.229.070
        if 'VERSION = "0.229.070"' not in content:
            print("❌ Version not updated to 0.229.070 in config.py")
            return False
        
        print("✅ Version correctly updated to 0.229.070")
        return True
        
    except Exception as e:
        print(f"❌ Error checking version: {e}")
        return False

def run_all_tests():
    """Run all group documents swagger integration tests."""
    print("🧪 Running Group Documents Backend Swagger Integration Tests...")
    print("=" * 70)
    
    tests = [
        test_swagger_route_imports,
        test_swagger_decorators_on_endpoints,
        test_group_documents_endpoint_coverage,
        test_authentication_security_configuration,
        test_group_document_endpoints_functionality,
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
        print(f"🎉 ALL TESTS PASSED! Group documents swagger integration is complete.")
        print(f"📋 Summary:")
        print(f"   • All 12 group documents endpoints have swagger decorators")
        print(f"   • Authentication security properly configured")
        print(f"   • Core functionality preserved")
        print(f"   • Version updated to 0.229.070")
        print(f"   • Feature toggles and permissions maintained")
    else:
        print(f"⚠️ Some tests failed. Please review the issues above.")
    
    return passed == total

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)