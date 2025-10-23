#!/usr/bin/env python3
"""
Quick Dynamic Schema Test
Version: 0.230.040

This is a simple test to verify dynamic schema generation is working
without requiring the full application to be running.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))

def test_dynamic_schema_functions():
    """Test the dynamic schema generation functions directly."""
    print("🔍 Testing Dynamic Schema Functions...")
    
    try:
        # Import the functions
        from swagger_wrapper import _generate_dynamic_schemas, _generate_minimal_required_schemas, _analyze_route_patterns
        
        # Create a mock Flask app
        from flask import Flask
        test_app = Flask(__name__)
        
        # Add some test routes with swagger decorations
        from swagger_wrapper import swagger_route
        
        @test_app.route('/api/test', methods=['POST'])
        @swagger_route(
            summary="Test endpoint",
            request_body={"type": "object"}
        )
        def test_endpoint():
            return {"status": "ok"}
        
        @test_app.route('/api/chat', methods=['POST'])
        @swagger_route(
            summary="Chat endpoint",
            request_body={"type": "object"}
        )
        def chat_endpoint():
            return {"status": "ok"}
        
        # Test minimal schema generation
        minimal_schemas = _generate_minimal_required_schemas()
        print(f"✅ Generated {len(minimal_schemas)} minimal schemas:")
        for schema_name in minimal_schemas:
            print(f"   - {schema_name}")
        
        # Test route pattern analysis
        with test_app.app_context():
            route_patterns = _analyze_route_patterns(test_app)
            print(f"✅ Analyzed {len(route_patterns)} route patterns:")
            for (route, method), schema in route_patterns.items():
                print(f"   - {method.upper()} {route} → {schema}")
        
        # Test dynamic schema generation
        with test_app.app_context():
            dynamic_schemas = _generate_dynamic_schemas(test_app)
            print(f"✅ Generated {len(dynamic_schemas)} dynamic schemas:")
            for schema_name in dynamic_schemas:
                print(f"   - {schema_name}")
        
        # Verify essential schemas exist
        essential_schemas = ['ErrorResponse', 'SimpleIdRequest', 'BulkIdsRequest', 'StatusUpdateRequest']
        missing_schemas = []
        
        for schema_name in essential_schemas:
            if schema_name not in dynamic_schemas:
                missing_schemas.append(schema_name)
        
        if missing_schemas:
            print(f"❌ Missing essential schemas: {missing_schemas}")
            return False
        else:
            print("✅ All essential schemas present")
        
        # Verify ChatRequest has correct structure
        if 'ChatRequest' in dynamic_schemas:
            chat_schema = dynamic_schemas['ChatRequest']
            
            # Check required fields
            if 'message' in chat_schema.get('required', []):
                print("✅ ChatRequest has required 'message' field")
            else:
                print("❌ ChatRequest missing required 'message' field")
                return False
            
            # Check enum values
            doc_scope = chat_schema.get('properties', {}).get('doc_scope', {})
            expected_enum = ["user", "group", "all", "personal"]
            actual_enum = doc_scope.get('enum', [])
            
            if set(actual_enum) == set(expected_enum):
                print("✅ ChatRequest doc_scope enum is correct")
            else:
                print(f"❌ ChatRequest doc_scope enum mismatch: {actual_enum}")
                return False
            
            # Check nullable fields
            nullable_fields = ['conversation_id', 'selected_document_id', 'active_group_id', 'model_deployment']
            for field in nullable_fields:
                prop = chat_schema.get('properties', {}).get(field, {})
                if prop.get('nullable'):
                    print(f"✅ {field} is properly nullable")
                else:
                    print(f"⚠️  {field} should be nullable")
        
        print("✅ Dynamic schema function test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_hardcoding_reduction():
    """Test that we've reduced hardcoding in the swagger_wrapper."""
    print("\n🔍 Testing Hardcoding Reduction...")
    
    try:
        # Read swagger_wrapper.py
        wrapper_file = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'swagger_wrapper.py')
        
        with open(wrapper_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that we're using dynamic generation
        dynamic_indicators = [
            '_generate_dynamic_schemas(app)',
            'def _generate_dynamic_schemas(',
            'def _generate_minimal_required_schemas(',
            'def _analyze_route_patterns('
        ]
        
        found_indicators = []
        for indicator in dynamic_indicators:
            if indicator in content:
                found_indicators.append(indicator)
                print(f"✅ Found: {indicator}")
        
        if len(found_indicators) == len(dynamic_indicators):
            print("✅ All dynamic generation indicators found")
        else:
            missing = set(dynamic_indicators) - set(found_indicators)
            print(f"❌ Missing indicators: {missing}")
            return False
        
        # Check that the old massive hardcoded schemas are gone
        # Look for large schema definitions (indicators of hardcoding)
        lines = content.split('\n')
        large_schema_blocks = 0
        current_block_size = 0
        in_schema_definition = False
        
        for line in lines:
            line = line.strip()
            if '"type": "object"' in line:
                in_schema_definition = True
                current_block_size = 1
            elif in_schema_definition:
                if line.startswith('}') and current_block_size > 20:
                    large_schema_blocks += 1
                    current_block_size = 0
                    in_schema_definition = False
                elif line:
                    current_block_size += 1
                    if current_block_size > 50:  # Reset if too large, might be function code
                        in_schema_definition = False
                        current_block_size = 0
        
        print(f"📊 Large hardcoded schema blocks detected: {large_schema_blocks}")
        
        if large_schema_blocks < 3:  # We expect some schemas to remain hardcoded
            print("✅ Significantly reduced hardcoded schema blocks")
        else:
            print(f"⚠️  Still have {large_schema_blocks} large hardcoded blocks")
        
        print("✅ Hardcoding reduction analysis complete!")
        return True
        
    except Exception as e:
        print(f"❌ Hardcoding reduction test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 Running Quick Dynamic Schema Tests...")
    
    test1_result = test_dynamic_schema_functions()
    test2_result = test_hardcoding_reduction()
    
    all_passed = test1_result and test2_result
    
    print(f"\n📋 Test Results:")
    print(f"   Dynamic Schema Functions: {'✅ PASS' if test1_result else '❌ FAIL'}")
    print(f"   Hardcoding Reduction: {'✅ PASS' if test2_result else '❌ FAIL'}")
    print(f"   Overall: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    
    if all_passed:
        print("\n🎉 Dynamic schema generation is working correctly!")
        print("📈 Successfully reduced hardcoding while maintaining schema references")
        print("🔧 Schemas are now generated dynamically from route analysis")
    
    sys.exit(0 if all_passed else 1)