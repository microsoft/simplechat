#!/usr/bin/env python3
"""Debug AST parsing for form data detection."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'application', 'single_app'))

from flask import request
from swagger_wrapper import _analyze_function_request_body

def test_explicit_form_function():
    """This function uses form data explicitly"""
    form_data = request.form
    app_title = form_data.get('app_title')
    max_size = form_data.get('max_file_size_mb') 
    enable_video = form_data.get('enable_video_file_support')
    classification_json = form_data.get('document_classification_categories_json')
    return 'success'

def test_json_function():
    """This function uses JSON data"""
    data = request.get_json()
    message = data.get('message')
    conversation_id = data.get('conversation_id')
    return {'status': 'ok'}

def test_file_upload_function():
    """This function handles file uploads"""
    if 'file' not in request.files:
        return 'No file'
    file = request.files['file']
    user_id = request.form.get('user_id')
    workspace_id = request.form.get('workspace_id')
    return 'File uploaded'

print("🔍 DEBUGGING AST PARSING FOR FORM DATA DETECTION")
print("=" * 60)

# Test 1: Form data function
print("1. Testing form data function:")
form_result = _analyze_function_request_body(test_explicit_form_function)
if form_result:
    print("   ✅ SUCCESS: Form data detected")
    content = form_result.get('content', {})
    print(f"   Content types: {list(content.keys())}")
    
    for content_type, schema_info in content.items():
        schema = schema_info.get('schema', {})
        properties = schema.get('properties', {})
        print(f"   {content_type}: {len(properties)} properties")
        for field, field_def in properties.items():
            field_type = field_def.get('type', 'unknown')
            desc = field_def.get('description', '')[:30]
            print(f"     • {field}: {field_type} - {desc}")
else:
    print("   ❌ FAILED: No form data detected")

# Test 2: JSON function  
print("\\n2. Testing JSON function:")
json_result = _analyze_function_request_body(test_json_function)
if json_result:
    print("   ✅ SUCCESS: JSON data detected")
    content = json_result.get('content', {})
    print(f"   Content types: {list(content.keys())}")
else:
    print("   ❌ FAILED: No JSON data detected")

# Test 3: File upload function
print("\\n3. Testing file upload function:")
upload_result = _analyze_function_request_body(test_file_upload_function)
if upload_result:
    print("   ✅ SUCCESS: File upload detected")
    content = upload_result.get('content', {})
    print(f"   Content types: {list(content.keys())}")
else:
    print("   ❌ FAILED: No file upload detected")

print("\\n" + "=" * 60)
if any([form_result, json_result, upload_result]):
    print("🎯 CONCLUSION: AST parsing is working - the issue is elsewhere!")
else:
    print("🚨 PROBLEM: AST parsing is not detecting any patterns - need to debug further")