#!/usr/bin/env python3
"""
Functional test for automatic query parameter detection in Swagger wrapper.
Version: 0.234.211
Implemented in: 0.234.211

This test ensures that the swagger_wrapper automatically detects query parameters
from request.args.get() calls in the function source code and includes them in
the OpenAPI specification.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_query_parameter_detection():
    """Test that query parameters are automatically detected from request.args.get() calls."""
    print("🔍 Testing Automatic Query Parameter Detection...")
    
    try:
        from flask import Flask, request
        from swagger_wrapper import swagger_route, _analyze_function_parameters
        
        # Create a test function with various query parameter patterns
        def test_endpoint():
            """
            Test endpoint with query parameters.
            Query Parameters:
                page (int): The page number to retrieve (default: 1).
                page_size (int): The number of items per page (default: 10).
                status (str): Filter by status.
                search (str): Search term.
            """
            page = int(request.args.get('page', 1))
            page_size = int(request.args.get('page_size', 10))
            status = request.args.get('status', None)
            search = str(request.args.get('search', ''))
            enabled = bool(request.args.get('enabled', False))
            return {}
        
        # Analyze the function
        print("\n📊 Analyzing function for query parameters...")
        parameters = _analyze_function_parameters(test_endpoint)
        
        print(f"\n✅ Found {len(parameters)} parameters")
        
        # Check that query parameters were detected
        query_params = [p for p in parameters if p.get('in') == 'query']
        print(f"   Query parameters found: {len(query_params)}")
        
        expected_params = {
            'page': {'type': 'integer', 'default': 1},
            'page_size': {'type': 'integer', 'default': 10},
            'status': {'type': 'string'},
            'search': {'type': 'string', 'default': ''},
            'enabled': {'type': 'boolean', 'default': False}
        }
        
        found_params = {p['name']: p for p in query_params}
        
        # Verify each expected parameter
        all_found = True
        for param_name, expected_schema in expected_params.items():
            if param_name in found_params:
                found_param = found_params[param_name]
                print(f"\n   ✅ {param_name}:")
                print(f"      - Type: {found_param['schema']['type']} (expected: {expected_schema['type']})")
                if 'default' in expected_schema:
                    print(f"      - Default: {found_param['schema'].get('default')} (expected: {expected_schema['default']})")
                print(f"      - Description: {found_param.get('description', 'N/A')}")
                print(f"      - Required: {found_param.get('required', False)}")
                
                # Verify type matches
                if found_param['schema']['type'] != expected_schema['type']:
                    print(f"      ❌ Type mismatch!")
                    all_found = False
            else:
                print(f"\n   ❌ {param_name}: NOT FOUND")
                all_found = False
        
        if all_found:
            print(f"\n✅ All query parameters correctly detected and typed!")
            return True
        else:
            print(f"\n❌ Some parameters were missing or incorrectly typed")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_safety_logs_endpoint():
    """Test that the actual /api/safety/logs endpoint has parameters detected."""
    print("\n\n🔍 Testing Real Safety Logs Endpoint Parameter Detection...")
    
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))
        
        from flask import Flask
        from swagger_wrapper import swagger_route, extract_route_info, get_auth_security
        from route_backend_safety import register_route_backend_safety
        
        # Create a minimal Flask app
        app = Flask(__name__)
        app.config['VERSION'] = '0.234.211'
        app.config['SECRET_KEY'] = 'test-secret-key'
        
        # Register the safety routes
        register_route_backend_safety(app)
        
        # Extract route info to generate OpenAPI spec
        print("\n📊 Generating OpenAPI spec...")
        with app.app_context():
            openapi_spec = extract_route_info(app)
        
        # Find the /api/safety/logs endpoint
        safety_logs_path = '/api/safety/logs'
        if safety_logs_path in openapi_spec['paths']:
            endpoint = openapi_spec['paths'][safety_logs_path]
            if 'get' in endpoint:
                get_operation = endpoint['get']
                parameters = get_operation.get('parameters', [])
                
                print(f"\n✅ Found {len(parameters)} parameters for GET /api/safety/logs")
                
                expected_params = ['page', 'page_size', 'status', 'action']
                found_param_names = [p['name'] for p in parameters if p.get('in') == 'query']
                
                print(f"\n   Expected query parameters: {expected_params}")
                print(f"   Found query parameters: {found_param_names}")
                
                all_found = True
                for expected in expected_params:
                    if expected in found_param_names:
                        param = next(p for p in parameters if p['name'] == expected)
                        print(f"\n   ✅ {expected}:")
                        print(f"      - Type: {param['schema']['type']}")
                        print(f"      - Default: {param['schema'].get('default', 'N/A')}")
                        print(f"      - Description: {param.get('description', 'N/A')}")
                        print(f"      - Required: {param.get('required', False)}")
                    else:
                        print(f"\n   ❌ {expected}: NOT FOUND in OpenAPI spec")
                        all_found = False
                
                if all_found:
                    print(f"\n✅ All expected query parameters are now in the OpenAPI spec!")
                    print(f"   This will prevent 'illegal parameter' violations from WAF/API gateways.")
                    return True
                else:
                    print(f"\n❌ Some expected parameters are still missing from spec")
                    return False
            else:
                print(f"❌ GET method not found for {safety_logs_path}")
                return False
        else:
            print(f"❌ Path {safety_logs_path} not found in OpenAPI spec")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 70)
    print("AUTOMATIC QUERY PARAMETER DETECTION TEST")
    print("=" * 70)
    
    results = []
    
    # Test 1: Basic query parameter detection
    results.append(test_query_parameter_detection())
    
    # Test 2: Real endpoint verification
    results.append(test_safety_logs_endpoint())
    
    # Summary
    print("\n" + "=" * 70)
    print(f"📊 Test Results: {sum(results)}/{len(results)} tests passed")
    print("=" * 70)
    
    sys.exit(0 if all(results) else 1)
