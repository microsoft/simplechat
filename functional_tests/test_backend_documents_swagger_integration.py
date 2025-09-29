#!/usr/bin/env python3
"""
Functional test for backend documents swagger integration.
Version: 0.229.068
Implemented in: 0.229.068

This test ensures that all document endpoints in route_backend_documents.py 
have proper swagger integration with @swagger_route decorators and authentication security.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_documents_swagger_imports():
    """Test that swagger imports are properly added to documents route file."""
    print("🔍 Testing documents swagger imports...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 
            'route_backend_documents.py'
        )
        
        with open(route_file_path, 'r') as f:
            content = f.read()
        
        # Verify swagger imports are present
        if 'from swagger_wrapper import swagger_route, get_auth_security' not in content:
            print("❌ Missing swagger wrapper imports")
            return False
            
        print("✅ Swagger imports found successfully")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_documents_swagger_decorators():
    """Test that all document endpoints have proper swagger decorators."""
    print("🔍 Testing documents swagger decorators...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 
            'route_backend_documents.py'
        )
        
        with open(route_file_path, 'r') as f:
            content = f.read()
        
        # Expected endpoints that should have swagger decorators
        expected_endpoints = [
            '/api/get_file_content',
            '/api/documents/upload', 
            '/api/documents',
            '/api/documents/<document_id>',  # GET, PATCH, DELETE versions
            '/api/documents/<document_id>/extract_metadata',
            '/api/get_citation',
            '/api/documents/upgrade_legacy',
            '/api/documents/<document_id>/share',
            '/api/documents/<document_id>/unshare',
            '/api/documents/<document_id>/shared-users',
            '/api/documents/<document_id>/remove-self',
            '/api/documents/<document_id>/approve-share'
        ]
        
        # Track found decorators
        decorated_endpoints = 0
        
        # Split content into lines for analysis
        lines = content.split('\n')
        
        for i, line in enumerate(lines):
            if '@app.route(' in line:
                # Found a route, check if next line has swagger decorator
                if i + 1 < len(lines) and '@swagger_route(security=get_auth_security())' in lines[i + 1]:
                    decorated_endpoints += 1
                    print(f"✅ Found properly decorated endpoint: {line.strip()}")
                else:
                    print(f"❌ Missing swagger decorator for: {line.strip()}")
                    return False
        
        # Verify we found all expected endpoints (14 total)
        if decorated_endpoints != 14:
            print(f"❌ Expected 14 decorated endpoints, found {decorated_endpoints}")
            return False
            
        print(f"✅ All {decorated_endpoints} document endpoints properly decorated")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_documents_decorator_order():
    """Test that decorators are in correct order: @app.route -> @swagger_route -> @login_required."""
    print("🔍 Testing documents decorator order...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 
            'route_backend_documents.py'
        )
        
        with open(route_file_path, 'r') as f:
            content = f.read()
        
        lines = content.split('\n')
        route_count = 0
        
        for i, line in enumerate(lines):
            if '@app.route(' in line:
                route_count += 1
                
                # Check if decorators are in correct order
                if (i + 1 < len(lines) and '@swagger_route(security=get_auth_security())' in lines[i + 1] and
                    i + 2 < len(lines) and '@login_required' in lines[i + 2]):
                    print(f"✅ Correct decorator order for endpoint {route_count}")
                else:
                    print(f"❌ Incorrect decorator order for endpoint {route_count}")
                    print(f"   Route: {line.strip()}")
                    if i + 1 < len(lines):
                        print(f"   Next: {lines[i + 1].strip()}")
                    if i + 2 < len(lines):
                        print(f"   Then: {lines[i + 2].strip()}")
                    return False
        
        print(f"✅ All {route_count} endpoints have correct decorator order")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_documents_endpoint_coverage():
    """Test comprehensive coverage of all document endpoints."""
    print("🔍 Testing documents endpoint coverage...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 
            'route_backend_documents.py'
        )
        
        with open(route_file_path, 'r') as f:
            content = f.read()
        
        # Expected document management functions
        expected_functions = [
            'get_file_content',
            'api_user_upload_document',
            'api_get_user_documents',
            'api_get_user_document',
            'api_patch_user_document',
            'api_delete_user_document',
            'api_extract_user_metadata',
            'get_citation',
            'api_upgrade_legacy_user_documents',
            'api_share_document',
            'api_unshare_document',
            'api_get_shared_users',
            'api_remove_self_from_document',
            'api_approve_shared_document'
        ]
        
        found_functions = []
        
        for func_name in expected_functions:
            if f'def {func_name}(' in content:
                found_functions.append(func_name)
                print(f"✅ Found function: {func_name}")
            else:
                print(f"❌ Missing function: {func_name}")
                return False
        
        if len(found_functions) != len(expected_functions):
            print(f"❌ Expected {len(expected_functions)} functions, found {len(found_functions)}")
            return False
            
        print(f"✅ All {len(found_functions)} document functions found")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_documents_auth_security_integration():
    """Test that get_auth_security() is properly integrated in swagger decorators."""
    print("🔍 Testing documents auth security integration...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 
            'route_backend_documents.py'
        )
        
        with open(route_file_path, 'r') as f:
            content = f.read()
        
        # Count occurrences of security integration
        security_decorators = content.count('@swagger_route(security=get_auth_security())')
        app_routes = content.count('@app.route(')
        
        if security_decorators != app_routes:
            print(f"❌ Mismatch: {app_routes} routes but {security_decorators} security decorators")
            return False
            
        # Verify get_auth_security is imported
        if 'get_auth_security' not in content:
            print("❌ get_auth_security function not imported")
            return False
            
        print(f"✅ All {security_decorators} endpoints have proper auth security integration")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_documents_enabled_required_preservation():
    """Test that @enabled_required decorators are preserved where needed."""
    print("🔍 Testing documents enabled_required preservation...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 
            'route_backend_documents.py'
        )
        
        with open(route_file_path, 'r') as f:
            content = f.read()
        
        # Most document endpoints should have @enabled_required("enable_user_workspace")
        enabled_required_count = content.count('@enabled_required("enable_user_workspace")')
        
        # Only get_citation doesn't have enabled_required, so we should have 13 occurrences
        expected_enabled_required = 13
        
        if enabled_required_count != expected_enabled_required:
            print(f"❌ Expected {expected_enabled_required} @enabled_required decorators, found {enabled_required_count}")
            return False
            
        print(f"✅ All {enabled_required_count} appropriate endpoints have @enabled_required preservation")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 Running Backend Documents Swagger Integration Tests...")
    print("=" * 60)
    
    tests = [
        test_documents_swagger_imports,
        test_documents_swagger_decorators,
        test_documents_decorator_order,
        test_documents_endpoint_coverage,
        test_documents_auth_security_integration,
        test_documents_enabled_required_preservation
    ]
    
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    passed = sum(results)
    total = len(results)
    
    print("\n" + "=" * 60)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if success:
        print("✅ All documents swagger integration tests PASSED!")
        print("🎉 Swagger integration successfully applied to all document endpoints")
        print("📚 All endpoints will now appear in /swagger documentation")
        print("🔐 Authentication security properly configured for all endpoints")
        print("🔒 Workspace enabling requirements preserved for document endpoints")
    else:
        print("❌ Some tests FAILED!")
        print("⚠️  Please review the swagger integration implementation")
    
    sys.exit(0 if success else 1)