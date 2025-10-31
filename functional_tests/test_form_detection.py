#!/usr/bin/env python3
"""Test script for form data detection in swagger_wrapper."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'application', 'single_app'))

# Mock request for testing
class MockRequest:
    form = {}

request = MockRequest()

from swagger_wrapper import _analyze_function_request_body

def test_admin_form():
    """Admin settings form endpoint"""
    form_data = request.form
    app_title = form_data.get('app_title', 'AI Chat Application')  
    max_file_size_mb = int(form_data.get('max_file_size_mb', 16))
    enable_video_file_support = form_data.get('enable_video_file_support') == 'on'
    document_classification_categories_json = form_data.get('document_classification_categories_json', '[]')
    return 'Settings updated'

def test_json_endpoint():
    """JSON endpoint for comparison"""
    data = request.get_json()
    message = data.get('message')
    conversation_id = data.get('conversation_id')
    return {'response': 'ok'}

def test_file_upload():
    """File upload endpoint"""
    if 'file' not in request.files:
        return 'No file'
    file = request.files['file']
    user_id = request.form.get('user_id')
    return 'File uploaded'

print("🔍 Testing Form Data Detection in Swagger Wrapper")
print("=" * 60)

# Test 1: Admin form with form_data.get() patterns
print("\n1. Testing admin form endpoint:")
result1 = _analyze_function_request_body(test_admin_form)
if result1:
    print("✅ SUCCESS: Form data detected!")
    content = result1.get('content', {})
    print(f"   Content types: {list(content.keys())}")
    
    for content_type, schema_info in content.items():
        print(f"\n   📋 {content_type}:")
        schema = schema_info.get('schema', {})
        properties = schema.get('properties', {})
        required = schema.get('required', [])
        
        print(f"      Description: {schema.get('description', 'N/A')}")
        print(f"      Required fields: {required if required else 'None'}")
        print("      Properties:")
        for field, field_def in properties.items():
            field_type = field_def.get('type', 'unknown')  
            desc = field_def.get('description', 'No description')
            nullable = ' (nullable)' if field_def.get('nullable') else ''
            print(f"        • {field}: {field_type}{nullable} - {desc}")
else:
    print("❌ FAILED: No form data schema generated")

# Test 2: JSON endpoint for comparison  
print("\n2. Testing JSON endpoint:")
result2 = _analyze_function_request_body(test_json_endpoint)
if result2:
    print("✅ SUCCESS: JSON data detected!")
    content = result2.get('content', {})
    print(f"   Content types: {list(content.keys())}")
else:
    print("❌ FAILED: No JSON schema generated")

# Test 3: File upload endpoint
print("\n3. Testing file upload endpoint:")
result3 = _analyze_function_request_body(test_file_upload)
if result3:
    print("✅ SUCCESS: File upload detected!")
    content = result3.get('content', {})
    print(f"   Content types: {list(content.keys())}")
    
    for content_type, schema_info in content.items():
        print(f"\n   📋 {content_type}:")
        schema = schema_info.get('schema', {})
        properties = schema.get('properties', {})
        print("      Properties:")
        for field, field_def in properties.items():
            field_type = field_def.get('type', 'unknown')
            field_format = field_def.get('format', '')
            format_str = f" (format: {field_format})" if field_format else ""
            desc = field_def.get('description', 'No description')
            print(f"        • {field}: {field_type}{format_str} - {desc}")
else:
    print("❌ FAILED: No file upload schema generated")

print("\n" + "=" * 60)
print("🎯 CONCLUSION:")
print("The enhanced swagger wrapper should now detect:")
print("   • Form data fields (application/x-www-form-urlencoded)")  
print("   • JSON request bodies (application/json)")
print("   • File uploads (multipart/form-data)")
print("   • Proper field types and descriptions based on naming patterns")