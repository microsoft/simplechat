# test_semantic_kernel_operation_consistency.py
"""
Comprehensive test to verify that Semantic Kernel operations work consistently.
This addresses the intermittent failure issue where getAppMetrics would sometimes fail.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from semantic_kernel_plugins.openapi_plugin_factory import OpenApiPluginFactory
import time

def test_operation_consistency():
    """Test that operations work consistently, even with fuzzy name matching."""
    print("🔄 Testing Semantic Kernel Operation Consistency...")
    
    # Configuration for a test plugin with common operation naming patterns
    test_config = {
        'name': 'openapi_test',
        'base_url': 'https://api.apis.guru/v2',
        'openapi_spec_content': {
            'openapi': '3.0.0',
            'info': {
                'title': 'APIs.guru API',
                'version': 'v2',
                'description': 'Wikipedia for Web APIs. Repository of API definitions in OpenAPI format.'
            },
            'paths': {
                '/list.json': {
                    'get': {
                        'operationId': 'listAPIs',
                        'summary': 'List all APIs',
                        'description': 'Returns links to the OpenAPI definitions for each API in the directory. If API exist in multiple versions `preferred` one is explicitly marked. Some basic info from the OpenAPI definition is cached inside each object.'
                    }
                },
                '/metrics.json': {
                    'get': {
                        'operationId': 'getMetrics',
                        'summary': 'Get API metrics',
                        'description': 'Some basic metrics for the entire directory. Just stunning numbers to put on a front page and are intended purely for WoW effect :)'
                    }
                },
                '/providers': {
                    'get': {
                        'operationId': 'getProviders',
                        'summary': 'List providers',
                        'description': 'List all the providers in the directory'
                    }
                }
            }
        }
    }
    
    try:
        factory = OpenApiPluginFactory()
        plugin = factory.create_from_config(test_config)
        
        print("✅ Plugin created successfully")
        
        # Test exact operation names multiple times to ensure consistency
        exact_tests = [
            ('getMetrics', 'Get API metrics'),
            ('listAPIs', 'List all APIs'),
            ('getProviders', 'List providers')
        ]
        
        print("\n=== Testing Exact Operation Names (5 iterations each) ===")
        for operation_id, description in exact_tests:
            print(f"\n🎯 Testing '{operation_id}' - {description}")
            success_count = 0
            for i in range(5):
                try:
                    start_time = time.time()
                    result = plugin.call_operation(operation_id=operation_id)
                    duration = time.time() - start_time
                    success_count += 1
                    print(f"  ✅ Attempt {i+1}: Success ({duration:.2f}s)")
                except Exception as e:
                    print(f"  ❌ Attempt {i+1}: Failed - {e}")
            
            consistency_rate = (success_count / 5) * 100
            print(f"  📊 Consistency Rate: {consistency_rate}% ({success_count}/5)")
        
        # Test fuzzy matching variations
        fuzzy_tests = [
            ('getAppMetrics', 'getMetrics', 'Common App prefix variation'),
            ('getMetricsApp', 'getMetrics', 'Common App suffix variation'),
            ('listAPIs', 'listAPIs', 'Exact match test'),
            ('listAllAPIs', 'listAPIs', 'Extended name variation'),
            ('getapismetrics', 'getMetrics', 'Case insensitive test'),
        ]
        
        print("\n=== Testing Fuzzy Matching (3 iterations each) ===")
        for fuzzy_name, expected_match, description in fuzzy_tests:
            print(f"\n🔍 Testing '{fuzzy_name}' -> '{expected_match}' - {description}")
            success_count = 0
            for i in range(3):
                try:
                    start_time = time.time()
                    result = plugin.call_operation(operation_id=fuzzy_name)
                    duration = time.time() - start_time
                    success_count += 1
                    print(f"  ✅ Attempt {i+1}: Success ({duration:.2f}s)")
                except Exception as e:
                    print(f"  ❌ Attempt {i+1}: Failed - {e}")
            
            consistency_rate = (success_count / 3) * 100
            print(f"  📊 Consistency Rate: {consistency_rate}% ({success_count}/3)")
        
        # Test list_available_apis for agent guidance
        print("\n=== Testing Operation Discovery ===")
        try:
            operations_list = plugin.list_available_apis()
            print("✅ Successfully retrieved operations list:")
            # Extract key parts for verification
            if "getMetrics" in operations_list and "listAPIs" in operations_list:
                print("  ✅ All expected operations are listed")
                print("  ✅ Operations include descriptions and guidance")
            else:
                print("  ⚠️ Some expected operations missing from list")
            
            # Show a preview of the guidance provided to agents
            print(f"\n📋 Agent Guidance Preview:")
            lines = operations_list.split('\n')[:10]  # First 10 lines
            for line in lines:
                if line.strip():
                    print(f"  {line}")
            if len(operations_list.split('\n')) > 10:
                print("  ...")
                
        except Exception as e:
            print(f"❌ Failed to get operations list: {e}")
        
        # Test invalid operation handling
        print("\n=== Testing Error Handling ===")
        invalid_operations = ['invalidOp', 'getWrongMetrics', 'notAnOperation']
        for invalid_op in invalid_operations:
            try:
                result = plugin.call_operation(operation_id=invalid_op)
                print(f"  ⚠️ Unexpected success with '{invalid_op}': {result}")
            except Exception as e:
                print(f"  ✅ Expected failure with '{invalid_op}': {str(e)[:100]}...")
        
        print("\n🎉 Consistency Test Complete!")
        print("📈 Summary:")
        print("  - Exact operation names should have 100% consistency")
        print("  - Fuzzy matching should handle common variations")
        print("  - Invalid operations should fail gracefully")
        print("  - Operation discovery provides clear guidance to agents")
        
    except Exception as e:
        print(f"❌ Test setup failed: {e}")
        import traceback
        traceback.print_exc()

def test_agent_guidance():
    """Test the enhanced agent guidance system."""
    print("\n🤖 Testing Agent Guidance Improvements...")
    
    test_config = {
        'name': 'openapi_test',
        'base_url': 'https://api.apis.guru/v2',
        'openapi_spec_content': {
            'openapi': '3.0.0',
            'info': {
                'title': 'APIs.guru API',
                'version': 'v2',
                'description': 'Wikipedia for Web APIs.'
            },
            'paths': {
                '/metrics.json': {
                    'get': {
                        'operationId': 'getMetrics',
                        'summary': 'Get API metrics',
                        'description': 'Get comprehensive metrics for the API directory'
                    }
                }
            }
        }
    }
    
    try:
        factory = OpenApiPluginFactory()
        plugin = factory.create_from_config(test_config)
        
        # Test the enhanced list_available_apis function
        operations_guide = plugin.list_available_apis()
        
        print("📖 Enhanced Agent Guidance:")
        print(operations_guide)
        
        # Verify key guidance elements
        guidance_checks = [
            ("**getMetrics**", "Operation names are highlighted"),
            ("Use this for API directory metrics", "Specific usage guidance provided"),
            ("Use exact operation names", "Clear instruction about naming"),
            ("'getMetrics' not 'getAppMetrics'", "Common mistake prevention"),
        ]
        
        print("\n✅ Guidance Quality Checks:")
        for check_text, check_description in guidance_checks:
            if check_text in operations_guide:
                print(f"  ✅ {check_description}")
            else:
                print(f"  ❌ Missing: {check_description}")
        
    except Exception as e:
        print(f"❌ Agent guidance test failed: {e}")

if __name__ == "__main__":
    test_operation_consistency()
    test_agent_guidance()
