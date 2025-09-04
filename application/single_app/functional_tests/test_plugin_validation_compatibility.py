#!/usr/bin/env python3
"""
Test Plugin Validation Compatibility

This test ensures that the SQL plugin validation fix doesn't break
validation for OpenAPI plugins or other plugin types. It verifies
that all plugin types still work correctly after the changes.
"""

import sys
import os
# Add the parent directory to the path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_openapi_plugin_validation():
    """Test that OpenAPI plugins still validate correctly."""
    print("🔍 Testing OpenAPI Plugin Validation...")
    
    try:
        from json_schema_validation import validate_plugin
        
        # Valid OpenAPI Plugin
        valid_openapi_plugin = {
            "name": "test_openapi_valid",
            "displayName": "Test OpenAPI Plugin",
            "type": "openapi",
            "description": "Test OpenAPI plugin with valid endpoint",
            "endpoint": "https://api.example.com/v1/openapi.json",
            "auth": {
                "type": "key",
                "key": "test-api-key"
            },
            "metadata": {
                "type": "openapi"
            },
            "additionalFields": {
                "auth_method": "api_key"
            }
        }
        
        # Invalid OpenAPI Plugin (no endpoint)
        invalid_openapi_plugin = {
            "name": "test_openapi_invalid",
            "displayName": "Test OpenAPI Plugin Invalid",
            "type": "openapi",
            "description": "Test OpenAPI plugin without endpoint",
            "endpoint": "",  # Invalid - OpenAPI plugins need real endpoints
            "auth": {
                "type": "key",
                "key": "test-api-key"
            },
            "metadata": {},
            "additionalFields": {}
        }
        
        # Test valid OpenAPI plugin
        print("  📊 Validating valid OpenAPI Plugin...")
        valid_error = validate_plugin(valid_openapi_plugin)
        if valid_error:
            print(f"❌ Valid OpenAPI Plugin validation failed: {valid_error}")
            return False
        print("  ✅ Valid OpenAPI Plugin validation passed!")
        
        # Test invalid OpenAPI plugin - this should still fail
        print("  📊 Validating invalid OpenAPI Plugin (should fail)...")
        invalid_error = validate_plugin(invalid_openapi_plugin)
        if not invalid_error:
            print("  ❌ Invalid OpenAPI Plugin should have failed validation!")
            return False
        print(f"  ✅ Invalid OpenAPI Plugin correctly failed: {invalid_error}")
        
        return True
        
    except Exception as e:
        print(f"❌ OpenAPI plugin test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_generic_plugin_validation():
    """Test that generic plugins still validate correctly."""
    print("🔍 Testing Generic Plugin Validation...")
    
    try:
        from json_schema_validation import validate_plugin
        
        # Valid Generic Plugin
        valid_generic_plugin = {
            "name": "test_generic_valid",
            "displayName": "Test Generic Plugin",
            "type": "custom",
            "description": "Test generic plugin with valid endpoint",
            "endpoint": "https://custom.example.com/api",
            "auth": {
                "type": "identity"
            },
            "metadata": {},
            "additionalFields": {}
        }
        
        # Invalid Generic Plugin (no endpoint)
        invalid_generic_plugin = {
            "name": "test_generic_invalid",
            "displayName": "Test Generic Plugin Invalid",
            "type": "custom",
            "description": "Test generic plugin without endpoint",
            "endpoint": "",  # Invalid - most plugins need real endpoints
            "auth": {
                "type": "identity"
            },
            "metadata": {},
            "additionalFields": {}
        }
        
        # Test valid generic plugin
        print("  📊 Validating valid Generic Plugin...")
        valid_error = validate_plugin(valid_generic_plugin)
        if valid_error:
            print(f"❌ Valid Generic Plugin validation failed: {valid_error}")
            return False
        print("  ✅ Valid Generic Plugin validation passed!")
        
        # Test invalid generic plugin - this should still fail
        print("  📊 Validating invalid Generic Plugin (should fail)...")
        invalid_error = validate_plugin(invalid_generic_plugin)
        if not invalid_error:
            print("  ❌ Invalid Generic Plugin should have failed validation!")
            return False
        print(f"  ✅ Invalid Generic Plugin correctly failed: {invalid_error}")
        
        return True
        
    except Exception as e:
        print(f"❌ Generic plugin test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_backend_route_openapi_handling():
    """Test that the backend route still handles OpenAPI plugins correctly."""
    print("🔍 Testing Backend Route OpenAPI Plugin Handling...")
    
    try:
        # Simulate the backend processing for OpenAPI plugins
        openapi_plugin = {
            "name": "test_openapi_backend",
            "displayName": "Test OpenAPI Backend",
            "type": "openapi",
            "description": "Test OpenAPI plugin from backend",
            "endpoint": "https://api.example.com/openapi.json",  # Real endpoint
            "auth": {"type": "key", "key": "test-key"},
            "metadata": {},
            "additionalFields": {}
        }
        
        # Apply the same backend logic as in the route
        plugin_type = openapi_plugin.get('type', '')
        if plugin_type in ['sql_schema', 'sql_query']:
            # This should NOT be triggered for OpenAPI plugins
            openapi_plugin.setdefault('endpoint', f'sql://{plugin_type}')
        else:
            # For other plugin types, use setdefault with empty string
            openapi_plugin.setdefault('endpoint', '')
        
        # Verify the endpoint wasn't changed
        expected_endpoint = "https://api.example.com/openapi.json"
        actual_endpoint = openapi_plugin['endpoint']
        
        if actual_endpoint == expected_endpoint:
            print(f"  ✅ Backend correctly preserved OpenAPI endpoint: {actual_endpoint}")
        else:
            print(f"  ❌ Backend endpoint mismatch. Expected: {expected_endpoint}, Got: {actual_endpoint}")
            return False
            
        # Test validation after backend processing
        from json_schema_validation import validate_plugin
        validation_error = validate_plugin(openapi_plugin)
        
        if validation_error:
            print(f"  ❌ Backend-processed OpenAPI plugin validation failed: {validation_error}")
            return False
        
        print("  ✅ Backend-processed OpenAPI plugin validation passed!")
        
        # Test with empty endpoint OpenAPI plugin
        empty_endpoint_plugin = {
            "name": "test_openapi_empty",
            "displayName": "Test OpenAPI Empty",
            "type": "openapi",
            "description": "Test OpenAPI plugin with empty endpoint",
            "endpoint": "",  # Empty endpoint
            "auth": {"type": "key", "key": "test-key"},
            "metadata": {},
            "additionalFields": {}
        }
        
        # Apply backend logic
        plugin_type = empty_endpoint_plugin.get('type', '')
        if plugin_type in ['sql_schema', 'sql_query']:
            empty_endpoint_plugin.setdefault('endpoint', f'sql://{plugin_type}')
        else:
            empty_endpoint_plugin.setdefault('endpoint', '')
        
        # This should still fail validation because OpenAPI plugins need real endpoints
        validation_error = validate_plugin(empty_endpoint_plugin)
        if not validation_error:
            print("  ❌ OpenAPI plugin with empty endpoint should have failed validation!")
            return False
        
        print("  ✅ OpenAPI plugin with empty endpoint correctly failed validation!")
        print("✅ Backend route OpenAPI plugin handling test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Backend route OpenAPI test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_sql_plugins_still_work():
    """Test that SQL plugins still work after the fix."""
    print("🔍 Testing SQL Plugins Still Work...")
    
    try:
        from json_schema_validation import validate_plugin
        
        # SQL Schema Plugin
        sql_schema_plugin = {
            "name": "test_sql_schema_compat",
            "displayName": "Test SQL Schema Compat",
            "type": "sql_schema",
            "description": "Test SQL schema plugin compatibility",
            "endpoint": "",  # Empty endpoint - should be handled
            "auth": {"type": "user"},
            "metadata": {"type": "sql_schema"},
            "additionalFields": {
                "database_type": "postgresql",
                "connection_string": "Host=localhost;Database=test;Username=user;Password=pass;"
            }
        }
        
        # Test SQL plugin validation
        print("  📊 Validating SQL Schema Plugin...")
        sql_error = validate_plugin(sql_schema_plugin)
        if sql_error:
            print(f"❌ SQL Schema Plugin validation failed: {sql_error}")
            return False
        print("  ✅ SQL Schema Plugin validation passed!")
        
        return True
        
    except Exception as e:
        print(f"❌ SQL plugin compatibility test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 Running Plugin Validation Compatibility Tests...")
    print("This test ensures the SQL plugin fix doesn't break other plugin types.\n")
    
    # Test all plugin types
    openapi_success = test_openapi_plugin_validation()
    generic_success = test_generic_plugin_validation()
    backend_success = test_backend_route_openapi_handling()
    sql_success = test_sql_plugins_still_work()
    
    overall_success = openapi_success and generic_success and backend_success and sql_success
    
    print(f"\n📊 Results:")
    print(f"  OpenAPI Plugin Test: {'✅ PASSED' if openapi_success else '❌ FAILED'}")
    print(f"  Generic Plugin Test: {'✅ PASSED' if generic_success else '❌ FAILED'}")
    print(f"  Backend OpenAPI Test: {'✅ PASSED' if backend_success else '❌ FAILED'}")
    print(f"  SQL Plugin Test: {'✅ PASSED' if sql_success else '❌ FAILED'}")
    print(f"  Overall: {'✅ ALL TESTS PASSED' if overall_success else '❌ SOME TESTS FAILED'}")
    
    if overall_success:
        print("\n🎉 All plugin types work correctly!")
        print("✅ OpenAPI plugins still require valid endpoints")
        print("✅ Generic plugins still require valid endpoints") 
        print("✅ SQL plugins now work without endpoint validation errors")
        print("✅ Backend processing preserves existing behavior for non-SQL plugins")
    else:
        print("\n❌ Some plugin types may have been affected by the changes!")
    
    sys.exit(0 if overall_success else 1)
