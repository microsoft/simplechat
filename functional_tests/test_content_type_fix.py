#!/usr/bin/env python3
"""Test the fixed content type handling in swagger wrapper."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'application', 'single_app'))

from flask import Flask, request
from swagger_wrapper import register_swagger_routes, extract_route_info

def test_content_type_fix():
    """Test that multipart/form-data is properly assigned in OpenAPI spec."""
    
    # Create test app with admin settings route
    app = Flask(__name__)
    app.config['VERSION'] = '0.230.044'
    
    @app.route('/admin/settings', methods=['POST'])
    def admin_settings():
        """Admin settings management endpoint"""
        form_data = request.form
        app_title = form_data.get('app_title', 'AI Chat Application')
        max_file_size_mb = int(form_data.get('max_file_size_mb', 16))
        enable_video_file_support = form_data.get('enable_video_file_support') == 'on'
        return 'Settings saved'

    @app.route('/api/chat', methods=['POST'])  
    def chat_endpoint():
        """Chat endpoint with JSON data"""
        data = request.get_json()
        message = data.get('message')
        conversation_id = data.get('conversation_id')
        return {'response': 'ok'}

    @app.route('/api/upload', methods=['POST'])
    def upload_endpoint():
        """File upload endpoint"""
        if 'file' not in request.files:
            return 'No file'
        file = request.files['file']
        user_id = request.form.get('user_id')
        return 'File uploaded'

    print("🔍 TESTING CONTENT TYPE FIX")
    print("=" * 50)
    
    with app.app_context():
        register_swagger_routes(app)
        
        # Extract the OpenAPI specification
        spec = extract_route_info(app)
        paths = spec.get('paths', {})
        
        # Test 1: Admin settings (should be multipart/form-data)
        admin_path = paths.get('/admin/settings', {})
        admin_post = admin_path.get('post', {})
        admin_request_body = admin_post.get('requestBody', {})
        admin_content = admin_request_body.get('content', {})
        
        print("1. Admin Settings Endpoint:")
        print(f"   Content types detected: {list(admin_content.keys())}")
        if 'multipart/form-data' in admin_content:
            schema = admin_content['multipart/form-data'].get('schema', {})
            properties = schema.get('properties', {})
            print(f"   ✅ SUCCESS: multipart/form-data detected with {len(properties)} fields")
            print(f"   Sample fields: {list(properties.keys())[:3]}")
        else:
            print("   ❌ FAILED: multipart/form-data not detected")
            print(f"   Available content types: {list(admin_content.keys())}")
        
        # Test 2: Chat endpoint (should be application/json) 
        chat_path = paths.get('/api/chat', {})
        chat_post = chat_path.get('post', {})
        chat_request_body = chat_post.get('requestBody', {})
        chat_content = chat_request_body.get('content', {})
        
        print("\\n2. Chat Endpoint:")
        print(f"   Content types detected: {list(chat_content.keys())}")
        if 'application/json' in chat_content:
            schema = chat_content['application/json'].get('schema', {})
            properties = schema.get('properties', {})
            print(f"   ✅ SUCCESS: application/json detected with {len(properties)} fields")
            print(f"   Sample fields: {list(properties.keys())}")
        else:
            print("   ❌ FAILED: application/json not detected")
        
        # Test 3: Upload endpoint (should be multipart/form-data)
        upload_path = paths.get('/api/upload', {})
        upload_post = upload_path.get('post', {})
        upload_request_body = upload_post.get('requestBody', {})
        upload_content = upload_request_body.get('content', {})
        
        print("\\n3. Upload Endpoint:")
        print(f"   Content types detected: {list(upload_content.keys())}")
        if 'multipart/form-data' in upload_content:
            schema = upload_content['multipart/form-data'].get('schema', {})
            properties = schema.get('properties', {})
            print(f"   ✅ SUCCESS: multipart/form-data detected with {len(properties)} fields")
            print(f"   Fields: {list(properties.keys())}")
        else:
            print("   ❌ FAILED: multipart/form-data not detected")
        
        print("\\n" + "=" * 50)
        print("🎯 SUMMARY:")
        print("The fix should now properly assign content types in the OpenAPI spec")
        print("instead of defaulting everything to application/json!")

if __name__ == "__main__":
    test_content_type_fix()