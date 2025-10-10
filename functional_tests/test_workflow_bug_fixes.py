#!/usr/bin/env python3
"""
Quick test for workflow bug fixes.
Version: 0.229.062
Fixes applied: CSS references and API endpoint conflicts

This test ensures that the workflow feature bug fixes work correctly:
- CSS MIME type errors resolved
- API endpoint conflicts resolved  
- Frontend uses existing document APIs
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_workflow_css_fixes():
    """Test that workflow templates no longer reference workspace.css."""
    print("🔍 Testing Workflow CSS Fixes...")
    
    try:
        template_dir = os.path.join('..', 'application', 'single_app', 'templates')
        workflow_templates = [
            'workflow.html',
            'workflow_file_selection.html',
            'workflow_summary_selection.html',
            'workflow_summary_view.html'
        ]
        
        all_fixed = True
        for template in workflow_templates:
            template_path = os.path.join(template_dir, template)
            if os.path.exists(template_path):
                with open(template_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                if 'workspace.css' in content:
                    print(f"❌ {template} still references workspace.css")
                    all_fixed = False
                else:
                    print(f"✅ {template} CSS references fixed")
            else:
                print(f"❌ Template missing: {template}")
                all_fixed = False
        
        return all_fixed
        
    except Exception as e:
        print(f"❌ Workflow CSS test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_workflow_api_endpoints():
    """Test that workflow uses existing API endpoints."""
    print("🔍 Testing Workflow API Endpoint Updates...")
    
    try:
        template_path = os.path.join('..', 'application', 'single_app', 'templates', 'workflow_file_selection.html')
        
        if not os.path.exists(template_path):
            print("❌ workflow_file_selection.html not found")
            return False
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that old API endpoints are not used
        old_endpoints = [
            '/api/get-user-documents',
            '/api/get-group-documents', 
            '/api/get-public-documents'
        ]
        
        # Check that new API endpoints are used
        new_endpoints = [
            '/api/documents',
            '/api/group_documents',
            '/api/public_documents'
        ]
        
        all_updated = True
        
        for old_endpoint in old_endpoints:
            if old_endpoint in content:
                print(f"❌ Still using old endpoint: {old_endpoint}")
                all_updated = False
        
        for new_endpoint in new_endpoints:
            if new_endpoint in content:
                print(f"✅ Using correct endpoint: {new_endpoint}")
            else:
                print(f"❌ Missing correct endpoint: {new_endpoint}")
                all_updated = False
        
        # Check that response parsing is updated
        if 'data.success && data.documents' in content:
            print("❌ Still using old response format check")
            all_updated = False
        elif 'data.documents && data.documents.length' in content:
            print("✅ Using correct response format check")
        else:
            print("⚠️ Response format check not found")
        
        return all_updated
        
    except Exception as e:
        print(f"❌ Workflow API test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_no_route_conflicts():
    """Test that workflow routes don't conflict with existing routes."""
    print("🔍 Testing No Route Conflicts...")
    
    try:
        # Import the workflow route module
        sys.path.insert(0, os.path.join('..', 'application', 'single_app'))
        from route_frontend_workflow import register_route_frontend_workflow
        
        print("✅ Workflow route module imported successfully")
        
        # Check workflow file for duplicate function names
        workflow_file_path = os.path.join('..', 'application', 'single_app', 'route_frontend_workflow.py')
        with open(workflow_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        duplicate_functions = [
            'api_get_user_documents',
            'api_get_group_documents',
            'api_get_public_documents'
        ]
        
        conflicts_found = False
        for func_name in duplicate_functions:
            if f'def {func_name}(' in content:
                print(f"❌ Duplicate function found: {func_name}")
                conflicts_found = True
        
        if not conflicts_found:
            print("✅ No duplicate function definitions found")
            return True
        else:
            return False
        
    except Exception as e:
        print(f"❌ Route conflict test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_version_update():
    """Test that version was properly updated."""
    print("🔍 Testing Version Update...")
    
    try:
        config_path = os.path.join('..', 'application', 'single_app', 'config.py')
        
        if not os.path.exists(config_path):
            print("❌ Config file not found")
            return False
        
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if 'VERSION = "0.229.062"' in content:
            print("✅ Version properly updated to 0.229.062")
            return True
        else:
            print("❌ Version not updated correctly")
            return False
        
    except Exception as e:
        print(f"❌ Version update test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Workflow Bug Fixes Test")
    print("=" * 35)
    
    tests = [
        test_workflow_css_fixes,
        test_workflow_api_endpoints,
        test_no_route_conflicts,
        test_version_update
    ]
    
    results = []
    for test in tests:
        print()
        results.append(test())
    
    success_count = sum(results)
    total_count = len(results)
    
    print(f"\n📊 Test Results: {success_count}/{total_count} tests passed")
    
    if success_count == total_count:
        print("🎉 All bug fixes verified! Workflow feature should work properly.")
        sys.exit(0)
    else:
        print("❌ Some tests failed. Please review the bug fixes.")
        sys.exit(1)