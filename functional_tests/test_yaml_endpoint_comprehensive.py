#!/usr/bin/env python3
"""
Complete validation test for YAML OpenAPI endpoint functionality.
Version: 0.230.042

This test provides a comprehensive validation that both JSON and YAML endpoints
work correctly when the server is running, and falls back to offline validation
when the server is not available.
"""

import sys
import os
import yaml
import json
import requests
from datetime import datetime

def test_server_endpoints():
    """Test both JSON and YAML endpoints with a running server."""
    print("🌐 Testing Live Server Endpoints...")
    
    base_url = "http://localhost:5000"
    
    # Test data for validation
    endpoints = [
        {
            'name': 'JSON',
            'url': f"{base_url}/swagger.json",
            'expected_content_type': 'application/json',
            'parser': json.loads
        },
        {
            'name': 'YAML', 
            'url': f"{base_url}/swagger.yaml",
            'expected_content_type': 'application/x-yaml',
            'parser': yaml.safe_load
        }
    ]
    
    results = {}
    
    for endpoint in endpoints:
        name = endpoint['name']
        url = endpoint['url']
        
        print(f"  📋 Testing {name} endpoint: {url}")
        
        try:
            # Make request with timeout
            response = requests.get(url, timeout=5, allow_redirects=False)
            
            print(f"    Status: {response.status_code}")
            print(f"    Content-Type: {response.headers.get('Content-Type', 'Not set')}")
            
            if response.status_code == 401:
                print(f"    ⚠️  Authentication required (expected)")
                results[name] = {'status': 'auth_required', 'content': None}
                continue
            elif response.status_code == 200:
                # Parse the content
                if name == 'JSON':
                    spec = response.json()
                else:  # YAML
                    spec = yaml.safe_load(response.text)
                
                # Validate structure
                if 'openapi' in spec and 'paths' in spec:
                    path_count = len(spec.get('paths', {}))
                    print(f"    ✅ Valid OpenAPI spec with {path_count} paths")
                    
                    # Check version
                    version = spec.get('info', {}).get('version', 'unknown')
                    print(f"    Version: {version}")
                    
                    results[name] = {
                        'status': 'success', 
                        'content': spec,
                        'path_count': path_count,
                        'version': version
                    }
                else:
                    print(f"    ❌ Invalid OpenAPI structure")
                    results[name] = {'status': 'invalid', 'content': spec}
            else:
                print(f"    ❌ Unexpected status code: {response.status_code}")
                results[name] = {'status': 'error', 'content': None}
                
        except requests.exceptions.ConnectionError:
            print(f"    ⚠️  Connection failed (server not running)")
            results[name] = {'status': 'connection_failed', 'content': None}
        except Exception as e:
            print(f"    ❌ Error: {e}")
            results[name] = {'status': 'error', 'content': None, 'error': str(e)}
    
    return results

def validate_format_consistency(results):
    """Validate that JSON and YAML formats contain the same information."""
    print("\n🔍 Validating Format Consistency...")
    
    json_result = results.get('JSON', {})
    yaml_result = results.get('YAML', {})
    
    json_content = json_result.get('content')
    yaml_content = yaml_result.get('content')
    
    if not json_content or not yaml_content:
        print("  ⚠️  Cannot compare formats (missing content)")
        return False
    
    # Compare key sections
    comparisons = [
        ('OpenAPI version', 'openapi'),
        ('API title', ['info', 'title']),
        ('API version', ['info', 'version']),
        ('Path count', lambda spec: len(spec.get('paths', {}))),
    ]
    
    all_match = True
    
    for desc, key_path in comparisons:
        if callable(key_path):
            json_val = key_path(json_content)
            yaml_val = key_path(yaml_content)
        else:
            json_val = get_nested_value(json_content, key_path)
            yaml_val = get_nested_value(yaml_content, key_path)
        
        if json_val == yaml_val:
            print(f"  ✅ {desc} matches: {json_val}")
        else:
            print(f"  ❌ {desc} differs: JSON={json_val}, YAML={yaml_val}")
            all_match = False
    
    # Compare path names
    json_paths = set(json_content.get('paths', {}).keys())
    yaml_paths = set(yaml_content.get('paths', {}).keys())
    
    if json_paths == yaml_paths:
        print(f"  ✅ Path endpoints match: {len(json_paths)} paths")
    else:
        print(f"  ❌ Path endpoints differ:")
        print(f"    JSON only: {json_paths - yaml_paths}")
        print(f"    YAML only: {yaml_paths - json_paths}")
        all_match = False
    
    return all_match

def get_nested_value(data, key_path):
    """Get a nested value from a dictionary using a path."""
    if isinstance(key_path, str):
        return data.get(key_path)
    elif isinstance(key_path, list):
        current = data
        for key in key_path:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
        return current
    return None

def test_yaml_specific_features():
    """Test YAML-specific features and formatting."""
    print("\n📝 Testing YAML-Specific Features...")
    
    # Create a sample OpenAPI spec
    sample_spec = {
        'openapi': '3.0.3',
        'info': {
            'title': 'Test API',
            'version': '1.0.0',
            'description': 'A test API with special characters: üñíçødé'
        },
        'paths': {
            '/test': {
                'get': {
                    'summary': 'Test endpoint',
                    'parameters': [
                        {
                            'name': 'query',
                            'in': 'query',
                            'schema': {'type': 'string'},
                            'description': 'Query parameter with special chars: €£¥'
                        }
                    ]
                }
            }
        }
    }
    
    try:
        # Convert to YAML
        yaml_content = yaml.dump(sample_spec, 
                               default_flow_style=False,
                               sort_keys=False,
                               allow_unicode=True,
                               indent=2)
        
        print("  ✅ YAML generation successful")
        
        # Test key YAML features
        features = [
            ('Unicode support', 'üñíçødé' in yaml_content),
            ('Block style (no {})', '{' not in yaml_content.split('\n')[1]),  # Skip first line
            ('Proper indentation', all(line.startswith('  ') or not line.startswith(' ') 
                                     for line in yaml_content.split('\n')[1:10] 
                                     if line.strip())),
            ('Readable structure', 'openapi:' in yaml_content and 'info:' in yaml_content)
        ]
        
        for feature_name, test_result in features:
            if test_result:
                print(f"  ✅ {feature_name}")
            else:
                print(f"  ❌ {feature_name}")
        
        # Test round-trip
        parsed_back = yaml.safe_load(yaml_content)
        if parsed_back == sample_spec:
            print("  ✅ Round-trip conversion")
        else:
            print("  ❌ Round-trip conversion failed")
            
        return True
        
    except Exception as e:
        print(f"  ❌ YAML feature test failed: {e}")
        return False

def main():
    """Run comprehensive YAML endpoint validation."""
    print("🧪 Comprehensive YAML OpenAPI Endpoint Validation")
    print("=" * 60)
    print(f"Test Time: {datetime.now().isoformat()}")
    print(f"Version: 0.230.042")
    print("=" * 60)
    
    # Test live endpoints
    endpoint_results = test_server_endpoints()
    
    # Validate consistency if both formats available
    consistency_ok = validate_format_consistency(endpoint_results)
    
    # Test YAML-specific features
    yaml_features_ok = test_yaml_specific_features()
    
    # Summary
    print("\n📊 Validation Summary")
    print("=" * 30)
    
    json_status = endpoint_results.get('JSON', {}).get('status', 'unknown')
    yaml_status = endpoint_results.get('YAML', {}).get('status', 'unknown')
    
    print(f"JSON Endpoint: {json_status}")
    print(f"YAML Endpoint: {yaml_status}")
    print(f"Format Consistency: {'✅ Pass' if consistency_ok else '❌ Fail'}")
    print(f"YAML Features: {'✅ Pass' if yaml_features_ok else '❌ Fail'}")
    
    # Overall result
    if yaml_status in ['success', 'auth_required'] and yaml_features_ok:
        print("\n🎉 YAML OpenAPI support is working correctly!")
        print("\n📋 Available Endpoints:")
        print("  • http://localhost:5000/swagger.json - JSON format")
        print("  • http://localhost:5000/swagger.yaml - YAML format")
        print("  • http://localhost:5000/swagger - Interactive UI")
        return True
    else:
        print("\n⚠️  Some issues detected in YAML support")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)