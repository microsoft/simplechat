# test_openapi_operation_lookup.py
"""
Test script to verify the improved operation lookup in OpenAPI plugin.
This tests the fuzzy matching for operation names.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from semantic_kernel_plugins.openapi_plugin_factory import OpenApiPluginFactory

def test_operation_lookup():
    """Test the operation lookup with fuzzy matching."""
    print("🔍 Testing OpenAPI Operation Lookup with Fuzzy Matching...")
    
    # Test configuration for APIs.guru - using inline spec for simplicity
    test_config = {
        'name': 'openapi_test',
        'base_url': 'https://api.apis.guru/v2',
        'openapi_spec_content': {
            'openapi': '3.0.0',
            'info': {'title': 'APIs.guru API', 'version': 'v2'},
            'paths': {
                '/list.json': {
                    'get': {
                        'operationId': 'listAPIs',
                        'summary': 'List all APIs',
                        'description': 'List all APIs in the directory'
                    }
                },
                '/metrics.json': {
                    'get': {
                        'operationId': 'getMetrics',
                        'summary': 'Get API metrics',
                        'description': 'Get metrics about the API directory'
                    }
                }
            }
        }
    }
    
    try:
        factory = OpenApiPluginFactory()
        plugin = factory.create_from_config(test_config)
        
        print("✅ Plugin created successfully")
        
        # Test 1: Exact operation name (should work)
        print("\n=== Test 1: Exact operation name 'getMetrics' ===")
        try:
            result = plugin.call_operation(operation_id='getMetrics')
            print(f"✅ Success with 'getMetrics': {type(result)} returned")
            if isinstance(result, dict):
                print(f"   Sample data: numAPIs={result.get('numAPIs', 'N/A')}, numProviders={result.get('numProviders', 'N/A')}")
        except Exception as e:
            print(f"❌ Failed with 'getMetrics': {e}")
        
        # Test 2: Wrong operation name that should be corrected (getAppMetrics -> getMetrics)
        print("\n=== Test 2: Fuzzy matching 'getAppMetrics' -> 'getMetrics' ===")
        try:
            result = plugin.call_operation(operation_id='getAppMetrics')
            print(f"✅ Success with fuzzy matching 'getAppMetrics': {type(result)} returned")
            if isinstance(result, dict):
                print(f"   Sample data: numAPIs={result.get('numAPIs', 'N/A')}, numProviders={result.get('numProviders', 'N/A')}")
        except Exception as e:
            print(f"❌ Failed with 'getAppMetrics': {e}")
        
        # Test 3: List available operations
        print("\n=== Test 3: List available operations ===")
        try:
            result = plugin.list_available_apis()
            print(f"✅ Available operations:\n{result}")
        except Exception as e:
            print(f"❌ Failed to list operations: {e}")
        
        # Test 4: Completely wrong operation name (should fail)
        print("\n=== Test 4: Invalid operation name 'nonExistentOperation' ===")
        try:
            result = plugin.call_operation(operation_id='nonExistentOperation')
            print(f"⚠️ Unexpected success with invalid operation: {result}")
        except Exception as e:
            print(f"✅ Expected failure with invalid operation: {e}")
            
    except Exception as e:
        print(f"❌ Plugin creation failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_operation_lookup()
