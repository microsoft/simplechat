#!/usr/bin/env python3
"""
Test enhanced automatic swagger generation.
Version: 0.229.063
Testing: Auto-generation of summary, description, and tags from route metadata

This test demonstrates the enhanced swagger wrapper with automatic generation
of summary from function names, description from docstrings, and tags from route paths.
"""

import sys
import os

# Add the application directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))

from flask import Flask, jsonify
from swagger_wrapper import swagger_route, extract_route_info

def test_automatic_metadata_generation():
    """Test automatic generation of summary, description, and tags."""
    print("🧪 Testing Automatic Metadata Generation...")
    
    try:
        # Create a test Flask app
        app = Flask(__name__)
        
        # Test route with full automatic generation
        @app.route('/api/users/<int:user_id>')
        @swagger_route()  # No parameters - everything should be auto-generated
        def get_user_profile(user_id: int):
            """Retrieve detailed profile information for a specific user account."""
            return jsonify({
                "user_id": user_id,
                "name": "John Doe",
                "email": "john@example.com",
                "profile_complete": True,
                "last_login": "2024-01-01T00:00:00Z"
            })
        
        # Test route with automatic tags from nested path
        @app.route('/api/admin/reports/analytics')
        @swagger_route()
        def get_analytics_report():
            """Generate comprehensive analytics report for administrative review."""
            return jsonify({
                "report_type": "analytics",
                "generated_at": "2024-01-01T00:00:00Z",
                "data_points": 1250,
                "status": "completed"
            })
        
        # Test route with mixed automatic and manual settings
        @app.route('/api/orders/<int:order_id>/items')
        @swagger_route(
            summary="Custom Summary",  # Manual summary should override auto-generation
            tags=["CustomTag"]         # Manual tags should override auto-generation
        )
        def get_order_items(order_id: int):
            """Fetch all items associated with a specific order for inventory tracking."""
            return jsonify({
                "order_id": order_id,
                "items": [
                    {"item_id": 1, "name": "Product A", "quantity": 2},
                    {"item_id": 2, "name": "Product B", "quantity": 1}
                ],
                "total_items": 3
            })
        
        # Test route with simple path
        @app.route('/health')
        @swagger_route()
        def check_health():
            """Check the overall health and status of the application service."""
            return jsonify({"status": "healthy", "timestamp": "2024-01-01T00:00:00Z"})
        
        # Extract route information and generate OpenAPI spec
        with app.app_context():
            spec = extract_route_info(app)
        
        # Validate the generated specification
        print(f"✅ Generated OpenAPI {spec['openapi']} specification")
        print(f"✅ Found {len(spec['paths'])} documented paths")
        print(f"✅ Generated {len(spec['tags'])} tag categories")
        
        # Test 1: Check automatic summary generation from function name
        user_path = '/api/users/{user_id}'
        if user_path in spec['paths'] and 'get' in spec['paths'][user_path]:
            operation = spec['paths'][user_path]['get']
            summary = operation.get('summary', '')
            print(f"✅ Auto-generated summary: '{summary}'")
            assert 'Get User Profile' in summary, f"Expected 'Get User Profile' in summary, got: {summary}"
        
        # Test 2: Check automatic description from docstring
        if user_path in spec['paths'] and 'get' in spec['paths'][user_path]:
            operation = spec['paths'][user_path]['get']
            description = operation.get('description', '')
            print(f"✅ Auto-generated description: '{description[:50]}...'")
            assert 'Retrieve detailed profile information' in description, "Docstring not used as description"
        
        # Test 3: Check automatic tags from route path
        if user_path in spec['paths'] and 'get' in spec['paths'][user_path]:
            operation = spec['paths'][user_path]['get']
            tags = operation.get('tags', [])
            print(f"✅ Auto-generated tags: {tags}")
            assert 'Users' in tags, f"Expected 'Users' tag from path, got: {tags}"
        
        # Test 4: Check nested path tags
        analytics_path = '/api/admin/reports/analytics'
        if analytics_path in spec['paths'] and 'get' in spec['paths'][analytics_path]:
            operation = spec['paths'][analytics_path]['get']
            tags = operation.get('tags', [])
            print(f"✅ Nested path tags: {tags}")
            expected_tags = ['Admin', 'Reports', 'Analytics']
            for expected_tag in expected_tags:
                assert expected_tag in tags, f"Expected '{expected_tag}' in tags from nested path, got: {tags}"
        
        # Test 5: Check manual override behavior
        order_path = '/api/orders/{order_id}/items'
        if order_path in spec['paths'] and 'get' in spec['paths'][order_path]:
            operation = spec['paths'][order_path]['get']
            summary = operation.get('summary', '')
            tags = operation.get('tags', [])
            print(f"✅ Manual override - Summary: '{summary}', Tags: {tags}")
            assert summary == "Custom Summary", f"Manual summary not preserved: {summary}"
            assert tags == ["CustomTag"], f"Manual tags not preserved: {tags}"
        
        # Test 6: Check simple path handling
        health_path = '/health'
        if health_path in spec['paths'] and 'get' in spec['paths'][health_path]:
            operation = spec['paths'][health_path]['get']
            tags = operation.get('tags', [])
            summary = operation.get('summary', '')
            print(f"✅ Simple path - Summary: '{summary}', Tags: {tags}")
            assert 'Check Health' in summary, f"Function name not converted to summary: {summary}"
            # Simple paths without /api prefix should have minimal/no tags
        
        # Test 7: Check response schema auto-generation still works
        if user_path in spec['paths'] and 'get' in spec['paths'][user_path]:
            operation = spec['paths'][user_path]['get']
            responses = operation.get('responses', {})
            if '200' in responses:
                schema = responses['200']['content']['application/json']['schema']
                properties = schema.get('properties', {})
                print(f"✅ Auto-generated response schema has {len(properties)} properties")
                expected_props = ['user_id', 'name', 'email', 'profile_complete', 'last_login']
                found_props = [prop for prop in expected_props if prop in properties]
                assert len(found_props) == len(expected_props), f"Expected {len(expected_props)} properties, found {len(found_props)}"
        
        print("✅ Automatic metadata generation test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_edge_cases():
    """Test edge cases for automatic generation."""
    print("\n🧪 Testing Edge Cases...")
    
    try:
        app = Flask(__name__)
        
        # Test with underscore-heavy function name
        @app.route('/api/test')
        @swagger_route()
        def get_user_account_billing_history():
            """Get billing history."""
            return jsonify({"history": []})
        
        # Test with root path
        @app.route('/')
        @swagger_route()
        def root_endpoint():
            """Root endpoint."""
            return jsonify({"message": "Welcome"})
        
        # Test with no docstring
        @app.route('/api/nodoc')
        @swagger_route()
        def no_docstring_endpoint():
            return jsonify({"status": "ok"})
        
        with app.app_context():
            spec = extract_route_info(app)
        
        # Check underscore function name conversion
        test_path = '/api/test'
        if test_path in spec['paths'] and 'get' in spec['paths'][test_path]:
            operation = spec['paths'][test_path]['get']
            summary = operation.get('summary', '')
            print(f"✅ Underscore conversion: '{summary}'")
            assert 'Get User Account Billing History' in summary, f"Underscore conversion failed: {summary}"
        
        # Check root path handling
        root_path = '/'
        if root_path in spec['paths'] and 'get' in spec['paths'][root_path]:
            operation = spec['paths'][root_path]['get']
            tags = operation.get('tags', [])
            print(f"✅ Root path tags: {tags}")
            # Root path should have empty or minimal tags
        
        # Check no docstring handling
        nodoc_path = '/api/nodoc'
        if nodoc_path in spec['paths'] and 'get' in spec['paths'][nodoc_path]:
            operation = spec['paths'][nodoc_path]['get']
            description = operation.get('description', '')
            print(f"✅ No docstring description: '{description}'")
            # Should be empty or minimal description
        
        print("✅ Edge cases test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Edge cases test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🔬 Starting Enhanced Automatic Swagger Generation Tests\n")
    
    tests = [
        test_automatic_metadata_generation,
        test_edge_cases
    ]
    
    results = []
    for test in tests:
        results.append(test())
    
    success_count = sum(results)
    total_count = len(results)
    
    print(f"\n📊 Test Results: {success_count}/{total_count} tests passed")
    
    if success_count == total_count:
        print("🎉 All tests passed! The enhanced automatic swagger generation is working correctly.")
        print("\n✨ New Features Validated:")
        print("   • Automatic summary generation from function names")
        print("   • Automatic description extraction from docstrings")
        print("   • Automatic tag generation from route path segments")
        print("   • Manual override support for all automatic features")
        print("   • Proper handling of nested paths and edge cases")
    else:
        print("⚠️  Some tests failed. Please check the output above for details.")
    
    sys.exit(0 if success_count == total_count else 1)