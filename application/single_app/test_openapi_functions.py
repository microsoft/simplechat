import os
import sys
sys.path.append('.')

# Set up logging first
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

from semantic_kernel_plugins.openapi_plugin_factory import OpenApiPluginFactory

# Create a test plugin to see what's being loaded
try:
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
    
    factory = OpenApiPluginFactory()
    plugin = factory.create_from_config(test_config)
    
    print("=== Testing listAPIs function ===")
    
    # Test the listAPIs function directly
    if hasattr(plugin, 'listAPIs'):
        result = plugin.listAPIs()
        print(f"listAPIs result: {result}")
    
    print("\n=== Testing getMetrics function ===")
    
    # Test the getMetrics function directly
    if hasattr(plugin, 'getMetrics'):
        result = plugin.getMetrics()
        print(f"getMetrics result: {result}")
    
    print("\n=== Testing through kernel plugin ===")
    
    # Test through the kernel plugin
    kernel_plugin = plugin.get_kernel_plugin()
    listAPIs_func = kernel_plugin.functions.get('listAPIs')
    if listAPIs_func:
        print("Found listAPIs function in kernel plugin")
        # Note: We'd need a kernel context to actually invoke it, but we can see the metadata
        print(f"Function metadata: {listAPIs_func.metadata}")
    
except Exception as e:
    print(f'Error: {e}')
    import traceback
    traceback.print_exc()
