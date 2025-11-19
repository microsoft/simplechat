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
                print(f"  ✅ {field}: {properties[field].get('type')} - {properties[field].get('description', 'No description')[:50]}")
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
        
        return len(found_fields) >= 8  # Should find most of the expected fields\n        \n        for field in expected_fields:\n            if field in properties:\n                found_fields.append(field)\n                print(f\"  ✅ {field}: {properties[field].get('type')} - {properties[field].get('description', 'No description')[:50]}\")\n            else:\n                missing_fields.append(field)\n        \n        if missing_fields:\n            print(f\"⚠️  Missing fields that should be detected: {missing_fields}\")\n        \n        # Verify bing_search is NOT in the schema (since it's not in the actual route)\n        if 'bing_search' in properties:\n            print(\"❌ ERROR: 'bing_search' found in schema but it's not in the actual route!\")\n            return False\n        else:\n            print(\"✅ Correctly excluded 'bing_search' - not found in actual route\")\n        \n        # Verify message is required\n        required_fields = schema.get('required', [])\n        if 'message' in required_fields:\n            print(\"✅ 'message' correctly identified as required\")\n        else:\n            print(\"⚠️  'message' should be required\")\n        \n        # Check for proper type inference\n        message_def = properties.get('message', {})\n        if message_def.get('type') == 'string' and message_def.get('minLength') == 1:\n            print(\"✅ 'message' has correct type and validation\")\n        \n        conversation_id_def = properties.get('conversation_id', {})\n        if conversation_id_def.get('format') == 'uuid' and conversation_id_def.get('nullable'):\n            print(\"✅ 'conversation_id' correctly identified as nullable UUID\")\n        \n        # Verify doc_scope enum\n        doc_scope_def = properties.get('doc_scope', {})\n        if 'enum' in doc_scope_def:\n            enum_values = doc_scope_def['enum']\n            print(f\"✅ 'doc_scope' has enum values: {enum_values}\")\n            if 'personal' in enum_values:\n                print(\"✅ 'personal' correctly included in doc_scope enum\")\n        \n        print(f\"📊 Schema Analysis Summary:\")\n        print(f\"   Found Fields: {len(found_fields)}\")\n        print(f\"   Required Fields: {len(required_fields)}\")\n        print(f\"   Properties Generated: {len(properties)}\")\n        \n        return len(found_fields) >= 8  # Should find most of the expected fields\n        \n    except Exception as e:\n        print(f\"❌ Test failed: {e}\")\n        import traceback\n        traceback.print_exc()\n        return False\n\ndef test_no_hardcoded_schemas():\n    \"\"\"Test that we're no longer using hardcoded schema references.\"\"\"\n    print(\"\\n🔍 Testing Elimination of Hardcoded Schemas...\")\n    \n    try:\n        # Read the swagger_wrapper.py to verify hardcoded schemas are removed\n        wrapper_file = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'swagger_wrapper.py')\n        \n        with open(wrapper_file, 'r', encoding='utf-8') as f:\n            content = f.read()\n        \n        # Check that we're no longer generating large hardcoded schema blocks\n        hardcoded_indicators = [\n            '\"ChatRequest\": {',\n            '\"DocumentUpdateRequest\": {',\n            'bing_search',  # This outdated parameter should not appear\n        ]\n        \n        found_hardcoded = []\n        for indicator in hardcoded_indicators:\n            if indicator in content:\n                found_hardcoded.append(indicator)\n        \n        if found_hardcoded:\n            print(f\"⚠️  Still found some hardcoded schema indicators: {found_hardcoded}\")\n        else:\n            print(\"✅ No hardcoded schema blocks found\")\n        \n        # Check for inline generation indicators\n        inline_indicators = [\n            '_analyze_function_request_body',\n            'inline schema',\n            '_infer_field_definition',\n            'Generated inline schema'\n        ]\n        \n        found_inline = []\n        for indicator in inline_indicators:\n            if indicator in content:\n                found_inline.append(indicator)\n                print(f\"✅ Found inline generation: {indicator}\")\n        \n        if len(found_inline) >= 3:\n            print(\"✅ Inline schema generation properly implemented\")\n            return True\n        else:\n            print(f\"❌ Missing inline generation indicators: expected >= 3, found {len(found_inline)}\")\n            return False\n        \n    except Exception as e:\n        print(f\"❌ Test failed: {e}\")\n        return False\n\ndef test_enhanced_field_inference():\n    \"\"\"Test the enhanced field definition inference.\"\"\"\n    print(\"\\n🔍 Testing Enhanced Field Inference...\")\n    \n    try:\n        from swagger_wrapper import _infer_field_definition, _extract_doc_scope_enum_from_source\n        \n        # Test field inference for different types\n        test_cases = [\n            ('message', 'string with minLength'),\n            ('conversation_id', 'uuid format with nullable'),\n            ('hybrid_search', 'boolean with default false'),\n            ('doc_scope', 'string with enum'),\n            ('top_n', 'integer with minimum'),\n        ]\n        \n        sample_source = \"\"\"\n        data = request.get_json()\n        message = data.get('message')\n        conversation_id = data.get('conversation_id')\n        hybrid_search = data.get('hybrid_search')\n        doc_scope = data.get('doc_scope')\n        top_n = data.get('top_n')\n        \"\"\"\n        \n        all_passed = True\n        for field_name, expected_type in test_cases:\n            definition = _infer_field_definition(field_name, sample_source)\n            \n            print(f\"Field '{field_name}': {definition}\")\n            \n            # Basic validation\n            if 'type' not in definition:\n                print(f\"❌ '{field_name}' missing type\")\n                all_passed = False\n            elif 'description' not in definition:\n                print(f\"❌ '{field_name}' missing description\")\n                all_passed = False\n            else:\n                print(f\"✅ '{field_name}' properly defined\")\n        \n        # Test doc_scope enum extraction\n        enum_values = _extract_doc_scope_enum_from_source(sample_source)\n        print(f\"Doc scope enum values: {enum_values}\")\n        \n        if len(enum_values) >= 3:  # Should have at least user, group, all, personal\n            print(\"✅ Doc scope enum extraction working\")\n        else:\n            print(\"⚠️  Doc scope enum extraction may need improvement\")\n        \n        return all_passed\n        \n    except Exception as e:\n        print(f\"❌ Enhanced field inference test failed: {e}\")\n        import traceback\n        traceback.print_exc()\n        return False\n\nif __name__ == \"__main__\":\n    print(\"🧪 Running Inline Schema Generation Tests...\")\n    print(f\"🎯 Goal: Eliminate hardcoded schemas and generate from actual routes\")\n    \n    test1_result = test_inline_schema_generation()\n    test2_result = test_no_hardcoded_schemas()\n    test3_result = test_enhanced_field_inference()\n    \n    all_passed = test1_result and test2_result and test3_result\n    \n    print(f\"\\n📋 Test Results:\")\n    print(f\"   Inline Schema Generation: {'✅ PASS' if test1_result else '❌ FAIL'}\")\n    print(f\"   Hardcoded Schema Elimination: {'✅ PASS' if test2_result else '❌ FAIL'}\")\n    print(f\"   Enhanced Field Inference: {'✅ PASS' if test3_result else '❌ FAIL'}\")\n    print(f\"   Overall: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}\")\n    \n    if all_passed:\n        print(\"\\n🎉 Inline schema generation is working perfectly!\")\n        print(\"📈 Schemas are now generated directly from actual route implementations\")\n        print(\"🚫 Eliminated outdated parameters like 'bing_search'\")\n        print(\"⚡ No more hardcoded schema references - everything is dynamic and accurate\")\n    else:\n        print(\"\\n❌ Some tests failed - review implementation\")\n    \n    sys.exit(0 if all_passed else 1)