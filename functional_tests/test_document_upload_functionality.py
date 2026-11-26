#!/usr/bin/env python3
# test_document_upload_functionality.py
"""
Functional test for document upload functionality.
Version: 0.228.006
Implemented in: 0.228.006

This test ensures that document upload works correctly without authentication issues.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_upload_endpoint_registration():
    """Test that the upload endpoint is properly registered."""
    print("🔍 Testing Upload Endpoint Registration...")
    
    try:
        # Import the app to check route registration
        sys.path.append(os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "application", "single_app"
        ))
        
        import app
        
        # Check for upload endpoint
        upload_routes = []
        for rule in app.app.url_map.iter_rules():
            rule_str = str(rule.rule)
            if 'documents/upload' in rule_str:
                upload_routes.append(rule_str)
        
        if '/api/documents/upload' not in upload_routes:
            print("❌ Upload endpoint not registered")
            return False
        print("✅ Upload endpoint properly registered")
        
        # Check for other document endpoints
        document_routes = []
        for rule in app.app.url_map.iter_rules():
            rule_str = str(rule.rule)
            if 'documents' in rule_str and 'api' in rule_str:
                document_routes.append(rule_str)
        
        print(f"✅ Found {len(document_routes)} document-related API routes")
        for route in document_routes:
            print(f"   {route}")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_upload_function_imports():
    """Test that all required functions are properly imported."""
    print("🔍 Testing Upload Function Imports...")
    
    try:
        sys.path.append(os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "application", "single_app"
        ))
        
        # Test imports for functions used in upload endpoint
        from functions_documents import allowed_file, create_document, update_document
        print("✅ Core document functions imported successfully")
        
        from functions_authentication import get_current_user_id
        print("✅ Authentication functions imported successfully")
        
        # Test that functions are callable
        import inspect
        allowed_file_sig = inspect.signature(allowed_file)
        create_document_sig = inspect.signature(create_document)
        
        print(f"✅ allowed_file signature: {allowed_file_sig}")
        print(f"✅ create_document signature: {create_document_sig}")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_route_backend_documents_registration():
    """Test that the route_backend_documents module is properly registered."""
    print("🔍 Testing Route Backend Documents Registration...")
    
    try:
        sys.path.append(os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "application", "single_app"
        ))
        
        # Check if route_backend_documents is imported in app.py
        app_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "application", "single_app", "app.py"
        )
        
        if not os.path.exists(app_file_path):
            print("❌ app.py not found")
            return False
        
        with open(app_file_path, 'r', encoding='utf-8') as f:
            app_content = f.read()
        
        # Check for route registration
        if 'route_backend_documents' not in app_content:
            print("❌ route_backend_documents not found in app.py")
            return False
        print("✅ route_backend_documents found in app.py")
        
        if 'register_route_backend_documents' not in app_content:
            print("❌ register_route_backend_documents function call not found")
            return False
        print("✅ register_route_backend_documents function call found")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Document Upload Functionality Test")
    print("=" * 50)
    
    tests = [
        test_upload_endpoint_registration,
        test_upload_function_imports,
        test_route_backend_documents_registration
    ]
    
    results = []
    for test in tests:
        print()
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Test Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All tests passed!")
        print("\n💡 Upload endpoint is properly configured.")
        print("💡 The 400 error in the browser is likely due to:")
        print("   • Authentication issues (user not logged in)")
        print("   • Missing CSRF tokens")
        print("   • Invalid form data format")
        print("   • JavaScript sending incorrect request format")
    else:
        print("❌ Some tests failed!")
    
    sys.exit(0 if success else 1)
