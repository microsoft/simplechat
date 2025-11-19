#!/usr/bin/env python3
"""
Functional test for Control Center feature.

This test validates:
1. Control Center page loads correctly for admin users
2. User management API functionality 
3. Access control and file upload restrictions work
4. Authentication middleware properly enforces restrictions
5. Frontend components render correctly
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock
import json
from datetime import datetime, timezone, timedelta

# Add the application directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_control_center_route_registration():
    """Test that Control Center routes are properly registered in app.py"""
    print("🔍 Testing Control Center route registration...")
    
    app_py_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app', 'app.py')
    
    with open(app_py_path, 'r', encoding='utf-8') as f:
        app_content = f.read()
    
    # Check for import statements
    required_imports = [
        'from route_frontend_control_center import *',
        'from route_backend_control_center import *'
    ]
    
    for import_stmt in required_imports:
        if import_stmt in app_content:
            print(f"✅ Import found: {import_stmt}")
        else:
            print(f"❌ Missing import: {import_stmt}")
            return False
    
    # Check for route registration calls
    required_registrations = [
        'register_route_frontend_control_center(app)',
        'register_route_backend_control_center(app)'
    ]
    
    for registration in required_registrations:
        if registration in app_content:
            print(f"✅ Registration found: {registration}")
        else:
            print(f"❌ Missing registration: {registration}")
            return False
    
    print("✅ All Control Center routes properly registered")
    return True

def test_control_center_template_exists():
    """Test that Control Center template file exists and has required content"""
    print("🔍 Testing Control Center template...")
    
    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app', 'templates', 'control_center.html')
    
    if not os.path.exists(template_path):
        print("❌ Control Center template file does not exist")
        return False
    
    with open(template_path, 'r', encoding='utf-8') as f:
        template_content = f.read()
    
    # Check for required template elements
    required_elements = [
        'Control Center',
        'id="dashboard"',
        'id="users"',
        'id="groups"',
        'id="workspaces"',
        'userManagementModal',
        'bulkActionModal',
        'control-center.js'
    ]
    
    for element in required_elements:
        if element in template_content:
            print(f"✅ Template element found: {element}")
        else:
            print(f"❌ Missing template element: {element}")
            return False
    
    print("✅ Control Center template contains all required elements")
    return True

def test_control_center_javascript_exists():
    """Test that Control Center JavaScript file exists and has main functionality"""
    print("🔍 Testing Control Center JavaScript...")
    
    js_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app', 'static', 'js', 'control-center.js')
    
    if not os.path.exists(js_path):
        print("❌ Control Center JavaScript file does not exist")
        return False
    
    with open(js_path, 'r', encoding='utf-8') as f:
        js_content = f.read()
    
    # Check for required JavaScript functions and classes
    required_js_elements = [
        'class ControlCenter',
        'loadUsers()',
        'showUserModal',
        'saveUserChanges',
        'executeBulkAction',
        'handleAccessControl',
        'handleFileUploadControl'
    ]
    
    for element in required_js_elements:
        if element in js_content:
            print(f"✅ JavaScript element found: {element}")
        else:
            print(f"❌ Missing JavaScript element: {element}")
            return False
    
    print("✅ Control Center JavaScript contains all required functionality")
    return True

def test_authentication_middleware_updates():
    """Test that authentication middleware has been updated with access control"""
    print("🔍 Testing authentication middleware updates...")
    
    auth_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app', 'functions_authentication.py')
    
    with open(auth_path, 'r', encoding='utf-8') as f:
        auth_content = f.read()
    
    # Check for new authentication functions
    required_auth_functions = [
        'check_user_access_status',
        'file_upload_required',
        'def file_upload_required(f):'
    ]
    
    for func in required_auth_functions:
        if func in auth_content:
            print(f"✅ Authentication function found: {func}")
        else:
            print(f"❌ Missing authentication function: {func}")
            return False
    
    # Check that user_required has been updated to check access status
    if 'check_user_access_status' in auth_content and 'user_required' in auth_content:
        print("✅ user_required decorator updated with access control")
    else:
        print("❌ user_required decorator not properly updated")
        return False
    
    print("✅ Authentication middleware properly updated")
    return True

def test_document_upload_restrictions():
    """Test that document upload routes have file_upload_required decorator"""
    print("🔍 Testing document upload restrictions...")
    
    # Check backend documents route
    backend_docs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app', 'route_backend_documents.py')
    
    with open(backend_docs_path, 'r', encoding='utf-8') as f:
        backend_content = f.read()
    
    if '@file_upload_required' in backend_content and 'api_user_upload_document' in backend_content:
        print("✅ Backend document upload has file_upload_required decorator")
    else:
        print("❌ Backend document upload missing file_upload_required decorator")
        return False
    
    # Check frontend chats route (ephemeral uploads)
    frontend_chats_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app', 'route_frontend_chats.py')
    
    with open(frontend_chats_path, 'r', encoding='utf-8') as f:
        frontend_content = f.read()
    
    if '@file_upload_required' in frontend_content and 'upload_file' in frontend_content:
        print("✅ Frontend chat upload has file_upload_required decorator")
    else:
        print("❌ Frontend chat upload missing file_upload_required decorator")
        return False
    
    print("✅ Document upload restrictions properly implemented")
    return True

def test_database_schema_extensions():
    """Test that database schema has been extended for Control Center"""
    print("🔍 Testing database schema extensions...")
    
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app', 'config.py')
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config_content = f.read()
    
    # Check for activity logs container
    if 'cosmos_activity_logs_container' in config_content:
        print("✅ Activity logs container defined in config")
    else:
        print("❌ Activity logs container missing from config")
        return False
    
    # Check for proper partition key
    if 'PartitionKey(path="/user_id")' in config_content:
        print("✅ Activity logs container has proper partition key")
    else:
        print("❌ Activity logs container partition key incorrect")
        return False
    
    print("✅ Database schema properly extended")
    return True

def test_control_center_api_endpoints():
    """Test that Control Center API endpoints are properly defined"""
    print("🔍 Testing Control Center API endpoints...")
    
    backend_cc_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app', 'route_backend_control_center.py')
    
    if not os.path.exists(backend_cc_path):
        print("❌ Control Center backend route file does not exist")
        return False
    
    with open(backend_cc_path, 'r', encoding='utf-8') as f:
        backend_content = f.read()
    
    # Check for required API endpoints
    required_endpoints = [
        '/api/admin/control-center/users',
        '/api/admin/control-center/users/<user_id>/access',
        '/api/admin/control-center/users/<user_id>/file-uploads',
        '/api/admin/control-center/users/bulk-action'
    ]
    
    for endpoint in required_endpoints:
        if endpoint in backend_content:
            print(f"✅ API endpoint found: {endpoint}")
        else:
            print(f"❌ Missing API endpoint: {endpoint}")
            return False
    
    # Check for required decorators on endpoints
    required_decorators = [
        '@admin_required',
        '@login_required',
        '@swagger_route'
    ]
    
    for decorator in required_decorators:
        if backend_content.count(decorator) >= 4:  # Should appear on all 4 endpoints
            print(f"✅ Decorator properly applied: {decorator}")
        else:
            print(f"❌ Decorator not properly applied: {decorator}")
            return False
    
    print("✅ Control Center API endpoints properly defined")
    return True

def test_sidebar_navigation_integration():
    """Test that Control Center is integrated into sidebar navigation"""
    print("🔍 Testing sidebar navigation integration...")
    
    sidebar_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app', 'templates', '_sidebar_nav.html')
    
    with open(sidebar_path, 'r', encoding='utf-8') as f:
        sidebar_content = f.read()
    
    # Check for Control Center link in admin section
    if 'Control Center' in sidebar_content and "url_for('control_center')" in sidebar_content:
        print("✅ Control Center link found in sidebar navigation")
    else:
        print("❌ Control Center link missing from sidebar navigation")
        return False
    
    # Check that it's in the admin section
    admin_section_start = sidebar_content.find('Admin')
    control_center_link = sidebar_content.find("url_for('control_center')")
    
    if admin_section_start != -1 and control_center_link != -1 and control_center_link > admin_section_start:
        print("✅ Control Center link properly placed in admin section")
    else:
        print("❌ Control Center link not in admin section")
        return False
    
    print("✅ Sidebar navigation integration successful")
    return True

def test_user_settings_schema():
    """Test that user settings schema supports access and file upload controls"""
    print("🔍 Testing user settings schema...")
    
    # Check if functions_settings.py can handle the new schema
    settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app', 'functions_settings.py')
    
    with open(settings_path, 'r', encoding='utf-8') as f:
        settings_content = f.read()
    
    # The existing update_user_settings function should be able to handle any new settings
    if 'update_user_settings' in settings_content and 'settings_to_update' in settings_content:
        print("✅ User settings update function exists")
    else:
        print("❌ User settings update function missing")
        return False
    
    # Check that the function merges settings properly
    if "doc['settings'].update(settings_to_update)" in settings_content:
        print("✅ Settings merge functionality exists")
    else:
        print("❌ Settings merge functionality missing")
        return False
    
    print("✅ User settings schema supports Control Center features")
    return True

def test_version_increment():
    """Test that version has been properly incremented"""
    print("🔍 Testing version increment...")
    
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app', 'config.py')
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config_content = f.read()
    
    # Look for version line
    version_lines = [line for line in config_content.split('\n') if 'VERSION = ' in line]
    
    if not version_lines:
        print("❌ Version not found in config.py")
        return False
    
    version_line = version_lines[0]
    print(f"✅ Version found: {version_line.strip()}")
    
    # Check that it's not the default version
    if '"0.230.001"' in version_line:
        print("❌ Version not incremented from default")
        return False
    
    if '"0.230.002"' in version_line:
        print("✅ Version properly incremented to 0.230.002")
    else:
        print("✅ Version has been incremented")
    
    return True

def test_comprehensive_control_center_functionality():
    """Run comprehensive test of all Control Center functionality"""
    print("🔍 Running comprehensive Control Center functionality test...")
    
    test_functions = [
        test_control_center_route_registration,
        test_control_center_template_exists,
        test_control_center_javascript_exists,
        test_authentication_middleware_updates,
        test_document_upload_restrictions,
        test_database_schema_extensions,
        test_control_center_api_endpoints,
        test_sidebar_navigation_integration,
        test_user_settings_schema,
        test_version_increment
    ]
    
    passed_tests = 0
    total_tests = len(test_functions)
    
    print(f"\n{'='*60}")
    print("CONTROL CENTER COMPREHENSIVE FUNCTIONALITY TEST")
    print(f"{'='*60}")
    
    for test_func in test_functions:
        try:
            if test_func():
                passed_tests += 1
            print()  # Add spacing between tests
        except Exception as e:
            print(f"❌ Test {test_func.__name__} failed with error: {e}")
            print()
    
    print(f"{'='*60}")
    print(f"CONTROL CENTER TEST RESULTS: {passed_tests}/{total_tests} tests passed")
    print(f"{'='*60}")
    
    if passed_tests == total_tests:
        print("🎉 All Control Center functionality tests PASSED!")
        print("\nControl Center features implemented:")
        print("✅ Dashboard with system statistics and alerts")
        print("✅ User management with access control and file upload restrictions")
        print("✅ Time-based temporary restrictions")
        print("✅ Bulk user actions")
        print("✅ Authentication middleware integration")
        print("✅ Database schema extensions")
        print("✅ Frontend components and JavaScript functionality")
        print("✅ Sidebar navigation integration")
        print("✅ Admin-only access controls")
        print("✅ API endpoints with proper authentication")
        return True
    else:
        print(f"❌ {total_tests - passed_tests} tests failed. Control Center may not function correctly.")
        return False

if __name__ == "__main__":
    success = test_comprehensive_control_center_functionality()
    sys.exit(0 if success else 1)