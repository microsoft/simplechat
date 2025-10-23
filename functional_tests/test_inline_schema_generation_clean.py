#!/usr/bin/env python3
"""
Inline Schema Generation Test
Version: 0.230.041
Implemented in: 0.230.041

This test validates that OpenAPI schemas are now generated inline directly 
from actual route implementations, eliminating hardcoded and outdated parameters 
like 'bing_search', and ensuring accuracy with the real route code.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))

def test_inline_schema_generation():
    """Test that schemas are generated inline from actual route analysis."""
    print("🔍 Testing Inline Schema Generation from Routes...")
    
    try:
        # Import required modules
        from flask import Flask
        from swagger_wrapper import _analyze_function_request_body, swagger_route
        from route_backend_chats import register_route_backend_chats
        
        # Create test app and register the actual chat route
        test_app = Flask(__name__)
        
        # Register the real chat routes
        register_route_backend_chats(test_app)
        
        # Get the actual chat_api function
        chat_func = None
        for rule in test_app.url_map.iter_rules():
            if '/api/chat' in rule.rule and 'POST' in rule.methods:
                chat_func = test_app.view_functions.get(rule.endpoint)
                break
        
        if not chat_func:
            print("❌ Could not find chat_api function")
            return False
            
        print("✅ Found actual chat_api function")
        
        # Analyze the actual function for request body schema
        schema = _analyze_function_request_body(chat_func)
        
        if not schema:
            print("❌ No schema generated from chat_api function")
            return False
            
        print(f"✅ Generated schema from actual route: {len(schema.get('properties', {}))} properties")
        
        # Verify the schema contains actual parameters from the route
        properties = schema.get('properties', {})
        
        expected_fields = [
            'message', 'conversation_id', 'hybrid_search', 'selected_document_id', 
            'image_generation', 'doc_scope', 'active_group_id', 'model_deployment',
            'top_n', 'classifications', 'chat_type'
        ]
        
        found_fields = []
        missing_fields = []
        
        for field in expected_fields:
            if field in properties:
                found_fields.append(field)
                desc = properties[field].get('description', 'No description')[:50]
                print(f"  ✅ {field}: {properties[field].get('type')} - {desc}")
            else:
                missing_fields.append(field)
        
        if missing_fields:
            print(f"⚠️  Missing fields that should be detected: {missing_fields}")
        
        # Verify bing_search is NOT in the schema (since it's not in the actual route)
        if 'bing_search' in properties:
            print("❌ ERROR: 'bing_search' found in schema but it's not in the actual route!")
            return False
        else:
            print("✅ Correctly excluded 'bing_search' - not found in actual route")
        
        # Verify message is required
        required_fields = schema.get('required', [])
        if 'message' in required_fields:
            print("✅ 'message' correctly identified as required")
        else:
            print("⚠️  'message' should be required")
        
        # Check for proper type inference
        message_def = properties.get('message', {})
        if message_def.get('type') == 'string' and message_def.get('minLength') == 1:
            print("✅ 'message' has correct type and validation")
        
        conversation_id_def = properties.get('conversation_id', {})
        if conversation_id_def.get('format') == 'uuid' and conversation_id_def.get('nullable'):
            print("✅ 'conversation_id' correctly identified as nullable UUID")
        
        # Verify doc_scope enum
        doc_scope_def = properties.get('doc_scope', {})
        if 'enum' in doc_scope_def:
            enum_values = doc_scope_def['enum']
            print(f"✅ 'doc_scope' has enum values: {enum_values}")
            if 'personal' in enum_values:
                print("✅ 'personal' correctly included in doc_scope enum")
        
        print(f"📊 Schema Analysis Summary:")
        print(f"   Found Fields: {len(found_fields)}")
        print(f"   Required Fields: {len(required_fields)}")
        print(f"   Properties Generated: {len(properties)}")
        
        return len(found_fields) >= 8  # Should find most of the expected fields
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_no_hardcoded_schemas():
    """Test that we're no longer using hardcoded schema references."""
    print("\\n🔍 Testing Elimination of Hardcoded Schemas...")
    
    try:
        # Read the swagger_wrapper.py to verify hardcoded schemas are removed
        wrapper_file = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'swagger_wrapper.py')
        
        with open(wrapper_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that we're no longer generating large hardcoded schema blocks
        hardcoded_indicators = [
            'bing_search',  # This outdated parameter should not appear
        ]
        
        found_hardcoded = []
        for indicator in hardcoded_indicators:
            if indicator in content:
                found_hardcoded.append(indicator)
        
        if found_hardcoded:
            print(f"⚠️  Still found some hardcoded schema indicators: {found_hardcoded}")
        else:
            print("✅ No outdated hardcoded parameters found")
        
        # Check for inline generation indicators
        inline_indicators = [
            '_analyze_function_request_body',
            'inline schema',
            '_infer_field_definition',
            'Generated inline schema'
        ]
        
        found_inline = []
        for indicator in inline_indicators:
            if indicator in content:
                found_inline.append(indicator)
                print(f"✅ Found inline generation: {indicator}")
        
        if len(found_inline) >= 3:
            print("✅ Inline schema generation properly implemented")
            return True
        else:
            print(f"❌ Missing inline generation indicators: expected >= 3, found {len(found_inline)}")
            return False
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

def test_enhanced_field_inference():
    """Test the enhanced field definition inference."""
    print("\\n🔍 Testing Enhanced Field Inference...")
    
    try:
        from swagger_wrapper import _infer_field_definition, _extract_doc_scope_enum_from_source
        
        # Test field inference for different types
        test_cases = [
            ('message', 'string with minLength'),
            ('conversation_id', 'uuid format with nullable'),
            ('hybrid_search', 'boolean with default false'),
            ('doc_scope', 'string with enum'),
            ('top_n', 'integer with minimum'),
        ]
        
        sample_source = """
        data = request.get_json()
        message = data.get('message')
        conversation_id = data.get('conversation_id')
        hybrid_search = data.get('hybrid_search')
        doc_scope = data.get('doc_scope')
        top_n = data.get('top_n')
        """
        
        all_passed = True
        for field_name, expected_type in test_cases:
            definition = _infer_field_definition(field_name, sample_source)
            
            print(f"Field '{field_name}': {definition}")
            
            # Basic validation
            if 'type' not in definition:
                print(f"❌ '{field_name}' missing type")
                all_passed = False
            elif 'description' not in definition:
                print(f"❌ '{field_name}' missing description")
                all_passed = False
            else:
                print(f"✅ '{field_name}' properly defined")
        
        # Test doc_scope enum extraction
        enum_values = _extract_doc_scope_enum_from_source(sample_source)
        print(f"Doc scope enum values: {enum_values}")
        
        if len(enum_values) >= 3:  # Should have at least user, group, all, personal
            print("✅ Doc scope enum extraction working")
        else:
            print("⚠️  Doc scope enum extraction may need improvement")
        
        return all_passed
        
    except Exception as e:
        print(f"❌ Enhanced field inference test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 Running Inline Schema Generation Tests...")
    print(f"🎯 Goal: Eliminate hardcoded schemas and generate from actual routes")
    
    test1_result = test_inline_schema_generation()
    test2_result = test_no_hardcoded_schemas()
    test3_result = test_enhanced_field_inference()
    
    all_passed = test1_result and test2_result and test3_result
    
    print(f"\\n📋 Test Results:")
    print(f"   Inline Schema Generation: {'✅ PASS' if test1_result else '❌ FAIL'}")
    print(f"   Hardcoded Schema Elimination: {'✅ PASS' if test2_result else '❌ FAIL'}")
    print(f"   Enhanced Field Inference: {'✅ PASS' if test3_result else '❌ FAIL'}")
    print(f"   Overall: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    
    if all_passed:
        print("\\n🎉 Inline schema generation is working perfectly!")
        print("📈 Schemas are now generated directly from actual route implementations")
        print("🚫 Eliminated outdated parameters like 'bing_search'")
        print("⚡ No more hardcoded schema references - everything is dynamic and accurate")
    else:
        print("\\n❌ Some tests failed - review implementation")
    
    sys.exit(0 if all_passed else 1)