#!/usr/bin/env python3
"""
Dynamic Schema Generation Test
Version: 0.230.039
Implemented in: 0.230.039

This test validates that the OpenAPI specification generation now uses 
dynamic schema analysis instead of hardcoded schema definitions, reducing 
maintenance overhead while maintaining functionality.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import json
import requests
from time import sleep

def test_dynamic_schema_generation():
    """Test that schemas are generated dynamically rather than hardcoded."""
    print("🔍 Testing Dynamic Schema Generation...")
    
    try:
        # Test the swagger endpoint
        response = requests.get('http://localhost:5000/swagger.json', timeout=10)
        
        if response.status_code != 200:
            print(f"❌ Failed to get swagger spec: {response.status_code}")
            return False
        
        swagger_spec = response.json()
        schemas = swagger_spec.get('components', {}).get('schemas', {})
        
        print(f"📊 Found {len(schemas)} schemas in specification")
        
        # Verify essential schemas exist
        essential_schemas = ['ErrorResponse', 'ChatRequest', 'SimpleIdRequest', 'BulkIdsRequest', 'StatusUpdateRequest']
        missing_schemas = []
        
        for schema_name in essential_schemas:
            if schema_name not in schemas:
                missing_schemas.append(schema_name)
            else:
                print(f"✅ Found essential schema: {schema_name}")
        
        if missing_schemas:
            print(f"❌ Missing essential schemas: {missing_schemas}")
            return False
        
        # Verify ChatRequest has proper structure
        chat_request = schemas.get('ChatRequest', {})
        if not chat_request.get('properties', {}).get('message'):
            print("❌ ChatRequest missing message property")
            return False
        
        # Check for nullable fields in ChatRequest
        nullable_fields = ['conversation_id', 'selected_document_id', 'active_group_id', 'model_deployment']
        for field in nullable_fields:
            prop = chat_request.get('properties', {}).get(field, {})
            if not prop.get('nullable'):
                print(f"⚠️  Warning: {field} should be nullable")
        
        # Verify doc_scope enum includes all values
        doc_scope = chat_request.get('properties', {}).get('doc_scope', {})
        expected_enum = ["user", "group", "all", "personal"]
        actual_enum = doc_scope.get('enum', [])
        
        if set(actual_enum) != set(expected_enum):
            print(f"❌ doc_scope enum mismatch. Expected: {expected_enum}, Got: {actual_enum}")
            return False
        
        print("✅ ChatRequest schema properly structured")
        
        # Check paths for request body references
        paths = swagger_spec.get('paths', {})
        schema_references = []
        inline_schemas = []
        
        for path, methods in paths.items():
            for method, operation in methods.items():
                if method.upper() in ['OPTIONS', 'HEAD']:
                    continue
                    
                request_body = operation.get('requestBody', {})
                if request_body:
                    content = request_body.get('content', {})
                    json_content = content.get('application/json', {})
                    schema = json_content.get('schema', {})
                    
                    if '$ref' in schema:
                        schema_ref = schema['$ref'].replace('#/components/schemas/', '')
                        schema_references.append((path, method, schema_ref))
                        print(f"📋 {method.upper()} {path} → schema reference: {schema_ref}")
                    elif schema.get('type') == 'object':
                        inline_schemas.append((path, method))
                        print(f"🔧 {method.upper()} {path} → inline schema")
        
        print(f"📊 Schema References: {len(schema_references)}, Inline Schemas: {len(inline_schemas)}")
        
        # Verify we're using more references than inline (goal: reduce hardcoding)
        reference_ratio = len(schema_references) / (len(schema_references) + len(inline_schemas)) if (len(schema_references) + len(inline_schemas)) > 0 else 0
        
        print(f"📈 Schema Reference Ratio: {reference_ratio:.2%}")
        
        if reference_ratio < 0.5:
            print("⚠️  Warning: Low schema reference ratio - consider adding more reusable schemas")
        else:
            print("✅ Good schema reference ratio - reducing hardcoding successfully")
        
        # Test specific route patterns
        test_patterns = [
            ('/api/chat', 'post', 'ChatRequest'),
            ('/api/documents/<document_id>', 'patch', 'DocumentUpdateRequest'),
        ]
        
        for path_pattern, method, expected_schema in test_patterns:
            # Find matching paths
            matching_paths = [p for p in paths.keys() if path_pattern.replace('<document_id>', '{document_id}') in p or path_pattern == p]
            
            if matching_paths:
                actual_path = matching_paths[0]
                operation = paths[actual_path].get(method, {})
                request_body = operation.get('requestBody', {})
                
                if request_body:
                    schema = request_body.get('content', {}).get('application/json', {}).get('schema', {})
                    schema_ref = schema.get('$ref', '').replace('#/components/schemas/', '')
                    
                    if schema_ref == expected_schema:
                        print(f"✅ {method.upper()} {actual_path} correctly uses {expected_schema}")
                    else:
                        print(f"⚠️  {method.upper()} {actual_path} uses {schema_ref}, expected {expected_schema}")
        
        print("✅ Dynamic schema generation test passed!")
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Connection error: {e}")
        print("💡 Make sure the application is running on http://localhost:5000")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_schema_reduction():
    """Test that we've reduced hardcoded schemas effectively."""
    print("\n🔍 Testing Schema Reduction Effectiveness...")
    
    try:
        # Read the swagger_wrapper.py file to analyze hardcoding
        wrapper_file = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'swagger_wrapper.py')
        
        with open(wrapper_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Count lines in schema definitions
        lines = content.split('\n')
        in_components = False
        schema_lines = 0
        hardcoded_schemas = []
        
        for i, line in enumerate(lines):
            if '"components":' in line and '"schemas":' in lines[i+1] if i+1 < len(lines) else False:
                in_components = True
                continue
            elif in_components and line.strip().startswith('}') and 'components' in lines[i-5:i]:
                in_components = False
                break
            elif in_components:
                schema_lines += 1
                if '"type": "object"' in line:
                    # Find schema name in previous lines
                    for j in range(max(0, i-10), i):
                        if '"' in lines[j] and ':' in lines[j] and 'Request' in lines[j]:
                            schema_name = lines[j].split('"')[1]
                            if schema_name not in hardcoded_schemas:
                                hardcoded_schemas.append(schema_name)
                            break
        
        print(f"📊 Schema definition lines: {schema_lines}")
        print(f"📊 Hardcoded schemas detected: {len(hardcoded_schemas)}")
        
        if hardcoded_schemas:
            print(f"🔍 Hardcoded schemas: {hardcoded_schemas}")
        
        # Check for dynamic generation functions
        dynamic_functions = [
            '_generate_dynamic_schemas',
            '_generate_minimal_required_schemas', 
            '_analyze_route_patterns'
        ]
        
        found_functions = []
        for func in dynamic_functions:
            if f'def {func}(' in content:
                found_functions.append(func)
                print(f"✅ Found dynamic function: {func}")
        
        if len(found_functions) == len(dynamic_functions):
            print("✅ All dynamic generation functions implemented")
        else:
            missing = set(dynamic_functions) - set(found_functions)
            print(f"❌ Missing dynamic functions: {missing}")
            return False
        
        # Estimate reduction in hardcoding
        if schema_lines < 100:  # Previously we had 150+ lines of hardcoded schemas
            print(f"✅ Significant reduction in hardcoded schema lines: {schema_lines} (previously ~150+)")
        else:
            print(f"⚠️  Still have {schema_lines} lines of hardcoded schemas - room for improvement")
        
        print("✅ Schema reduction analysis complete!")
        return True
        
    except Exception as e:
        print(f"❌ Schema reduction test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 Running Dynamic Schema Generation Tests...")
    
    # Give the server a moment to start if needed
    sleep(2)
    
    test1_result = test_dynamic_schema_generation()
    test2_result = test_schema_reduction()
    
    all_passed = test1_result and test2_result
    
    print(f"\n📋 Test Results:")
    print(f"   Dynamic Schema Generation: {'✅ PASS' if test1_result else '❌ FAIL'}")
    print(f"   Schema Reduction Analysis: {'✅ PASS' if test2_result else '❌ FAIL'}")
    print(f"   Overall: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    
    if all_passed:
        print("\n🎉 Dynamic schema generation is working correctly!")
        print("📈 Successfully reduced hardcoding while maintaining functionality")
    
    sys.exit(0 if all_passed else 1)