#!/usr/bin/env python3
"""
Functional test for automatic request body schema generation in swagger_wrapper.
Version: 0.230.038
Implemented in: 0.230.038

This test ensures that the swagger wrapper automatically detects and generates
appropriate request body schemas for routes that use request.get_json() patterns.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Add the application directory to Python path
app_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app')
sys.path.insert(0, app_dir)

def test_auto_request_body_generation():
    """Test automatic request body schema generation from function analysis."""
    print("🔍 Testing automatic request body schema generation...")
    
    try:
        from swagger_wrapper import swagger_route, _analyze_function_request_body
        from flask import request
        
        # Test function that uses request.get_json() with field access patterns
        def sample_post_function():
            """Sample function that uses request.get_json()."""
            data = request.get_json()
            name = data.get('name')
            email = data.get('email') 
            user_id = data['user_id']
            enabled = data.get('enabled', True)
            created_date = data.get('created_date')
            return {"success": True}
        
        # Test the analysis function directly
        print("   📊 Testing _analyze_function_request_body...")
        result = _analyze_function_request_body(sample_post_function)
        
        if not result:
            print("   ❌ Analysis returned None - expected request body schema")
            return False
        
        # Verify the schema structure
        if result.get('type') != 'object':
            print(f"   ❌ Expected type 'object', got: {result.get('type')}")
            return False
        
        properties = result.get('properties', {})
        if not properties:
            print("   ❌ No properties detected in request body schema")
            return False
        
        # Check that detected fields have appropriate types
        expected_fields = {
            'name': 'string',
            'email': 'string', 
            'user_id': 'integer',
            'enabled': 'boolean',
            'created_date': 'string'
        }
        
        print(f"   📋 Detected fields: {list(properties.keys())}")
        print(f"   📋 Expected fields: {list(expected_fields.keys())}")
        
        for field, expected_type in expected_fields.items():
            if field not in properties:
                print(f"   ❌ Expected field '{field}' not detected")
                return False
            
            actual_type = properties[field].get('type')
            if actual_type != expected_type:
                print(f"   ❌ Field '{field}': expected type '{expected_type}', got '{actual_type}'")
                return False
            
            print(f"   ✅ Field '{field}': {actual_type} (correct)")
        
        print("   ✅ Request body analysis function working correctly")
        
        # Test decorator integration
        print("   🎯 Testing decorator integration...")
        
        @swagger_route(
            summary="Test endpoint with auto request body",
            auto_request_body=True,
            auto_schema=True
        )
        def decorated_function():
            """Test function for decorator integration."""
            data = request.get_json()
            username = data.get('username')
            password = data.get('password')
            remember_me = data.get('remember_me', False)
            return {"authenticated": True}
        
        # Check that the decorator stored the auto-generated request body
        swagger_doc = getattr(decorated_function, '_swagger_doc', None)
        if not swagger_doc:
            print("   ❌ No swagger documentation attached to decorated function")
            return False
        
        request_body = swagger_doc.get('request_body')
        if not request_body:
            print("   ❌ No request body in swagger documentation")
            return False
        
        if request_body.get('type') != 'object':
            print(f"   ❌ Expected request body type 'object', got: {request_body.get('type')}")
            return False
        
        body_properties = request_body.get('properties', {})
        expected_decorator_fields = ['username', 'password', 'remember_me']
        
        for field in expected_decorator_fields:
            if field not in body_properties:
                print(f"   ❌ Expected field '{field}' not found in decorator-generated schema")
                return False
            print(f"   ✅ Decorator field '{field}': {body_properties[field].get('type')}")
        
        print("   ✅ Decorator integration working correctly")
        
        # Test function without request.get_json() - should return None
        print("   🚫 Testing function without request body...")
        
        def no_request_body_function():
            """Function that doesn't use request.get_json()."""
            return {"data": "static"}
        
        no_body_result = _analyze_function_request_body(no_request_body_function)
        if no_body_result is not None:
            print(f"   ❌ Expected None for function without request body, got: {no_body_result}")
            return False
        
        print("   ✅ Correctly detected no request body needed")
        
        # Test disabled auto_request_body
        print("   ⚙️ Testing disabled auto_request_body...")
        
        @swagger_route(
            summary="Test endpoint with disabled auto request body",
            auto_request_body=False,
            auto_schema=True
        )
        def disabled_auto_function():
            """Function with auto_request_body disabled."""
            data = request.get_json()
            test_field = data.get('test_field')
            return {"result": test_field}
        
        disabled_doc = getattr(disabled_auto_function, '_swagger_doc', None)
        disabled_request_body = disabled_doc.get('request_body') if disabled_doc else None
        
        if disabled_request_body is not None:
            print(f"   ❌ Expected no auto-generated request body when disabled, got: {disabled_request_body}")
            return False
        
        print("   ✅ Auto request body correctly disabled")
        
        print("✅ All request body generation tests passed!")
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_request_body_spec_generation():
    """Test that request bodies are properly included in OpenAPI spec generation."""
    print("🔍 Testing request body inclusion in OpenAPI spec...")
    
    try:
        from flask import Flask
        from swagger_wrapper import swagger_route, extract_route_info
        import json
        
        # Create a test Flask app
        app = Flask(__name__)
        
        @app.route('/api/test-post', methods=['POST'])
        @swagger_route(
            summary="Test POST endpoint",
            auto_request_body=True,
            auto_schema=True
        )
        def test_post_endpoint():
            """Test POST endpoint with auto request body."""
            from flask import request
            data = request.get_json()
            name = data.get('name')
            age = data['age']
            active = data.get('active', True)
            return {"success": True, "name": name}
        
        # Generate OpenAPI spec
        with app.app_context():
            spec = extract_route_info(app)
        
        # Check if the route is in the spec
        paths = spec.get('paths', {})
        test_path = '/api/test-post'
        
        if test_path not in paths:
            print(f"   ❌ Route {test_path} not found in OpenAPI spec")
            return False
        
        post_operation = paths[test_path].get('post')
        if not post_operation:
            print(f"   ❌ POST operation not found for {test_path}")
            return False
        
        # Check if requestBody is present
        request_body = post_operation.get('requestBody')
        if not request_body:
            print(f"   ❌ No requestBody found in POST operation for {test_path}")
            return False
        
        print(f"   ✅ Request body found in OpenAPI spec")
        
        # Check request body structure
        if not request_body.get('required'):
            print(f"   ❌ Request body should be marked as required")
            return False
        
        content = request_body.get('content', {})
        json_content = content.get('application/json')
        if not json_content:
            print(f"   ❌ No application/json content type in request body")
            return False
        
        schema = json_content.get('schema')
        if not schema:
            print(f"   ❌ No schema in request body")
            return False
        
        if schema.get('type') != 'object':
            print(f"   ❌ Expected schema type 'object', got: {schema.get('type')}")
            return False
        
        properties = schema.get('properties', {})
        expected_props = ['name', 'age', 'active']
        
        for prop in expected_props:
            if prop not in properties:
                print(f"   ❌ Expected property '{prop}' not found in schema")
                return False
            print(f"   ✅ Property '{prop}': {properties[prop]}")
        
        print("   ✅ Request body properly included in OpenAPI specification")
        print("✅ OpenAPI spec generation test passed!")
        return True
        
    except Exception as e:
        print(f"❌ OpenAPI spec test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 Running Swagger Request Body Analysis Tests...")
    
    test1_result = test_auto_request_body_generation()
    test2_result = test_request_body_spec_generation()
    
    all_passed = test1_result and test2_result
    
    print(f"\n📊 Test Results:")
    print(f"   Auto Request Body Generation: {'✅ PASSED' if test1_result else '❌ FAILED'}")  
    print(f"   OpenAPI Spec Generation: {'✅ PASSED' if test2_result else '❌ FAILED'}")
    print(f"\n🎯 Overall Result: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    
    sys.exit(0 if all_passed else 1)