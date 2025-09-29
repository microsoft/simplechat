#!/usr/bin/env python3
"""
Functional test for backend conversations swagger integration.
Version: 0.229.067
Implemented in: 0.229.067

This test ensures that all conversation endpoints in route_backend_conversations.py 
have proper swagger integration with @swagger_route decorators and authentication security.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_conversations_swagger_imports():
    """Test that swagger imports are properly added to conversations route file."""
    print("🔍 Testing conversations swagger imports...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 
            'route_backend_conversations.py'
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

def test_conversations_swagger_decorators():
    """Test that all conversation endpoints have proper swagger decorators."""
    print("🔍 Testing conversations swagger decorators...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 
            'route_backend_conversations.py'
        )
        
        with open(route_file_path, 'r') as f:
            content = f.read()
        
        # Expected endpoints that should have swagger decorators
        expected_endpoints = [
            ('/api/get_messages', 'GET'),
            ('/api/image/<image_id>', 'GET'),
            ('/api/get_conversations', 'GET'),
            ('/api/create_conversation', 'POST'),
            ('/api/conversations/<conversation_id>', 'PUT'),
            ('/api/conversations/<conversation_id>', 'DELETE'),
            ('/api/delete_multiple_conversations', 'POST'),
            ('/api/conversations/<conversation_id>/metadata', 'GET')
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
        
        # Verify we found all expected endpoints
        if decorated_endpoints != len(expected_endpoints):
            print(f"❌ Expected {len(expected_endpoints)} decorated endpoints, found {decorated_endpoints}")
            return False
            
        print(f"✅ All {decorated_endpoints} conversation endpoints properly decorated")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_conversations_decorator_order():
    """Test that decorators are in correct order: @app.route -> @swagger_route -> @login_required."""
    print("🔍 Testing conversations decorator order...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 
            'route_backend_conversations.py'
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

def test_conversations_endpoint_coverage():
    """Test comprehensive coverage of all conversation endpoints."""
    print("🔍 Testing conversations endpoint coverage...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 
            'route_backend_conversations.py'
        )
        
        with open(route_file_path, 'r') as f:
            content = f.read()
        
        # Expected conversation management functions
        expected_functions = [
            'api_get_messages',
            'api_get_image', 
            'get_conversations',
            'create_conversation',
            'update_conversation_title',
            'delete_conversation',
            'delete_multiple_conversations',
            'get_conversation_metadata_api'
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
            
        print(f"✅ All {len(found_functions)} conversation functions found")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_conversations_auth_security_integration():
    """Test that get_auth_security() is properly integrated in swagger decorators."""
    print("🔍 Testing conversations auth security integration...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 
            'route_backend_conversations.py'
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

if __name__ == "__main__":
    print("🧪 Running Backend Conversations Swagger Integration Tests...")
    print("=" * 60)
    
    tests = [
        test_conversations_swagger_imports,
        test_conversations_swagger_decorators,
        test_conversations_decorator_order,
        test_conversations_endpoint_coverage,
        test_conversations_auth_security_integration
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
        print("✅ All conversations swagger integration tests PASSED!")
        print("🎉 Swagger integration successfully applied to all conversation endpoints")
        print("📚 All endpoints will now appear in /swagger documentation")
        print("🔐 Authentication security properly configured for all endpoints")
    else:
        print("❌ Some tests FAILED!")
        print("⚠️  Please review the swagger integration implementation")
    
    sys.exit(0 if success else 1)