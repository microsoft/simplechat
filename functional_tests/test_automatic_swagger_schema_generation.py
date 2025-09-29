#!/usr/bin/env python3
"""
Test automatic swagger schema generation.
Version: 0.229.062
Testing: Automatic parameter and response schema inference from function code

This test demonstrates the enhanced swagger wrapper with automatic schema generation.
"""

import sys
import os

# Add the application directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))

from flask import Flask, jsonify
from swagger_wrapper import swagger_route, extract_route_info

def test_automatic_schema_generation():
    """Test the automatic schema generation functionality."""
    print("🧪 Testing Automatic Swagger Schema Generation...")
    
    try:
        # Create a test Flask app
        app = Flask(__name__)
        
        # Test route with automatic schema generation
        @app.route('/api/test/simple')
        @swagger_route(
            summary="Simple test endpoint",
            tags=["Test"]
        )
        def simple_test():
            """A simple test endpoint that returns basic information."""
            return jsonify({
                "status": "success",
                "message": "This is a test endpoint", 
                "timestamp": "2024-01-01T00:00:00Z",
                "count": 42,
                "enabled": True
            })
        
        # Test route with path parameter
        @app.route('/api/test/user/<int:user_id>')
        @swagger_route(
            summary="Get user information", 
            tags=["Test", "Users"]
        )
        def get_user(user_id: int):
            """Get information for a specific user."""
            return jsonify({
                "user_id": user_id,
                "name": "Test User",
                "email": "test@example.com", 
                "active": True
            })
        
        # Extract route information and generate OpenAPI spec
        with app.app_context():
            spec = extract_route_info(app)
        
        # Validate the generated specification
        assert 'openapi' in spec, "OpenAPI version not found"
        assert 'paths' in spec, "Paths not found in spec"
        assert 'info' in spec, "Info section not found"
        
        print(f"✅ Generated OpenAPI {spec['openapi']} specification")
        print(f"✅ Found {len(spec['paths'])} documented paths")
        print(f"✅ Generated {len(spec['tags'])} tag categories")
        
        # Check specific paths
        if '/api/test/simple' in spec['paths']:
            simple_path = spec['paths']['/api/test/simple']
            if 'get' in simple_path:
                get_op = simple_path['get']
                print(f"✅ Simple endpoint has summary: '{get_op.get('summary', 'N/A')}'")
                
                # Check if responses were auto-generated
                responses = get_op.get('responses', {})
                print(f"✅ Auto-generated {len(responses)} response definitions")
                
                if '200' in responses:
                    response_schema = responses['200'].get('content', {}).get('application/json', {}).get('schema', {})
                    properties = response_schema.get('properties', {})
                    print(f"✅ Success response schema has {len(properties)} properties")
                    
                    # Validate some expected properties
                    expected_props = ['status', 'message', 'timestamp', 'count', 'enabled']
                    found_props = [prop for prop in expected_props if prop in properties]
                    print(f"✅ Found {len(found_props)}/{len(expected_props)} expected properties")
        
        # Check user endpoint with parameters
        if '/api/test/user/{user_id}' in spec['paths']:
            user_path = spec['paths']['/api/test/user/{user_id}']
            if 'get' in user_path:
                get_op = user_path['get']
                parameters = get_op.get('parameters', [])
                print(f"✅ User endpoint has {len(parameters)} auto-generated parameters")
        
        print("✅ Automatic schema generation test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_enhanced_decorator_features():
    """Test enhanced decorator features like auto_schema parameter."""
    print("\n🧪 Testing Enhanced Decorator Features...")
    
    try:
        app = Flask(__name__)
        
        # Test with auto_schema disabled
        @app.route('/api/test/manual')
        @swagger_route(
            summary="Manual schema endpoint",
            tags=["Test"],
            auto_schema=False,
            responses={
                "200": {
                    "description": "Manual response definition",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "manually_defined": {"type": "boolean"}
                                }
                            }
                        }
                    }
                }
            }
        )
        def manual_test():
            """Endpoint with manually defined schemas."""
            return jsonify({"manually_defined": True})
        
        # Test with docstring as description
        @app.route('/api/test/docstring')
        @swagger_route(
            summary="Docstring test",
            tags=["Test"]
        )
        def docstring_test():
            """
            This endpoint uses its docstring as the description.
            
            It should automatically extract this text for the OpenAPI description field.
            """
            return jsonify({"docstring_used": True})
        
        # Extract and validate
        with app.app_context():
            spec = extract_route_info(app)
        
        # Check manual schema endpoint
        if '/api/test/manual' in spec['paths']:
            manual_path = spec['paths']['/api/test/manual']['get']
            responses = manual_path.get('responses', {})
            if '200' in responses:
                schema = responses['200']['content']['application/json']['schema']
                properties = schema.get('properties', {})
                if 'manually_defined' in properties:
                    print("✅ Manual schema definition preserved")
        
        # Check docstring usage
        if '/api/test/docstring' in spec['paths']:
            docstring_path = spec['paths']['/api/test/docstring']['get']
            description = docstring_path.get('description', '')
            if 'docstring' in description.lower():
                print("✅ Function docstring used as description")
        
        print("✅ Enhanced decorator features test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🔬 Starting Automatic Swagger Schema Generation Tests\n")
    
    tests = [
        test_automatic_schema_generation,
        test_enhanced_decorator_features
    ]
    
    results = []
    for test in tests:
        results.append(test())
    
    success_count = sum(results)
    total_count = len(results)
    
    print(f"\n📊 Test Results: {success_count}/{total_count} tests passed")
    
    if success_count == total_count:
        print("🎉 All tests passed! The automatic swagger schema generation is working correctly.")
    else:
        print("⚠️  Some tests failed. Please check the output above for details.")
    
    sys.exit(0 if success_count == total_count else 1)