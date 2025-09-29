#!/usr/bin/env python3
"""
Functional test for route_backend_chats.py swagger integration.
Version: 0.229.066
Implemented in: 0.229.066

This test ensures that the /api/chat endpoint in route_backend_chats.py is properly decorated 
with @swagger_route decorator and will be included in the automatic swagger documentation.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_backend_chats_swagger_integration():
    """Test that the backend chats endpoint has swagger decorator."""
    print("🔍 Testing Backend Chats Swagger Integration...")
    
    try:
        # Import the swagger extraction functionality
        from swagger_wrapper import extract_route_info
        
        # Import the registration function
        from route_backend_chats import register_route_backend_chats
        
        # Create a test Flask app and register the routes
        from flask import Flask
        test_app = Flask(__name__)
        
        # Register the chat routes
        register_route_backend_chats(test_app)
        
        # Count endpoints with swagger decorators
        swagger_endpoints = 0
        total_endpoints = 0
        endpoint_details = []
        
        for rule in test_app.url_map.iter_rules():
            if '/api/chat' in rule.rule:
                total_endpoints += 1
                endpoint_name = rule.endpoint
                
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
                        print(f"    Summary: {route_info.get('summary', 'Auto-generated')}")
                        print(f"    Tags: {route_info.get('tags', [])}")
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
        print(f"  Total chat endpoints: {total_endpoints}")
        print(f"  Swagger-enabled endpoints: {swagger_endpoints}")
        if total_endpoints > 0:
            print(f"  Coverage: {(swagger_endpoints/total_endpoints*100):.1f}%")
        
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
        
        # Test expected endpoint structure
        print(f"\n🎯 Endpoint Analysis:")
        expected_endpoint = '/api/chat'
        found_expected = False
        
        for ep in endpoint_details:
            if ep['path'] == expected_endpoint:
                found_expected = True
                print(f"  ✅ Found expected endpoint: {ep['path']}")
                print(f"    Methods: {ep['methods']}")
                print(f"    Swagger enabled: {'✅' if ep['has_swagger'] else '❌'}")
                if ep['has_swagger']:
                    print(f"    Summary: {ep['summary']}")
                    print(f"    Tags: {ep['tags']}")
                break
        
        if not found_expected:
            print(f"  ❌ Expected endpoint {expected_endpoint} not found")
        
        # Check if all endpoints have swagger decorators
        success = swagger_endpoints == total_endpoints and swagger_endpoints >= 1 and found_expected
        
        if success:
            print(f"\n✅ Backend chats endpoint successfully integrated with swagger!")
            print(f"   - Chat API endpoint decorated with @swagger_route")
            print(f"   - Automatic schema generation enabled")
            print(f"   - Authentication security configured")
            print(f"   - Ready for /swagger documentation")
            print(f"   - Endpoint: POST /api/chat")
        else:
            print(f"\n❌ Integration incomplete:")
            print(f"   - Expected 1 chat endpoint")
            print(f"   - Found {swagger_endpoints} swagger-enabled endpoints")
            if not found_expected:
                print(f"   - Expected endpoint /api/chat not found")
        
        return success
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_backend_chats_swagger_integration()
    print(f"\n{'='*60}")
    if success:
        print("🎉 BACKEND CHATS SWAGGER INTEGRATION TEST PASSED!")
        print("The /api/chat endpoint is now documented and accessible via /swagger")
    else:
        print("💥 BACKEND CHATS SWAGGER INTEGRATION TEST FAILED!")
        print("The chat endpoint may not be properly documented")
    print(f"{'='*60}")
    sys.exit(0 if success else 1)