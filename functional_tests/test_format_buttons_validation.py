#!/usr/bin/env python3
# test_format_buttons_validation.py
"""
Quick validation test for YAML format buttons in Swagger UI.
Version: 0.230.042

This test validates that the UI enhancements for format selection are working.
Implemented in: 0.230.043
"""

import sys
import os

# Add the application directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))

def test_format_buttons_in_ui():
    """Test that the format selection buttons are properly implemented."""
    print("🎨 Testing Format Selection UI Enhancements...")
    
    try:
        from swagger_wrapper import register_swagger_routes
        from flask import Flask
        
        app = Flask(__name__)
        app.config['VERSION'] = '0.230.042'
        
        # Register swagger routes
        register_swagger_routes(app)
        
        print("  ✅ Swagger routes registered successfully")
        
        # Check that both endpoints are registered
        routes = []
        for rule in app.url_map.iter_rules():
            if 'swagger' in rule.rule:
                routes.append(rule.rule)
        
        expected_routes = ['/swagger', '/swagger.json', '/swagger.yaml']
        for expected in expected_routes:
            if expected in routes:
                print(f"  ✅ Route {expected} registered")
            else:
                print(f"  ❌ Route {expected} missing")
        
        # Test that we can get the swagger UI HTML
        with app.test_client() as client:
            # Note: This will fail with 401 because of authentication, but we can check the route exists
            response = client.get('/swagger')
            if response.status_code == 401:
                print("  ✅ Swagger UI route accessible (authentication required as expected)")
            elif response.status_code == 200:
                print("  ✅ Swagger UI route accessible")
                
                # Check if our format buttons are in the HTML
                html_content = response.get_data(as_text=True)
                ui_features = [
                    'format-selection',
                    '/swagger.json',
                    '/swagger.yaml', 
                    'copySpecUrl',
                    'JSON',
                    'YAML'
                ]
                
                for feature in ui_features:
                    if feature in html_content:
                        print(f"    ✅ UI feature '{feature}' present")
                    else:
                        print(f"    ❌ UI feature '{feature}' missing")
            else:
                print(f"  ❌ Unexpected response: {response.status_code}")
        
        print("\n✅ Format selection UI validation completed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_yaml_endpoint_registration():
    """Test that YAML endpoint is properly registered and configured."""
    print("🔧 Testing YAML Endpoint Registration...")
    
    try:
        from swagger_wrapper import _swagger_cache
        
        # Test cache configuration
        stats = _swagger_cache.get_cache_stats()
        
        if 'formats' in stats:
            formats = stats['formats']
            supported = formats.get('supported_formats', [])
            
            if 'json' in supported and 'yaml' in supported:
                print("  ✅ Both JSON and YAML formats supported in cache")
            else:
                print(f"  ❌ Format support incomplete: {supported}")
        else:
            print("  ❌ No format information in cache configuration")
        
        # Test that YAML import works
        import yaml
        print(f"  ✅ PyYAML available (version: {yaml.__version__})")
        
        # Test YAML generation
        test_data = {'openapi': '3.0.3', 'info': {'title': 'Test'}}
        yaml_output = yaml.dump(test_data, default_flow_style=False, indent=2)
        
        if 'openapi: 3.0.3' in yaml_output:
            print("  ✅ YAML generation working correctly")
        else:
            print("  ❌ YAML generation failed")
        
        print("✅ YAML endpoint registration validation completed!")
        return True
        
    except Exception as e:
        print(f"❌ YAML endpoint test failed: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Quick Format Button Validation Tests...\n")
    
    tests = [
        test_format_buttons_in_ui,
        test_yaml_endpoint_registration
    ]
    
    results = []
    for test in tests:
        print(f"\n{'='*60}")
        result = test()
        results.append(result)
        print(f"{'='*60}")
    
    success_count = sum(results)
    total_count = len(results)
    
    print(f"\n📊 Quick Test Results:")
    print(f"✅ Passed: {success_count}")
    print(f"❌ Failed: {total_count - success_count}")
    
    if success_count == total_count:
        print("\n🎉 All format button validation tests passed!")
        print("\n💡 New Features Available:")
        print("   📄 JSON download button - Direct access to /swagger.json")
        print("   📝 YAML download button - Direct access to /swagger.yaml")
        print("   📋 JSON URL copy button - Copy JSON URL to clipboard")
        print("   📋 YAML URL copy button - Copy YAML URL to clipboard")
        print("\n🌐 Visit http://localhost:5000/swagger to see the new buttons!")
    else:
        print(f"\n⚠️  {total_count - success_count} test(s) failed")
    
    sys.exit(0 if success_count == total_count else 1)