#!/usr/bin/env python3
"""
Functional test for Swagger Route Wrapper system.
Version: 0.229.061
Implemented in: 0.229.061

This test ensures that the swagger wrapper system works correctly and 
prevents regression of the auto-documentation functionality.
"""

import sys
import os
import requests
import json
import time
import urllib3

# Disable SSL warnings since we're testing with self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Add the application directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_swagger_wrapper_system():
    """Test the swagger wrapper system functionality."""
    print("🔍 Testing Swagger Route Wrapper System...")
    
    base_url = "https://127.0.0.1:5000"
    
    try:
        # Test 1: Check if /swagger endpoint returns HTML
        print("  📋 Testing /swagger endpoint...")
        response = requests.get(f"{base_url}/swagger", timeout=10, verify=False)
        if response.status_code != 200:
            print(f"❌ /swagger endpoint failed with status {response.status_code}")
            return False
        
        if "swagger-ui" not in response.text.lower():
            print("❌ /swagger endpoint doesn't contain Swagger UI")
            return False
        
        print("  ✅ /swagger endpoint working correctly")
        
        # Test 2: Check if /swagger.json returns valid OpenAPI spec
        print("  📋 Testing /swagger.json endpoint...")
        response = requests.get(f"{base_url}/swagger.json", timeout=10, verify=False)
        if response.status_code != 200:
            print(f"❌ /swagger.json endpoint failed with status {response.status_code}")
            return False
        
        try:
            spec = response.json()
        except json.JSONDecodeError:
            print("❌ /swagger.json endpoint doesn't return valid JSON")
            return False
        
        # Validate OpenAPI spec structure
        required_fields = ["openapi", "info", "paths"]
        for field in required_fields:
            if field not in spec:
                print(f"❌ OpenAPI spec missing required field: {field}")
                return False
        
        if spec.get("openapi") != "3.0.3":
            print(f"❌ Unexpected OpenAPI version: {spec.get('openapi')}")
            return False
        
        if spec.get("info", {}).get("title") != "SimpleChat API":
            print(f"❌ Unexpected API title: {spec.get('info', {}).get('title')}")
            return False
        
        print(f"  ✅ /swagger.json endpoint working correctly (found {len(spec.get('paths', {}))} paths)")
        
        # Test 3: Check if documented routes are present
        print("  📋 Testing documented routes presence...")
        paths = spec.get("paths", {})
        
        expected_routes = [
            "/api/models/gpt",
            "/api/models/embedding", 
            "/api/models/image"
        ]
        
        documented_routes = []
        for route in expected_routes:
            if route in paths:
                documented_routes.append(route)
                # Check if route has proper documentation
                route_spec = paths[route]
                if "get" in route_spec:
                    get_spec = route_spec["get"]
                    if "summary" in get_spec and "tags" in get_spec:
                        print(f"    ✅ {route} properly documented")
                    else:
                        print(f"    ⚠️  {route} missing summary or tags")
                else:
                    print(f"    ⚠️  {route} missing GET method documentation")
        
        print(f"  ✅ Found {len(documented_routes)}/{len(expected_routes)} expected documented routes")
        
        # Test 4: Check route listing endpoint
        print("  📋 Testing /api/swagger/routes endpoint...")
        response = requests.get(f"{base_url}/api/swagger/routes", timeout=10, verify=False)
        if response.status_code != 200:
            print(f"❌ /api/swagger/routes endpoint failed with status {response.status_code}")
            return False
        
        try:
            routes_data = response.json()
        except json.JSONDecodeError:
            print("❌ /api/swagger/routes endpoint doesn't return valid JSON")
            return False
        
        # Validate routes data structure
        required_fields = ["routes", "total_routes", "documented_routes", "undocumented_routes"]
        for field in required_fields:
            if field not in routes_data:
                print(f"❌ Routes data missing required field: {field}")
                return False
        
        total_routes = routes_data.get("total_routes", 0)
        documented_routes = routes_data.get("documented_routes", 0)
        undocumented_routes = routes_data.get("undocumented_routes", 0)
        
        if total_routes != documented_routes + undocumented_routes:
            print(f"❌ Route counts don't add up: {total_routes} != {documented_routes} + {undocumented_routes}")
            return False
        
        print(f"  ✅ Route listing working (Total: {total_routes}, Documented: {documented_routes}, Undocumented: {undocumented_routes})")
        
        # Test 5: Validate specific route documentation
        print("  📋 Testing specific route documentation quality...")
        models_routes = [route for route in routes_data.get("routes", []) if "/api/models/" in route.get("path", "")]
        
        expected_models_routes = 3  # gpt, embedding, image
        if len(models_routes) < expected_models_routes:
            print(f"❌ Expected at least {expected_models_routes} model routes, found {len(models_routes)}")
            return False
        
        for route in models_routes:
            if not route.get("documented", False):
                print(f"❌ Model route {route.get('path')} is not documented")
                return False
            
            if not route.get("tags"):
                print(f"⚠️  Model route {route.get('path')} missing tags (but is documented)")
            else:
                print(f"✅ Model route {route.get('path')} has tags: {route.get('tags')}")
        
        print(f"  ✅ All {len(models_routes)} model routes properly documented")
        
        # Test 6: Test swagger decorator preservation of functionality 
        print("  📋 Testing that decorated routes still work...")
        
        # This test would require authentication, so we just test for expected error codes
        test_routes = [
            ("/api/models/gpt", [401, 403]),  # Should require authentication
            ("/api/models/embedding", [401, 403]),
            ("/api/models/image", [401, 403])
        ]
        
        for route_path, expected_codes in test_routes:
            response = requests.get(f"{base_url}{route_path}", timeout=10, verify=False)
            if response.status_code not in expected_codes:
                print(f"❌ Route {route_path} returned unexpected status {response.status_code}, expected one of {expected_codes}")
                return False
        
        print("  ✅ Decorated routes preserve authentication requirements")
        
        print("✅ All Swagger Route Wrapper tests passed!")
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error testing swagger endpoints: {e}")
        print("   💡 Make sure the Flask application is running on https://127.0.0.1:5000")
        return False
    except Exception as e:
        print(f"❌ Unexpected error testing swagger wrapper: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_swagger_integration():
    """Test integration with existing application structure."""
    print("🔍 Testing Swagger Integration...")
    
    try:
        # Test module imports
        print("  📋 Testing module imports...")
        from swagger_wrapper import swagger_route, register_swagger_routes, COMMON_SCHEMAS
        print("  ✅ Successfully imported swagger_wrapper modules")
        
        # Test schema definitions
        print("  📋 Testing schema definitions...")
        required_schemas = ["error_response", "success_response", "paginated_response"]
        for schema_name in required_schemas:
            if schema_name not in COMMON_SCHEMAS:
                print(f"❌ Missing required schema: {schema_name}")
                return False
            
            schema = COMMON_SCHEMAS[schema_name]
            if not isinstance(schema, dict) or "type" not in schema:
                print(f"❌ Invalid schema structure for {schema_name}")
                return False
        
        print(f"  ✅ All {len(required_schemas)} required schemas present and valid")
        
        # Test decorator functionality
        print("  📋 Testing decorator functionality...")
        
        @swagger_route(
            summary="Test Route",
            description="Test route for validation",
            tags=["Test"]
        )
        def test_function():
            return "test"
        
        if not hasattr(test_function, '_swagger_doc'):
            print("❌ Swagger decorator not attaching documentation metadata")
            return False
        
        doc = getattr(test_function, '_swagger_doc')
        if doc.get('summary') != "Test Route":
            print("❌ Swagger decorator not storing summary correctly")
            return False
        
        if doc.get('tags') != ["Test"]:
            print("❌ Swagger decorator not storing tags correctly") 
            return False
        
        print("  ✅ Swagger decorator working correctly")
        
        print("✅ All Swagger Integration tests passed!")
        return True
        
    except ImportError as e:
        print(f"❌ Failed to import swagger modules: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error testing swagger integration: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 Running Swagger Route Wrapper System Tests...")
    print("=" * 60)
    
    # Run integration tests first (don't require running server)
    integration_success = test_swagger_integration()
    
    if not integration_success:
        print("\n❌ Integration tests failed. Cannot proceed with endpoint tests.")
        sys.exit(1)
    
    print("\n" + "=" * 60)
    
    # Run endpoint tests (require running server)
    endpoint_success = test_swagger_wrapper_system()
    
    print("\n" + "=" * 60)
    
    if integration_success and endpoint_success:
        print("🎉 All tests passed! Swagger Route Wrapper system is working correctly.")
        sys.exit(0)
    else:
        print("❌ Some tests failed. Check the output above for details.")
        if not endpoint_success:
            print("💡 Endpoint tests failed - make sure the Flask app is running on https://127.0.0.1:5000")
        sys.exit(1)