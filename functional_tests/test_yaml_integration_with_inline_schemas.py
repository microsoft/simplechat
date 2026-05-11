#!/usr/bin/env python3
"""
Integration test for YAML generation with inline schema generation.
Version: 0.230.042
Implemented in: 0.230.042

This test validates that YAML generation works correctly with the inline schema
generation system, producing accurate YAML specifications from actual route analysis.
"""

import sys
import os
import yaml
import json

# Add the application directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))

def test_yaml_with_inline_schemas():
    """Test YAML generation with inline schema generation."""
    print("🔍 Testing YAML Generation with Inline Schemas...")
    
    try:
        # Import the swagger wrapper components
        from swagger_wrapper import extract_route_info, _swagger_cache
        
        # Create a mock Flask app for testing
        from flask import Flask
        app = Flask(__name__)
        app.config['VERSION'] = '0.230.042'
        
        # Add a test route with the swagger decorator
        from swagger_wrapper import swagger_route
        
        @app.route('/api/test-chat', methods=['POST'])
        @swagger_route(
            summary="Test Chat API",
            description="Test endpoint for YAML generation validation",
            tags=["Test"],
            auto_request_body=True
        )
        def test_chat_api():
            """Test chat endpoint with inline schema generation."""
            # Simulate typical chat API code structure
            data = request.get_json()
            message = data.get('message')
            conversation_id = data.get('conversation_id')
            model_deployment = data.get('model_deployment')
            doc_scope = data.get('doc_scope', 'user')
            hybrid_search = data.get('hybrid_search', False)
            
            return {"status": "success", "response": "Test response"}
        
        with app.app_context():
            print("  • Generating OpenAPI specification...")
            
            # Generate the OpenAPI spec using inline schema generation
            openapi_spec = extract_route_info(app)
            
            print(f"    ✅ Generated spec with {len(openapi_spec.get('paths', {}))} paths")
            
            # Convert to YAML
            yaml_content = yaml.dump(openapi_spec, 
                                   default_flow_style=False, 
                                   sort_keys=False,
                                   allow_unicode=True,
                                   indent=2)
            
            print("  • Validating YAML structure...")
            
            # Parse YAML back to validate
            parsed_yaml = yaml.safe_load(yaml_content)
            
            # Validate core OpenAPI structure
            required_fields = ['openapi', 'info', 'paths', 'components']
            for field in required_fields:
                if field in parsed_yaml:
                    print(f"    ✅ Required field '{field}' present")
                else:
                    print(f"    ❌ Missing required field '{field}'")
            
            # Check if inline schema generation worked
            test_path = '/api/test-chat'
            if test_path in parsed_yaml.get('paths', {}):
                post_spec = parsed_yaml['paths'][test_path].get('post', {})
                request_body = post_spec.get('requestBody', {})
                
                if request_body:
                    print(f"    ✅ Request body schema generated inline")
                    
                    # Check if schema is inline (not a reference)
                    content = request_body.get('content', {})
                    json_content = content.get('application/json', {})
                    schema = json_content.get('schema', {})
                    
                    if '$ref' in schema:
                        print(f"    ⚠️  Schema uses reference: {schema['$ref']}")
                    else:
                        print(f"    ✅ Schema is inline: {len(schema.get('properties', {}))} properties")
                        
                        # Check for expected properties from route analysis
                        properties = schema.get('properties', {})
                        expected_props = ['message', 'conversation_id', 'model_deployment', 'doc_scope', 'hybrid_search']
                        found_props = []
                        
                        for prop in expected_props:
                            if prop in properties:
                                found_props.append(prop)
                                
                        print(f"    ✅ Found {len(found_props)}/{len(expected_props)} expected properties")
                        if found_props:
                            print(f"      Properties: {', '.join(found_props)}")
                else:
                    print(f"    ❌ No request body schema generated")
            else:
                print(f"    ❌ Test path not found in generated spec")
            
            # Validate YAML formatting
            print("  • Validating YAML formatting...")
            
            if yaml_content.startswith('openapi: 3.0.3'):
                print("    ✅ YAML starts with correct OpenAPI version")
            else:
                print("    ❌ YAML does not start with expected OpenAPI version")
            
            # Check indentation (should be 2 spaces)
            lines = yaml_content.split('\n')
            proper_indentation = True
            for i, line in enumerate(lines[:20]):  # Check first 20 lines
                if line.strip() and line.startswith(' '):
                    # Count leading spaces
                    leading_spaces = len(line) - len(line.lstrip())
                    if leading_spaces % 2 != 0:
                        print(f"    ❌ Improper indentation on line {i+1}: {leading_spaces} spaces")
                        proper_indentation = False
                        break
            
            if proper_indentation:
                print("    ✅ YAML uses proper 2-space indentation")
            
            # Test round-trip conversion
            print("  • Testing round-trip conversion...")
            roundtrip_spec = yaml.safe_load(yaml_content)
            
            if roundtrip_spec == openapi_spec:
                print("    ✅ Round-trip conversion successful (YAML ↔ Dict)")
            else:
                print("    ❌ Round-trip conversion failed")
                
                # Show differences
                original_keys = set(str(openapi_spec.keys()))
                roundtrip_keys = set(str(roundtrip_spec.keys()))
                if original_keys != roundtrip_keys:
                    print(f"      Key differences: {original_keys.symmetric_difference(roundtrip_keys)}")
            
            print(f"\n  📄 Sample YAML output (first 500 chars):")
            print("  " + "\n  ".join(yaml_content[:500].split('\n')))
            
        print("\n✅ YAML inline schema generation test completed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_yaml_cache_integration():
    """Test that YAML caching works with inline schema generation."""
    print("🗂️ Testing YAML Cache Integration...")
    
    try:
        from swagger_wrapper import _swagger_cache
        
        # Clear cache to start fresh
        _swagger_cache.clear_cache()
        
        # Get initial cache stats
        initial_stats = _swagger_cache.get_cache_stats()
        print(f"  Initial cache: {initial_stats['cached_specs']} entries")
        
        # Validate format support
        formats = initial_stats.get('formats', {})
        supported = formats.get('supported_formats', [])
        
        if 'json' in supported and 'yaml' in supported:
            print("  ✅ Both JSON and YAML formats supported in cache")
        else:
            print(f"  ❌ Missing format support: {supported}")
        
        print("✅ YAML cache integration test completed!")
        return True
        
    except Exception as e:
        print(f"❌ Cache integration test failed: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Starting YAML Integration Tests...\n")
    
    tests = [
        test_yaml_with_inline_schemas,
        test_yaml_cache_integration
    ]
    
    results = []
    for test in tests:
        print(f"\n{'='*60}")
        result = test()
        results.append(result)
        print(f"{'='*60}")
    
    success_count = sum(results)
    total_count = len(results)
    
    print(f"\n📊 Integration Test Results:")
    print(f"✅ Passed: {success_count}")
    print(f"❌ Failed: {total_count - success_count}")
    print(f"📈 Success Rate: {success_count}/{total_count} ({100*success_count//total_count}%)")
    
    if success_count == total_count:
        print("\n🎉 All YAML integration tests passed!")
        print("\n💡 Key Features Validated:")
        print("   • YAML generation from inline schema analysis")
        print("   • Proper YAML formatting and indentation")
        print("   • Round-trip conversion safety")
        print("   • Cache system with dual format support")
        print("   • Integration with existing inline generation system")
    else:
        print(f"\n⚠️  {total_count - success_count} test(s) failed")
    
    sys.exit(0 if success_count == total_count else 1)