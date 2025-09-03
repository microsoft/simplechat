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
    
    print(f'Plugin created: {plugin}')
    print(f'Plugin type: {type(plugin)}')
    print(f'Has get_kernel_plugin: {hasattr(plugin, "get_kernel_plugin")}')
    
    # Check what methods exist on the plugin
    print(f'Plugin methods: {[m for m in dir(plugin) if not m.startswith("_")]}')
    
    # Try getting the kernel plugin
    if hasattr(plugin, 'get_kernel_plugin'):
        kernel_plugin = plugin.get_kernel_plugin()
        print(f'Kernel plugin: {kernel_plugin}')
        print(f'Functions in plugin: {list(kernel_plugin.functions.keys())}')
        
        # Check if we have the expected functions
        for func_name in ['listAPIs', 'getMetrics']:
            if hasattr(plugin, func_name):
                print(f'Plugin has method: {func_name}')
            else:
                print(f'Plugin missing method: {func_name}')
    
except Exception as e:
    print(f'Error: {e}')
    import traceback
    traceback.print_exc()
