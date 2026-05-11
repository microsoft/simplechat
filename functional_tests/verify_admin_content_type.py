#!/usr/bin/env python3
"""Verify that the admin settings route uses multipart/form-data correctly."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'application', 'single_app'))

from flask import Flask
from swagger_wrapper import _analyze_function_request_body, extract_route_info
from route_frontend_admin_settings import register_route_frontend_admin_settings

def test_admin_settings_content_type():
    """Test the actual admin settings route content type detection."""
    
    # Create app and register the actual route
    app = Flask(__name__)
    app.config['VERSION'] = '0.230.044'
    
    # Register the actual admin settings route
    register_route_frontend_admin_settings(app)
    
    print("🔍 VERIFYING ADMIN SETTINGS ROUTE CONTENT TYPE")
    print("=" * 60)
    
    # Find the admin_settings function
    admin_func = None
    route_rule = None
    
    for rule in app.url_map.iter_rules():
        if '/admin/settings' in rule.rule and 'POST' in rule.methods:
            admin_func = app.view_functions[rule.endpoint]
            route_rule = rule
            break
    
    if not admin_func:
        print("❌ Could not find admin settings function")
        return
    
    print(f"✅ Found admin settings function: {admin_func.__name__}")
    print(f"Route: {route_rule.rule}")
    print(f"Methods: {list(route_rule.methods)}")
    print(f"Has swagger decorator: {hasattr(admin_func, '_swagger_doc')}")
    
    # 1. Check what the function actually uses in its code
    print("\n📋 CODE ANALYSIS:")
    import inspect
    try:
        source = inspect.getsource(admin_func)
        uses_form = 'request.form' in source or 'form_data.get(' in source
        uses_json = 'request.get_json()' in source or 'get_json()' in source
        print(f"   Uses form data: {uses_form}")
        print(f"   Uses JSON data: {uses_json}")
        
        # Count form_data.get() occurrences
        form_get_count = source.count('form_data.get(')
        print(f"   form_data.get() calls: {form_get_count}")
        
    except Exception as e:
        print(f"   Could not analyze source: {e}")
    
    # 2. Test the swagger wrapper analysis
    print("\n🔧 SWAGGER WRAPPER ANALYSIS:")
    result = _analyze_function_request_body(admin_func)
    
    if result:
        print("   ✅ SUCCESS: Request body schema detected!")
        content = result.get('content', {})
        print(f"   Content types: {list(content.keys())}")
        
        for content_type, schema_info in content.items():
            schema = schema_info.get('schema', {})
            properties = schema.get('properties', {})
            required = schema.get('required', [])
            
            print(f"\n   📋 {content_type}:")
            print(f"      Properties: {len(properties)} fields detected")
            print(f"      Required: {len(required)} fields")
            print(f"      Description: {schema.get('description', 'N/A')}")
            
            # Show first 5 fields as examples
            field_examples = list(properties.items())[:5]
            for field, field_def in field_examples:
                field_type = field_def.get('type', 'unknown')
                desc = field_def.get('description', 'No description')[:30]
                nullable = ' (nullable)' if field_def.get('nullable') else ''
                print(f"      • {field}: {field_type}{nullable} - {desc}")
            
            if len(properties) > 5:
                print(f"      ... and {len(properties) - 5} more fields")
    else:
        print("   ❌ FAILED: No request body schema detected")
    
    # 3. Test the complete OpenAPI spec generation
    print("\n🎯 FULL OPENAPI SPEC ANALYSIS:")
    
    with app.app_context():
        try:
            spec = extract_route_info(app)
            paths = spec.get('paths', {})
            admin_path = paths.get('/admin/settings', {})
            post_spec = admin_path.get('post', {})
            request_body = post_spec.get('requestBody', {})
            content = request_body.get('content', {})
            
            print(f"   OpenAPI paths found: {len(paths)}")
            print(f"   Admin settings POST found: {'post' in admin_path}")
            print(f"   Request body content types: {list(content.keys())}")
            
            if content:
                for content_type, schema_info in content.items():
                    schema = schema_info.get('schema', {})
                    properties = schema.get('properties', {})
                    print(f"   {content_type}: {len(properties)} properties")
            
        except Exception as e:
            print(f"   Error generating OpenAPI spec: {e}")
    
    print("\n" + "=" * 60)
    print("🎯 CONCLUSION:")
    
    # Expected behavior
    print("\n📝 EXPECTED BEHAVIOR:")
    print("   • HTML form uses: enctype='multipart/form-data'")
    print("   • Python code uses: request.form and form_data.get()")
    print("   • Swagger should detect: multipart/form-data")
    print("   • OpenAPI spec should show: multipart/form-data content type")
    
    # Actual verification
    if result and 'multipart/form-data' in result.get('content', {}):
        print("\n✅ SUCCESS: Everything is working correctly!")
        print("   The swagger wrapper properly detected multipart/form-data")
        print("   This matches the actual HTML form enctype and Python code usage")
    elif result and 'application/x-www-form-urlencoded' in result.get('content', {}):
        print("\n⚠️  PARTIAL: Detected form data but as URL-encoded instead of multipart")
        print("   This might be due to file upload detection logic")
    else:
        print("\n❌ ISSUE: The swagger wrapper is not detecting the correct content type")

if __name__ == "__main__":
    test_admin_settings_content_type()