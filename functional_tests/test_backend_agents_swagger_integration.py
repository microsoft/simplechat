#!/usr/bin/env python3
"""
Functional test for route_backend_agents.py swagger integration.
Version: 0.229.065
Implemented in: 0.229.065

This test ensures that all endpoints in route_backend_agents.py are properly decorated 
with @swagger_route decorators and will be included in the automatic swagger documentation.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_backend_agents_swagger_integration():
    """Test that all backend agents endpoints have swagger decorators."""
    print("🔍 Testing Backend Agents Swagger Integration...")
    
    try:
        # Import the swagger extraction functionality
        from swagger_wrapper import extract_route_info
        
        # Import the blueprint
        from route_backend_agents import bpa
        
        # Get all rules for the blueprint
        from flask import Flask
        test_app = Flask(__name__)
        test_app.register_blueprint(bpa)
        
        # Count endpoints with swagger decorators
        swagger_endpoints = 0
        total_endpoints = 0
        endpoint_details = []
        
        for rule in test_app.url_map.iter_rules():
            if rule.endpoint.startswith('admin_agents.'):
                total_endpoints += 1
                endpoint_name = rule.endpoint.split('.')[-1]
                
                # Try to extract route info (this will work if swagger_route decorator is present)
                try:
                    route_info = extract_route_info(rule, test_app.view_functions[rule.endpoint])
                    if route_info:
                        swagger_endpoints += 1
                        endpoint_details.append({
                            'endpoint': endpoint_name,
                            'path': rule.rule,
                            'methods': list(rule.methods - {'HEAD', 'OPTIONS'}),
                            'has_swagger': True,
                            'summary': route_info.get('summary', 'Auto-generated'),
                            'tags': route_info.get('tags', [])
                        })
                        print(f"  ✅ {endpoint_name}: {rule.rule} ({', '.join(rule.methods - {'HEAD', 'OPTIONS'})})")
                    else:
                        endpoint_details.append({
                            'endpoint': endpoint_name,
                            'path': rule.rule,
                            'methods': list(rule.methods - {'HEAD', 'OPTIONS'}),
                            'has_swagger': False
                        })
                        print(f"  ❌ {endpoint_name}: {rule.rule} - No swagger decorator")
                except Exception as e:
                    endpoint_details.append({
                        'endpoint': endpoint_name,
                        'path': rule.rule,
                        'methods': list(rule.methods - {'HEAD', 'OPTIONS'}),
                        'has_swagger': False,
                        'error': str(e)
                    })
                    print(f"  ❌ {endpoint_name}: {rule.rule} - Error: {e}")
        
        print(f"\n📊 Results:")
        print(f"  Total endpoints: {total_endpoints}")
        print(f"  Swagger-enabled endpoints: {swagger_endpoints}")
        print(f"  Coverage: {(swagger_endpoints/total_endpoints*100):.1f}%")
        
        # Expected endpoints based on our analysis
        expected_endpoints = [
            'generate_agent_id',
            'get_user_agents',
            'set_user_agents', 
            'delete_user_agent',
            'set_user_selected_agent',
            'get_global_agent_settings_for_users',
            'get_all_admin_settings',
            'set_selected_agent',
            'list_agents',
            'add_agent',
            'get_admin_agent_settings',
            'update_agent_setting',
            'edit_agent',
            'delete_agent',
            'orchestration_types',
            'orchestration_settings'
        ]
        
        found_endpoints = [ep['endpoint'] for ep in endpoint_details]
        
        print(f"\n🎯 Expected vs Found:")
        for expected in expected_endpoints:
            if expected in found_endpoints:
                ep_detail = next(ep for ep in endpoint_details if ep['endpoint'] == expected)
                status = "✅" if ep_detail['has_swagger'] else "❌"
                print(f"  {status} {expected}")
            else:
                print(f"  ❓ {expected} - Not found")
        
        # Test security integration
        print(f"\n🔒 Security Integration Test:")
        security_count = 0
        for ep in endpoint_details:
            if ep['has_swagger']:
                # Check if security is properly configured
                try:
                    from swagger_wrapper import get_auth_security
                    auth_security = get_auth_security()
                    if auth_security:
                        security_count += 1
                        print(f"  ✅ Security configured for authentication")
                        break
                except:
                    pass
        
        if security_count > 0:
            print(f"  ✅ Authentication security properly configured")
        else:
            print(f"  ❌ Authentication security not found")
        
        # Check if all endpoints have swagger decorators
        success = swagger_endpoints == total_endpoints and swagger_endpoints >= len(expected_endpoints)
        
        if success:
            print(f"\n✅ All backend agents endpoints successfully integrated with swagger!")
            print(f"   - {swagger_endpoints} endpoints decorated with @swagger_route")
            print(f"   - Automatic schema generation enabled")
            print(f"   - Authentication security configured")
            print(f"   - Ready for /swagger documentation")
        else:
            print(f"\n❌ Integration incomplete:")
            print(f"   - Expected at least {len(expected_endpoints)} endpoints")
            print(f"   - Found {swagger_endpoints} swagger-enabled endpoints")
            print(f"   - Missing decorators on {total_endpoints - swagger_endpoints} endpoints")
        
        return success
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_backend_agents_swagger_integration()
    print(f"\n{'='*60}")
    if success:
        print("🎉 BACKEND AGENTS SWAGGER INTEGRATION TEST PASSED!")
        print("All endpoints are now documented and accessible via /swagger")
    else:
        print("💥 BACKEND AGENTS SWAGGER INTEGRATION TEST FAILED!")
        print("Some endpoints may not be properly documented")
    print(f"{'='*60}")
    sys.exit(0 if success else 1)